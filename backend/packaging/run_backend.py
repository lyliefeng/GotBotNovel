"""PyInstaller entry point for the GotBotNovel local backend."""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=int(os.environ.get("APP_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
