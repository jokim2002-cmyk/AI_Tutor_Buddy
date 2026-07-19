from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

import flet as ft

from gyanverse_ui import main as gyanverse_main

APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "data" / "logs"


def main(page: ft.Page) -> None:
    try:
        gyanverse_main(page)
    except Exception:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / "phase11_startup_error.log"
        log_path.write_text(
            f"Timestamp: {datetime.now().isoformat()}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")