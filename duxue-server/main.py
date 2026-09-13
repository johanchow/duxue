"""Local API entrypoint — equivalent to an npm start script.

Usage:
    python main.py
    ENV_FILE=.env.prod python main.py
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "true").lower() in {"1", "true", "yes"}
    uvicorn.run("app.bootstrap.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
