"""Nightly SQLite backup (docs/database.md, "Backups"; JAE-63).

Run by ``weather-station-backup.timer``. Uses SQLite's online backup API, so
a reading stored mid-copy cannot leave a torn file, then checks the copy's
integrity before giving it its final name. Any failure exits non-zero, which
systemd logs and the alert checker notices (no fresh backup).

    python -m weather_station_server.backup
"""

import logging
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from weather_station_server.config import load_backup_dir, load_db_path

log = logging.getLogger(__name__)

# Nightly copies kept: a month of history to go back to.
KEEP = 30
PATTERN = "weather-*.db"


def backup(db_path: str, dest: Path, now: datetime | None = None) -> tuple[Path, int]:
    """Copy the database into ``dest``, check it, and prune old copies.

    Returns the new file and how many readings it holds.
    """
    now = now or datetime.now(UTC)
    dest.mkdir(parents=True, exist_ok=True)
    final = dest / f"weather-{now.astimezone(UTC):%Y%m%dT%H%M%SZ}.db"
    partial = dest / f".{final.name}.partial"
    partial.unlink(missing_ok=True)
    source_uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    try:
        with (
            closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source,
            closing(sqlite3.connect(partial)) as copy,
        ):
            source.backup(copy)
            check = copy.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise sqlite3.DatabaseError(f"backup failed integrity check: {check}")
            readings = copy.execute("SELECT count(*) FROM readings").fetchone()[0]
        partial.replace(final)
    finally:
        partial.unlink(missing_ok=True)
    for old in sorted(dest.glob(PATTERN))[:-KEEP]:
        old.unlink()
        log.info("backup: removed %s (keeping %d)", old.name, KEEP)
    return final, readings


def latest_backup(dest: Path) -> Path | None:
    """The newest backup in ``dest``; names sort by time."""
    copies = sorted(dest.glob(PATTERN))
    return copies[-1] if copies else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path, dest = load_db_path(), load_backup_dir()
    try:
        path, readings = backup(db_path, dest)
    except (OSError, sqlite3.Error) as exc:
        log.error("backup: FAILED copying %s to %s: %s", db_path, dest, exc)
        return 1
    log.info("backup: wrote %s (%d readings, %d bytes)", path, readings, path.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
