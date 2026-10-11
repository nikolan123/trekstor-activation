from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 2
STAT_KEYS = (
    "activation_requests",
    "package_downloads",
    "manual_downloads",
)

ANDROID_DOWNLOAD_MANAGER_PREFIX = "androiddownloadmanager/"
ANDROID_VERSION = re.compile(r"^[0-9][0-9A-Za-z._+-]{0,31}$")
TABLET_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()/-]{0,79}$")
BUILD_NUMBER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+/-]{0,127}$")


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def extract_device_info(user_agent: str | None) -> tuple[str, str, str] | None:
    if not user_agent or len(user_agent) > 512:
        return None
    normalized = user_agent.strip()
    if not normalized.lower().startswith(ANDROID_DOWNLOAD_MANAGER_PREFIX):
        return None
    if not normalized.endswith(")") or "(" not in normalized:
        return None

    details = normalized[normalized.find("(") + 1 : -1]
    parts = [" ".join(part.split()) for part in details.split(";")]
    android_index = next(
        (index for index, part in enumerate(parts) if part.startswith("Android ")),
        None,
    )
    if android_index is None:
        return None

    android_version = parts[android_index].removeprefix("Android ")
    for part in reversed(parts[android_index + 1 :]):
        if " Build/" not in part:
            continue
        model, build_number = part.rsplit(" Build/", 1)
        if (
            ANDROID_VERSION.fullmatch(android_version)
            and TABLET_MODEL.fullmatch(model)
            and BUILD_NUMBER.fullmatch(build_number)
        ):
            return android_version, model, build_number
    return None


def classify_download_user_agent(
    user_agent: str | None,
) -> tuple[str, tuple[str, str, str] | None]:
    """Classify a download client without retaining its raw User-Agent."""

    device_info = extract_device_info(user_agent)
    if device_info:
        return "tablet_app", device_info

    normalized = (user_agent or "").strip().lower()
    if normalized.startswith(ANDROID_DOWNLOAD_MANAGER_PREFIX):
        return "tablet_app_unknown", None
    if normalized.startswith(("curl/", "wget/", "python-requests/", "httpie/")):
        return "command_line", None
    if normalized.startswith("mozilla/") or any(
        browser in normalized
        for browser in ("chrome/", "firefox/", "safari/", "edg/", "opr/")
    ):
        return "browser", None
    return "other", None


def extract_tablet_model(user_agent: str | None) -> str | None:
    device_info = extract_device_info(user_agent)
    return device_info[1] if device_info else None


@dataclass(frozen=True)
class RequestRecord:
    timestamp_utc: str
    route: str
    method: str
    status_code: int
    duration_ms: float
    request_bytes: int
    response_bytes: int
    outcome: str
    tablet_model: str | None
    android_version: str | None = None
    build_number: str | None = None
    user_agent_status: str | None = None


class LogStore:
    def __init__(self, database_path: Path, mode: str) -> None:
        if mode not in {"compliant", "extensive"}:
            raise ValueError("LOG_MODE must be 'compliant' or 'extensive'")
        self.database_path = database_path
        # Legacy 'extensive' deployments now use the same privacy-safe fields.
        self.mode = "compliant"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise RuntimeError(f"Could not enable SQLite WAL mode: {journal_mode}")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS request_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    route TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    request_bytes INTEGER NOT NULL,
                    response_bytes INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    tablet_model TEXT,
                    android_version TEXT,
                    build_number TEXT,
                    user_agent_status TEXT
                );

                CREATE TABLE IF NOT EXISTS extensive_request_log (
                    request_id INTEGER PRIMARY KEY,
                    client_ip TEXT,
                    client_port INTEGER,
                    scheme TEXT NOT NULL,
                    http_version TEXT NOT NULL,
                    raw_path BLOB NOT NULL,
                    query_string BLOB NOT NULL,
                    headers_json TEXT NOT NULL,
                    body BLOB NOT NULL,
                    exception TEXT,
                    FOREIGN KEY(request_id) REFERENCES request_log(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS statistics (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0 CHECK(value >= 0)
                );
                """
            )
            version_row = connection.execute(
                "SELECT version FROM schema_info LIMIT 1"
            ).fetchone()
            if version_row is None:
                connection.execute(
                    "INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,)
                )
            elif version_row[0] == 1:
                connection.execute("ALTER TABLE request_log ADD COLUMN android_version TEXT")
                connection.execute("ALTER TABLE request_log ADD COLUMN build_number TEXT")
                connection.execute("ALTER TABLE request_log ADD COLUMN user_agent_status TEXT")
                connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
            elif version_row[0] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported database schema {version_row[0]}; expected {SCHEMA_VERSION}"
                )
            connection.executemany(
                "INSERT OR IGNORE INTO statistics(name, value) VALUES (?, 0)",
                ((key,) for key in STAT_KEYS),
            )

    def record(self, record: RequestRecord, statistic: str | None = None) -> None:
        if statistic is not None and statistic not in STAT_KEYS:
            raise ValueError(f"Unknown statistic: {statistic}")

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO request_log(
                    timestamp_utc, route, method, status_code, duration_ms,
                    request_bytes, response_bytes, outcome, tablet_model,
                    android_version, build_number, user_agent_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp_utc,
                    record.route,
                    record.method,
                    record.status_code,
                    record.duration_ms,
                    record.request_bytes,
                    record.response_bytes,
                    record.outcome,
                    record.tablet_model,
                    record.android_version,
                    record.build_number,
                    record.user_agent_status,
                ),
            )

            if statistic is not None:
                connection.execute(
                    "UPDATE statistics SET value = value + 1 WHERE name = ?",
                    (statistic,),
                )

    def statistics(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            rows = dict(connection.execute("SELECT name, value FROM statistics"))
        return {key: int(rows.get(key, 0)) for key in STAT_KEYS}
