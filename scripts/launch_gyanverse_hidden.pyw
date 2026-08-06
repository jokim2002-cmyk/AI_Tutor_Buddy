from __future__ import annotations

import datetime as _dt
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / f"gyanverse_hidden_{_dt.date.today():%Y%m%d}.log"

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
_log = LOG_PATH.open("a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log
print(f"\n[{_dt.datetime.now().isoformat(timespec='seconds')}] Starting GyanVerse Academy hidden desktop runtime")

try:
    import flet as ft
    from gyanverse_ui import main

    oauth_port = int(os.getenv("GYANVERSE_OAUTH_PORT", "8550"))
    ft.run(main, port=oauth_port)
except BaseException:
    traceback.print_exc()
    raise
finally:
    _log.flush()
