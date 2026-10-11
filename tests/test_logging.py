from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import server.main as main_module
from server.log_store import (
    LogStore,
    classify_download_user_agent,
    extract_device_info,
    extract_tablet_model,
)
from server.main import create_app
from server.request_logging import (
    MAX_BODY_BYTES,
    MAX_HEADER_BYTES,
    MAX_QUERY_BYTES,
    RequestLoggingMiddleware,
)


async def request(
    app,
    path: str,
    *,
    method: str = "GET",
    query: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    client: tuple[str, int] = ("203.0.113.42", 45678),
) -> tuple[int, bytes]:
    messages: list[dict] = []
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query,
        "root_path": "",
        "headers": headers or [(b"host", b"id.readerportal.de")],
        "client": client,
        "server": ("id.readerportal.de", 80),
    }
    await app(scope, receive, send)
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, response_body


class ModelExtractionTests(unittest.TestCase):
    def test_known_models(self):
        self.assertEqual(
            extract_tablet_model(
                "AndroidDownloadManager/4.4.2 (Linux; U; Android 4.4.2; "
                "breeze 10.1 quad Build/KOT49H)"
            ),
            "breeze 10.1 quad",
        )
        self.assertEqual(
            extract_tablet_model(
                "AndroidDownloadManager/4.4.2 (Linux; U; Android 4.4.2; "
                "SurfTab breeze 7.0 quad Build/KOT49H)"
            ),
            "SurfTab breeze 7.0 quad",
        )

    def test_arbitrary_user_agent_is_rejected(self):
        self.assertIsNone(extract_tablet_model("Mozilla/5.0 secret model"))

    def test_version_model_and_build_are_extracted(self):
        self.assertEqual(
            extract_device_info(
                "AndroidDownloadManager/4.4.2 (Linux; U; Android 4.4.2; "
                "SurfTab breeze 7.0 quad Build/KOT49H)"
            ),
            ("4.4.2", "SurfTab breeze 7.0 quad", "KOT49H"),
        )

    def test_locale_variant_is_extracted(self):
        self.assertEqual(
            extract_device_info(
                "AndroidDownloadManager/6.0 (Linux; U; Android 6.0; de-DE; "
                "SurfTab breeze 10.1 quad Build/MRA58K)"
            ),
            ("6.0", "SurfTab breeze 10.1 quad", "MRA58K"),
        )

    def test_download_client_categories(self):
        self.assertEqual(
            classify_download_user_agent("curl/8.7.1"),
            ("command_line", None),
        )
        self.assertEqual(
            classify_download_user_agent("Mozilla/5.0 Chrome/125.0"),
            ("browser", None),
        )
        self.assertEqual(
            classify_download_user_agent("AndroidDownloadManager/broken"),
            ("tablet_app_unknown", None),
        )

class CustomPackageTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_package_is_built_during_startup_and_served(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            assets = root / "assets"
            folders = {
                name: assets / name
                for name in ("music", "apps", "wallpaper", "pictures", "movies")
            }
            folders["apps"].mkdir(parents=True)
            folders["apps"].joinpath("example.apk").write_bytes(b"example apk")
            package = root / "custom.zip"
            database = root / "data" / "requests.sqlite3"

            with (
                patch.object(main_module, "BASE_DIR", root),
                patch.object(main_module, "ASSETS_DIR", assets),
                patch.object(main_module, "ZIP_FOLDERS", folders),
                patch.object(main_module, "ZIP_PATH", package),
            ):
                app = create_app(database_path=database, log_mode="compliant")
                self.assertFalse(package.exists())

                async with app.router.lifespan_context(app):
                    self.assertTrue(package.is_file())
                    status, body = await request(app, "/tabletinit")
                    self.assertEqual(status, 200)
                    expected_md5 = main_module.md5_file(package)
                    self.assertEqual(json.loads(body)["customfile_md5"], expected_md5)

                    status, body = await request(app, "/custom.zip")
                    self.assertEqual(status, 200)
                    self.assertEqual(body, package.read_bytes())

                with zipfile.ZipFile(package) as archive:
                    self.assertEqual(archive.read("apps/example.apk"), b"example apk")


class WebsiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_website_is_served_at_root_with_its_assets(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "requests.sqlite3"
            app = create_app(
                database_path=database,
                log_mode="compliant",
            )
            await asyncio.to_thread(app.state.log_store.initialize)

            status, body = await request(app, "/")
            self.assertEqual(status, 200)
            self.assertIn(b"TrekStor tablet activation", body)

            status, body = await request(app, "/variants.css")
            self.assertEqual(status, 200)
            self.assertIn(b"IBM Plex Sans", body)

            with closing(sqlite3.connect(database)) as connection:
                recorded_requests = connection.execute(
                    "SELECT COUNT(*) FROM request_log"
                ).fetchone()[0]
            self.assertEqual(recorded_requests, 0)


class LoggingModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        assets = root / "assets"
        for name, value in {
            "BASE_DIR": root,
            "ASSETS_DIR": assets,
            "ZIP_PATH": root / "custom.zip",
            "MANUAL_PATH": assets / "manual.pdf",
            "ZIP_FOLDERS": {
                name: assets / name
                for name in ("music", "apps", "wallpaper", "pictures", "movies")
            },
        }.items():
            self.enterContext(patch.object(main_module, name, value))

    async def make_app(self, mode: str):
        database = Path(self.temporary_directory.name) / f"{mode}.sqlite3"
        app = create_app(database_path=database, log_mode=mode)
        await self.enterAsyncContext(app.router.lifespan_context(app))
        return app, database

    async def test_compliant_mode_omits_identifiers_and_counts_success(self):
        app, database = await self.make_app("compliant")
        status, _ = await request(
            app,
            "/tabletinit",
            query=b"device_id=secret-device-id",
            headers=[
                (b"host", b"id.readerportal.de"),
                (b"authorization", b"Bearer secret-token"),
                (b"user-agent", b"private user agent"),
            ],
        )
        self.assertEqual(status, 200)
        package_status, _ = await request(app, "/custom.zip")
        self.assertEqual(package_status, 200)
        await request(app, "/private-name", query=b"email=niko@example.com")

        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute(
                "SELECT route, method, status_code, tablet_model FROM request_log ORDER BY id"
            ).fetchall()
            extensive_count = connection.execute(
                "SELECT COUNT(*) FROM extensive_request_log"
            ).fetchone()[0]
            serialized_database = " ".join(
                value
                for row in connection.iterdump()
                for value in [row]
            )

        self.assertEqual(rows[0], ("/tabletinit", "GET", 200, None))
        self.assertEqual(rows[1][0], "/custom.zip")
        self.assertEqual(len(rows), 2)
        self.assertEqual(extensive_count, 0)
        for secret in (
            "203.0.113.42",
            "secret-device-id",
            "secret-token",
            "private-name",
            "niko@example.com",
        ):
            self.assertNotIn(secret, serialized_database)

        stats_status, stats_body = await request(app, "/api/stats")
        self.assertEqual(stats_status, 200)
        self.assertEqual(
            json.loads(stats_body),
            {
                "activation_requests": 1,
                "package_downloads": 1,
                "manual_downloads": 0,
            },
        )

    async def test_legacy_extensive_mode_does_not_store_raw_requests(self):
        app, database = await self.make_app("extensive")
        await request(
            app, "/tabletinit", query=b"device_id=secret-id",
            headers=[(b"host", b"id.readerportal.de"),
                     (b"authorization", b"Bearer secret-token")],
            body=b"secret body",
        )
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM extensive_request_log"
            ).fetchone()[0], 0)
            dump = " ".join(connection.iterdump())
        for secret in ("secret-id", "secret-token", "secret body", "203.0.113.42"):
            self.assertNotIn(secret, dump)

    async def test_removed_aliases_use_custom_404(self):
        app, database = await self.make_app("compliant")
        for path in ("/boostrap", "/boostrap/", "/api/TrekStorProduct"):
            status, body = await request(app, path)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["path"], path)
        await request(app, "/api/stats")
        await request(app, "/tabletinit", method="POST")
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM request_log"
            ).fetchone()[0], 0)

    async def test_statistics_persist_across_store_instances(self):
        app, database = await self.make_app("compliant")
        await request(app, "/tabletinit")
        second_store = LogStore(database, "compliant")
        second_store.initialize()
        self.assertEqual(second_store.statistics()["activation_requests"], 1)

        extensive_store = LogStore(database, "extensive")
        extensive_store.initialize()
        self.assertEqual(extensive_store.statistics()["activation_requests"], 1)

    async def test_lifespan_initializes_database(self):
        database = Path(self.temporary_directory.name) / "lifespan.sqlite3"
        app = create_app(database_path=database, log_mode="compliant")
        self.assertFalse(database.exists())
        async with app.router.lifespan_context(app):
            self.assertTrue(database.exists())

    async def test_model_is_stored_only_for_download_route(self):
        app, database = await self.make_app("compliant")
        user_agent = (
            b"AndroidDownloadManager/4.4.2 (Linux; U; Android 4.4.2; "
            b"breeze 10.1 quad Build/KOT49H)"
        )
        headers = [
            (b"host", b"id.readerportal.de"),
            (b"user-agent", user_agent),
        ]
        await request(app, "/custom.zip", headers=headers)
        await request(app, "/unmatched", headers=headers)

        with closing(sqlite3.connect(database)) as connection:
            models = connection.execute(
                """SELECT route, tablet_model, android_version, build_number,
                          user_agent_status FROM request_log ORDER BY id"""
            ).fetchall()
        self.assertEqual(
            models[0],
            ("/custom.zip", "breeze 10.1 quad", "4.4.2", "KOT49H", "tablet_app"),
        )
        self.assertEqual(len(models), 1)

    async def test_unrecognized_download_user_agent_is_not_retained(self):
        app, database = await self.make_app("compliant")
        await request(
            app,
            "/custom.zip",
            headers=[(b"user-agent", b"private unusual user agent")],
        )
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                """SELECT tablet_model, android_version, build_number,
                          user_agent_status FROM request_log"""
            ).fetchone()
            dump = " ".join(connection.iterdump())
        self.assertEqual(row, (None, None, None, "other"))
        self.assertNotIn("private unusual user agent", dump)

    async def test_exceptions_record_outcome_without_exception_text(self):
        database = Path(self.temporary_directory.name) / "exception.sqlite3"
        store = LogStore(database, "extensive")
        store.initialize()

        async def failing_app(scope, receive, send):
            raise RuntimeError("complete diagnostic exception")

        middleware = RequestLoggingMiddleware(failing_app, store)
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": b"failure body"}

        async def send(message):
            pass

        scope = {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "http_version": "1.1",
            "path": "/tabletinit",
            "raw_path": b"/failing/private",
            "query_string": b"secret=yes",
            "headers": [(b"authorization", b"Bearer exception-secret")],
            "client": ("198.51.100.9", 9999),
        }
        with self.assertRaisesRegex(RuntimeError, "diagnostic exception"):
            await middleware(scope, receive, send)

        with closing(sqlite3.connect(database)) as connection:
            outcome = connection.execute(
                "SELECT outcome FROM request_log"
            ).fetchone()[0]
            exception = connection.execute(
                "SELECT exception FROM extensive_request_log"
            ).fetchone()
        self.assertEqual(outcome, "interrupted")
        self.assertIsNone(exception)

    async def test_log_write_failure_does_not_break_response(self):
        app, _ = await self.make_app("compliant")

        def fail_record(*args, **kwargs):
            raise sqlite3.OperationalError("simulated write failure")

        app.state.log_store.record = fail_record
        status, body = await request(app, "/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"activation_requests": 0, "package_downloads": 0, "manual_downloads": 0})

    async def test_request_limits_and_boundaries(self):
        app, database = await self.make_app("compliant")
        for path in ("/tabletinit", "/unknown"):
            with self.subTest(path=path):
                status, _ = await request(app, path, headers=[
                    (b"content-length", str(MAX_BODY_BYTES + 1).encode()),
                ])
                self.assertEqual(status, 413)
                status, _ = await request(app, path, query=b"x" * (MAX_QUERY_BYTES + 1))
                self.assertEqual(status, 414)
                status, _ = await request(app, path, headers=[
                    (b"x", b"x" * MAX_HEADER_BYTES),
                ])
                self.assertEqual(status, 431)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM request_log"
            ).fetchone()[0], 0)
        status, _ = await request(app, "/tabletinit",
            query=b"x" * MAX_QUERY_BYTES,
            headers=[(b"content-length", str(MAX_BODY_BYTES).encode())],
            body=b"x" * MAX_BODY_BYTES)
        self.assertEqual(status, 200)
        status, _ = await request(app, "/unknown", headers=[
            (b"x", b"x" * (MAX_HEADER_BYTES - 1)),
        ])
        self.assertEqual(status, 404)

    async def test_records_and_counters_are_kept_indefinitely(self):
        app, database = await self.make_app("compliant")
        await request(app, "/tabletinit")
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE request_log SET timestamp_utc = '2000-01-01T00:00:00+00:00'")
        store = LogStore(database, "compliant")
        store.initialize()
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT timestamp_utc FROM request_log"
            ).fetchone()[0], "2000-01-01T00:00:00+00:00")
        self.assertEqual(store.statistics()["activation_requests"], 1)


