#!/usr/bin/env python3
"""Apply config/stella_keymap_joy.json into Stella's local sqlite settings.

Quit Stella before running this. Safe to re-run (replaces keymap_joy wholesale
with the repo snapshot).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    src = repo / "config" / "stella_keymap_joy.json"
    if not src.is_file():
        print(f"FAIL: missing {src}")
        return 1

    db = Path.home() / "Library/Application Support/Stella/stella.sqlite3"
    if not db.is_file():
        print(f"FAIL: Stella settings DB not found at {db}")
        print("      Launch Stella once so it creates the database, then re-run.")
        return 1

    payload = src.read_text(encoding="utf-8")
    json.loads(payload)  # validate

    backup = db.with_suffix(f".sqlite3.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(db, backup)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO settings(setting, value) VALUES('keymap_joy', ?)"
        " ON CONFLICT(setting) DO UPDATE SET value=excluded.value",
        (payload,),
    )
    con.commit()
    con.close()
    print(f"PASS: wrote keymap_joy from {src}")
    print(f"PASS: backup at {backup}")
    print("NOTE: relaunch Stella to pick up the mapping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
