from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .log_store import LogStore, RequestRecord, classify_download_user_agent, utc_timestamp

LOGGER = logging.getLogger(__name__)
STATISTICS = {
    "/tabletinit": "activation_requests",
    "/custom.zip": "package_downloads",
    "/manual.pdf": "manual_downloads",
}
MAX_BODY_BYTES = 16 * 1024
MAX_QUERY_BYTES = 4 * 1024
MAX_HEADER_BYTES = 16 * 1024


class RequestTooLarge(Exception):
    pass


async def reject(send, status: int) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-length", b"0")]})
    await send({"type": "http.response.body", "body": b""})


class RequestLoggingMiddleware:
    """Log activation traffic without collecting raw request data."""

    def __init__(self, app: Callable[..., Awaitable[None]], store: LogStore) -> None:
        self.app = app
        self.store = store

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        if len(scope.get("query_string", b"")) > MAX_QUERY_BYTES:
            await reject(send, 414)
            return
        if sum(len(name) + len(value) for name, value in headers) > MAX_HEADER_BYTES:
            await reject(send, 431)
            return
        for name, value in headers:
            if name.lower() == b"content-length":
                try:
                    length = int(value)
                except ValueError:
                    await reject(send, 400)
                    return
                if length < 0:
                    await reject(send, 400)
                    return
                if length > MAX_BODY_BYTES:
                    await reject(send, 413)
                    return

        request_bytes = 0

        async def limited_receive():
            nonlocal request_bytes
            message = await receive()
            if message["type"] == "http.request":
                request_bytes += len(message.get("body", b""))
                if request_bytes > MAX_BODY_BYTES:
                    raise RequestTooLarge
            return message

        path = scope.get("path", "")
        tracked = scope.get("method") == "GET" and path in STATISTICS
        status_code = 500
        response_bytes = 0
        complete = False
        response_started = False
        failed = False

        async def capture_send(message):
            nonlocal status_code, response_bytes, complete, response_started
            await send(message)
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_started = True
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
                complete = not message.get("more_body", False)

        started = time.perf_counter()
        try:
            # Never drain or buffer a body. Only limit chunks the app requests.
            await self.app(scope, limited_receive, capture_send)
        except RequestTooLarge:
            if response_started:
                failed = True
                raise
            await reject(capture_send, 413)
        except BaseException:
            failed = True
            raise
        finally:
            if tracked:
                duration_ms = (time.perf_counter() - started) * 1000
                outcome = (
                    "interrupted" if failed or not complete
                    else "server_error" if status_code >= 500
                    else "client_error" if status_code >= 400
                    else "success"
                )
                user_agent = next((value.decode("latin-1") for name, value in headers
                                   if name.lower() == b"user-agent" and len(value) <= 512), None)
                category, device = (
                    classify_download_user_agent(user_agent)
                    if path in {"/custom.zip", "/manual.pdf"}
                    else (None, None)
                )
                record = RequestRecord(
                    timestamp_utc=utc_timestamp(), route=path, method="GET",
                    status_code=status_code, duration_ms=duration_ms,
                    request_bytes=request_bytes, response_bytes=response_bytes,
                    outcome=outcome, tablet_model=device[1] if device else None,
                    android_version=device[0] if device else None,
                    build_number=device[2] if device else None,
                    user_agent_status=category,
                )
                statistic = (
                    STATISTICS[path]
                    if not failed and complete and status_code == 200 else None
                )
                try:
                    await asyncio.to_thread(self.store.record, record, statistic)
                except Exception:
                    LOGGER.error("Failed to persist activation request log")
                LOGGER.info("GET %s -> %d in %.1f ms", path, status_code, duration_ms)
