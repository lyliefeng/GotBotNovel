"""PyInstaller entry point for the GotBotNovel local backend."""

import os
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config


def bundled_backend_root() -> Path:
    """Return the backend data root in source and PyInstaller environments."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def migrate_database() -> None:
    root = bundled_backend_root()
    config_path = root / "alembic-sqlite.ini"
    script_location = root / "alembic" / "sqlite"
    if not config_path.is_file() or not script_location.is_dir():
        raise RuntimeError(
            f"SQLite migration resources are missing: {config_path}, {script_location}"
        )
    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("script_location", str(script_location))
    command.upgrade(alembic_config, "head")


def main() -> None:
    migrate_database()
    # A concrete import makes the application visible to PyInstaller's module
    # analysis; passing only "app.main:app" to Uvicorn is not sufficient.
    from app.main import app

    uvicorn.run(
        app,
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=int(os.environ.get("APP_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
