"""그려줘 v0.1 (Geuryeojwo) - standalone local AI image studio."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gui.main_window import run

if __name__ == "__main__":
    raise SystemExit(run())
