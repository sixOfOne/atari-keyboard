#!/usr/bin/env python3
"""Non-interactive smoke check for the local Stella executable.

Full play requires Stella installed and a display. This script only invokes
``stella -help`` (no ROM launch), so the executable check does not require a
display. A ROM path may be supplied as argv[1], STELLA_ROM, or config/games.yaml.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def configured_rom() -> str | None:
    if len(sys.argv) > 1:
        return sys.argv[1]
    if os.environ.get("STELLA_ROM"):
        return os.environ["STELLA_ROM"]
    games_file = Path(__file__).resolve().parents[1] / "config" / "games.yaml"
    if games_file.exists():
        text = games_file.read_text(encoding="utf-8")
        match = re.search(r"^\s*rom:\s*(\S+)\s*$", text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def main() -> int:
    stella = shutil.which("stella")
    if not stella:
        print("FAIL: Stella executable 'stella' was not found on PATH.")
        print("      Install Stella before attempting full play.")
        return 1

    print(f"PASS: found Stella at {stella}")
    rom = configured_rom()
    if rom:
        rom_path = Path(rom).expanduser()
        if rom_path.exists():
            print(f"PASS: configured ROM path exists: {rom_path}")
        else:
            print(f"WARN: configured ROM path does not exist yet: {rom_path}")

    try:
        result = subprocess.run(
            [stella, "-help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: could not complete non-interactive 'stella -help': {exc}")
        return 1

    if result.returncode == 0:
        print("PASS: Stella completed the non-interactive help check.")
        print("NOTE: Full play still requires a display, a ROM, and verified Stella key bindings.")
        return 0
    print(f"FAIL: 'stella -help' exited with status {result.returncode}.")
    if result.stdout:
        print(result.stdout.strip())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
