#!/usr/bin/env python3
"""Non-interactive smoke check for the local Stella install.

Full play needs a display, a ROM, and verified key bindings. This script only
checks that ``stella`` resolves on PATH to an executable binary and that an
optional ROM path exists. It deliberately does **not** launch Stella: the
macOS app binary often hangs after printing ``-help``, which makes process
probes unreliable for CI-style checks.
"""
from __future__ import annotations

import os
import re
import shutil
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
        match = re.search(r"^\s*rom:\s*[\"']?([^\"']+?)[\"']?\s*$", text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def main() -> int:
    stella = shutil.which("stella")
    if not stella:
        print("FAIL: Stella executable 'stella' was not found on PATH.")
        print("      Install Stella (and/or symlink it into PATH) before full play.")
        return 1

    stella_path = Path(stella).resolve()
    if not stella_path.is_file() or not os.access(stella_path, os.X_OK):
        print(f"FAIL: Stella path is not an executable file: {stella_path}")
        return 1

    print(f"PASS: found Stella at {stella_path}")
    if "Stella.app" in str(stella_path):
        print("PASS: PATH resolves into the Stella.app bundle (expected on macOS).")

    rom = configured_rom()
    if not rom:
        print("WARN: no ROM configured (pass a path argv, STELLA_ROM, or config/games.yaml).")
        print("PASS: Stella binary smoke check succeeded.")
        print("NOTE: Full play still requires a display, a ROM, and verified Stella key bindings.")
        return 0

    rom_path = Path(rom).expanduser()
    if not rom_path.is_absolute():
        rom_path = (Path(__file__).resolve().parents[1] / rom_path).resolve()
    if not rom_path.is_file():
        print(f"FAIL: configured ROM path does not exist: {rom_path}")
        return 1
    if rom_path.stat().st_size <= 0:
        print(f"FAIL: configured ROM is empty: {rom_path}")
        return 1

    print(f"PASS: configured ROM path exists ({rom_path.stat().st_size} bytes): {rom_path}")
    print("PASS: Stella + ROM smoke check succeeded.")
    print("NOTE: Full play still requires a display and verified Stella key bindings.")
    print(f"HINT: try: stella \"{rom_path}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