class MiddlewareLimitsTests(unittest.IsolatedAsyncioTestCase):
    class Store:
        def __init__(self):
            self.records = []

        def record(self, record, statistic):
            self.records.append((record, statistic))

    async def test_does_not_read_bodies_and_does_not_limit_downloads(self):
        store = self.Store()
        response = b"x" * (MAX_BODY_BYTES * 4)

        async def receive():
            self.fail("Middleware must not pre-read the request body")

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": response})

        async def send(message):
            pass

        await RequestLoggingMiddleware(app, store)(
            {"type": "http", "path": "/custom.zip", "method": "GET"}, receive, send)
        self.assertEqual(store.records[0][0].response_bytes, len(response))
        self.assertEqual(store.records[0][0].request_bytes, 0)
        self.assertEqual(store.records[0][1], "package_downloads")

    async def test_chunked_body_is_limited_without_buffering_or_replay(self):
        store = self.Store()
        messages = []
        received = []
        chunk = {"type": "http.request", "body": b"x" * 4096, "more_body": True}

        async def receive():
            return chunk

        async def app(scope, receive, send):
            while True:
                received.append(await receive())

        async def send(message):
            messages.append(message)

        await RequestLoggingMiddleware(app, store)(
            {"type": "http", "path": "/anything", "method": "POST"}, receive, send)
        self.assertEqual(messages[0]["status"], 413)
        self.assertEqual(len(received), 4)
        self.assertTrue(all(message is chunk for message in received))
        self.assertEqual(store.records, [])

    async def test_partial_cached_and_incomplete_responses_do_not_count(self):
        for status, complete in ((206, True), (304, True), (200, False), (500, True)):
            with self.subTest(status=status, complete=complete):
                store = self.Store()

                async def app(scope, receive, send):
                    await send({"type": "http.response.start", "status": status})
                    await send({"type": "http.response.body", "body": b"x", "more_body": not complete})

                async def receive():
                    self.fail("Unexpected receive")

                async def send(message):
                    pass

                await RequestLoggingMiddleware(app, store)(
                    {"type": "http", "path": "/custom.zip", "method": "GET"}, receive, send)
                self.assertEqual(len(store.records), 1)
                self.assertIsNone(store.records[0][1])

    async def test_disconnect_does_not_count_a_download(self):
        store = self.Store()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b"partial", "more_body": True})
            await send({"type": "http.response.body", "body": b"final"})

        async def receive():
            self.fail("Unexpected receive")

        async def send(message):
            if message.get("body") == b"final":
                raise OSError("disconnected private client")

        with self.assertRaises(OSError):
            await RequestLoggingMiddleware(app, store)(
                {"type": "http", "path": "/custom.zip", "method": "GET"}, receive, send)
        self.assertIsNone(store.records[0][1])
        self.assertEqual(store.records[0][0].outcome, "interrupted")


if __name__ == "__main__":
    unittest.main()
