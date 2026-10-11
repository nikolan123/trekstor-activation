from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

if __package__:
    from .log_store import LogStore
    from .request_logging import RequestLoggingMiddleware
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server.log_store import LogStore
    from server.request_logging import RequestLoggingMiddleware

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
WEBSITE_DIR = BASE_DIR / "website"
WEBSITE_INDEX_PATH = WEBSITE_DIR / "index.html"
ZIP_PATH = BASE_DIR / "custom.zip"
MANUAL_PATH = ASSETS_DIR / "manual.pdf"
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "trekstore.sqlite3"

ZIP_FOLDERS = {
    "music": ASSETS_DIR / "music",
    "apps": ASSETS_DIR / "apps",
    "wallpaper": ASSETS_DIR / "wallpaper",
    "pictures": ASSETS_DIR / "pictures",
    "movies": ASSETS_DIR / "movies",
}

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_zip_directory(archive: zipfile.ZipFile, name: str) -> None:
    info = zipfile.ZipInfo(name.rstrip("/") + "/", ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o40775 << 16
    archive.writestr(info, b"")


def build_custom_zip() -> None:
    ASSETS_DIR.mkdir(exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix="custom-", suffix=".zip.tmp", dir=BASE_DIR, delete=False
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)

    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as archive:
            added_anything = False
            add_zip_directory(archive, "apps")

            for zip_folder, local_folder in ZIP_FOLDERS.items():
                local_folder.mkdir(parents=True, exist_ok=True)
                if zip_folder != "apps":
                    add_zip_directory(archive, zip_folder)

                for file in sorted(local_folder.iterdir(), key=lambda path: path.name):
                    if file.name == ".gitkeep":
                        continue
                    if file.is_file():
                        archive.write(file, f"{zip_folder}/{file.name}")
                        added_anything = True

            if not added_anything:
                add_zip_directory(archive, "noop")

        temporary_path.replace(ZIP_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)

    LOGGER.info("Built %s (MD5 %s)", ZIP_PATH, md5_file(ZIP_PATH))


def create_app(
    *,
    database_path: Path | None = None,
    log_mode: str | None = None,
) -> FastAPI:
    configure_logging()
    selected_mode = (log_mode or os.getenv("LOG_MODE", "compliant")).lower()
    selected_database = database_path or Path(
        os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))
    )
    store = LogStore(selected_database, selected_mode)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await asyncio.to_thread(store.initialize)
        await asyncio.to_thread(build_custom_zip)
        LOGGER.info("Request logging mode: %s", store.mode)
        LOGGER.info("SQLite database: %s", selected_database)
        yield

    application = FastAPI(lifespan=lifespan)
    application.state.log_store = store
    application.add_middleware(RequestLoggingMiddleware, store=store)

    @application.get("/")
    async def read_root():
        # The TrekStor connectivity check accepts either HTTP 200 or 204.
        return FileResponse(WEBSITE_INDEX_PATH, media_type="text/html")

    @application.get("/variants.css")
    async def website_stylesheet():
        return FileResponse(WEBSITE_DIR / "variants.css", media_type="text/css")

    @application.get("/IBMPlexSans-Regular.woff2")
    async def website_regular_font():
        return FileResponse(WEBSITE_DIR / "IBMPlexSans-Regular.woff2")

    @application.get("/IBMPlexSans-SemiBold.woff2")
    async def website_semibold_font():
        return FileResponse(WEBSITE_DIR / "IBMPlexSans-SemiBold.woff2")

    @application.get("/tabletinit")
    async def tablet_init(request: Request):
        base_url = str(request.base_url).rstrip("/")
        payload = {
            "manual_url": (
                f"{base_url}/manual.pdf" if MANUAL_PATH.exists() else "none"
            ),
            "store_name": "TrekStor Tablet Activation",
            "custom_url": f"{base_url}/custom.zip",
            "customfile_md5": md5_file(ZIP_PATH),
        }
        LOGGER.info("Served tablet configuration")
        return JSONResponse(payload)

    @application.get("/custom.zip")
    async def custom_zip():
        return FileResponse(
            ZIP_PATH,
            media_type="application/zip",
            filename="custom.zip",
        )

    @application.get("/manual.pdf")
    async def manual():
        if not MANUAL_PATH.exists():
            LOGGER.warning("Manual asset does not exist")
            return Response(status_code=404)
        return FileResponse(
            MANUAL_PATH,
            media_type="application/pdf",
            filename="manual.pdf",
        )

    @application.get("/api/stats")
    async def statistics():
        totals = await asyncio.to_thread(store.statistics)
        return JSONResponse(totals)

    # Keep this last so real routes above win.
    @application.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def unknown_request(path: str, request: Request):
        return JSONResponse(
            status_code=404,
            content={
                "error": "unknown endpoint",
                "method": request.method,
                "path": "/" + path,
            },
        )

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    LOGGER.info("Serving on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
