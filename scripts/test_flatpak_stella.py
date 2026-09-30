#!/usr/bin/env python3
"""Checks for Flatpak keymap apply and the TigerVNC Stella launch command."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_apply():
    path = ROOT / "scripts" / "apply_stella_keymap.py"
    spec = importlib.util.spec_from_file_location("apply_stella_keymap", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def test_keymap_apply(apply, tmp: Path) -> None:
    payload = apply.load_keymap(ROOT / "config" / "stella_keymap_joy.json")
    home = tmp / "home"
    home.mkdir()

    targets = apply.resolve_targets("auto", home, native_stella_installed=False)
    if [t.label for t in targets] != ["flatpak"]:
        fail(f"auto on a non-mac host should target flatpak only, got {targets}")

    db = apply.flatpak_settings_db(home)
    result = apply.apply_keymap(db, payload, create=True)
    if not result.ok or not result.changed:
        fail(f"fresh apply failed: {result.messages}")
    if not db.is_file():
        fail(f"flatpak DB was not created at {db}")

    con = sqlite3.connect(db)
    try:
        user_version = con.execute("PRAGMA user_version").fetchone()[0]
        rows = dict(con.execute("SELECT setting, value FROM settings"))
    finally:
        con.close()
    if user_version != 1:
        fail(f"user_version {user_version}, expected 1")
    if rows.get("event_ver") != apply.STELLA7_EVENT_VERSION:
        fail(f"event_ver {rows.get('event_ver')!r}")
    parsed = json.loads(rows["keymap_joy"])
    pairs = {(item["event"], item["key"]) for item in parsed}
    for binding in apply.REQUIRED_BINDINGS:
        if binding not in pairs:
            fail(f"missing binding {binding}")

    again = apply.apply_keymap(db, payload, create=True)
    if not again.ok or again.changed:
        fail(f"second apply should be a no-op, got {again}")
    backups = list(db.parent.glob("stella.sqlite3.bak-*"))
    if backups:
        fail(f"unchanged apply created a backup: {backups}")

    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO settings(setting, value) VALUES('event_ver', '7')"
            " ON CONFLICT(setting) DO UPDATE SET value='7'"
        )
        con.commit()
    finally:
        con.close()
    kept = apply.apply_keymap(db, payload, create=True)
    if not kept.ok:
        fail(f"apply with event_ver 7 failed: {kept.messages}")
    con = sqlite3.connect(db)
    try:
        event_ver = con.execute(
            "SELECT value FROM settings WHERE setting='event_ver'"
        ).fetchone()[0]
    finally:
        con.close()
    if event_ver != "7":
        fail(f"event_ver was overwritten: {event_ver}")

    # Default "1" must be raised or Stella 7 ignores keymap_joy.
    con = sqlite3.connect(db)
    try:
        con.execute(
            "UPDATE settings SET value='1' WHERE setting='event_ver'"
        )
        con.commit()
    finally:
        con.close()
    upgraded = apply.apply_keymap(db, payload, create=True)
    if not upgraded.ok or not upgraded.changed:
        fail(f"event_ver upgrade failed: {upgraded.messages}")
    con = sqlite3.connect(db)
    try:
        event_ver = con.execute(
            "SELECT value FROM settings WHERE setting='event_ver'"
        ).fetchone()[0]
    finally:
        con.close()
    if event_ver != "6":
        fail(f"event_ver 1 was not updated, got {event_ver}")
    backups = sorted(db.parent.glob("stella.sqlite3.bak-*"))
    if not backups:
        fail("event_ver upgrade did not leave a backup")
    con = sqlite3.connect(backups[-1])
    try:
        backed_up = con.execute(
            "SELECT value FROM settings WHERE setting='event_ver'"
        ).fetchone()[0]
    finally:
        con.close()
    if backed_up != "1":
        fail(f"backup should still have event_ver 1, got {backed_up}")

    missing = apply.apply_keymap(
        home / "Library" / "Application Support" / "Stella" / "stella.sqlite3",
        payload,
        create=False,
    )
    if missing.ok:
        fail("macos apply should fail when the DB does not exist")
    if (
        home / "Library" / "Application Support" / "Stella" / "stella.sqlite3"
    ).exists():
        fail("macos apply created a DB")

    code = apply.main(
        [
            "--target",
            "flatpak",
            "--home",
            str(home),
            "--json",
            str(ROOT / "config" / "stella_keymap_joy.json"),
        ]
    )
    if code != 0:
        fail(f"main() returned {code}")

    saved_platform = sys.platform
    sys.platform = "darwin"
    try:
        mac_targets = apply.resolve_targets(
            "auto", home, native_stella_installed=True
        )
    finally:
        sys.platform = saved_platform
    if [item.label for item in mac_targets] != ["macos"] or mac_targets[0].create:
        fail(f"darwin auto should use the existing macOS DB, got {mac_targets}")

    linux_targets = apply.resolve_targets(
        "linux", home, native_stella_installed=False
    )
    expected_linux = apply.linux_settings_db(home)
    if len(linux_targets) != 1 or linux_targets[0].path != expected_linux:
        fail(f"linux target path mismatch: {linux_targets}")
    print("PASS: flatpak keymap apply")


def test_launch_command() -> None:
    from atari_kickoff.cli import (
        FLATPAK_STELLA,
        REMOTE_SDL_ENV,
        REMOTE_STELLA_ARGS,
        build_remote_stella_cmd,
    )

    rom = "/home/ec2-user/roms/Pac-Man (NA).a26"
    foreground = build_remote_stella_cmd(rom, foreground=True)
    background = build_remote_stella_cmd(rom, foreground=False)
    wrapper = (
        ROOT / "ansible" / "roles" / "stella" / "files" / "stella-flatpak"
    ).read_text(encoding="utf-8")

    required = [
        "export DISPLAY=:1",
        "export XAUTHORITY=$HOME/.Xauthority",
        "flatpak run",
        FLATPAK_STELLA,
        "'/home/ec2-user/roms/Pac-Man (NA).a26'",
    ]
    for key, value in REMOTE_SDL_ENV:
        required.append(f"export {key}={value}")
        required.append(f"--env={key}={value}")
    for token in ("-video", "software", "-audio.enabled", "0"):
        if token not in REMOTE_STELLA_ARGS:
            fail(f"REMOTE_STELLA_ARGS missing {token}")
        required.append(token)

    for label, command in (("foreground", foreground), ("background", background)):
        for token in required:
            if token not in command:
                fail(f"{label} command missing {token!r}: {command}")
    if "nohup" not in background or "/tmp/atari-kickoff-stella.log" not in background:
        fail(f"background command should detach: {background}")
    if "nohup" in foreground:
        fail("foreground command should stay attached")

    for token in (
        "SDL_AUDIODRIVER:-dummy",
        "SDL_VIDEODRIVER:-x11",
        "LIBGL_ALWAYS_SOFTWARE:-1",
        '--env="SDL_AUDIODRIVER=${SDL_AUDIODRIVER}"',
        "--env=",
        "-video software",
        "-audio.enabled 0",
        FLATPAK_STELLA,
    ):
        if token not in wrapper:
            fail(f"stella-flatpak wrapper missing {token!r}")
    print("PASS: remote launch command")


def main() -> int:
    import tempfile

    apply = load_apply()
    with tempfile.TemporaryDirectory() as tmp:
        test_keymap_apply(apply, Path(tmp))
    test_launch_command()
    print("PASS: flatpak stella checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
