#!/usr/bin/env python3
"""Apply config/stella_keymap_joy.json into Stella's sqlite settings.

Quit Stella before running this. Safe to re-run: keymap_joy is replaced with
the repo snapshot when the parsed JSON differs.

Stella 7 loads keymap_joy only when the settings row event_ver equals
Event::VERSION (6 in the Flatpak 7.0 build). A fresh database leaves
event_ver at the compiled default "1", and Stella then ignores the custom
map and overwrites it with defaults on exit. This script sets event_ver to 6
when the row is missing or still that default, and leaves any other value
(for example a newer Stella that already saved its own version) in place.

Paths:
  macOS app:  ~/Library/Application Support/Stella/stella.sqlite3
  Linux/XDG:  ${XDG_CONFIG_HOME:-~/.config}/stella/stella.sqlite3
  Flatpak:    ~/.var/app/io.github.stella_emu.Stella/config/stella/stella.sqlite3

Flatpak sets XDG_CONFIG_HOME to ~/.var/app/<id>/config inside the sandbox.
Stella appends /stella and stores stella.sqlite3 there. Copying the JSON to
~/.config/atari-kickoff/ does not change what the Flatpak app reads.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


FLATPAK_APP_ID = "io.github.stella_emu.Stella"
# Stella 7.0 src/emucore/Event.hxx: Event::VERSION. keymap_joy is ignored
# unless the stored event_ver matches the build that is running.
STELLA7_EVENT_VERSION = "6"
# Settings.cxx default before PhysicalKeyboardHandler::saveMapping().
DEFAULT_EVENT_VERSIONS = {"", "0", "1"}
SETTINGS_DDL = (
    "CREATE TABLE IF NOT EXISTS settings ("
    "setting TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID"
)

# Bindings this project promises (see config/keymap.yaml). Stella stores
# arrow keys as up/down/left/right, matching the macOS snapshot.
REQUIRED_BINDINGS = (
    ("LeftJoystickUp", "w"),
    ("LeftJoystickLeft", "a"),
    ("LeftJoystickDown", "s"),
    ("LeftJoystickRight", "d"),
    ("LeftJoystickUp", "up"),
    ("LeftJoystickDown", "down"),
    ("LeftJoystickLeft", "left"),
    ("LeftJoystickRight", "right"),
    ("LeftJoystickFire", "space"),
    ("LeftJoystickFire", "lctrl"),
)


@dataclass
class DbTarget:
    label: str
    path: Path
    create: bool


@dataclass
class ApplyResult:
    ok: bool
    changed: bool
    db: Path
    messages: list[str] = field(default_factory=list)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def macos_settings_db(home: Path) -> Path:
    return home / "Library" / "Application Support" / "Stella" / "stella.sqlite3"


def linux_settings_db(home: Path, xdg_config_home: str | None = None) -> Path:
    if xdg_config_home:
        base = Path(xdg_config_home).expanduser()
    else:
        base = home / ".config"
    return base / "stella" / "stella.sqlite3"


def flatpak_settings_db(home: Path, app_id: str = FLATPAK_APP_ID) -> Path:
    # Host view of the sandbox XDG_CONFIG_HOME, plus Stella's /stella base dir.
    return home / ".var" / "app" / app_id / "config" / "stella" / "stella.sqlite3"


def find_keymap_json(explicit: str | None, home: Path) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    bundled = repo_root() / "config" / "stella_keymap_joy.json"
    # When this file lives in the repo, parents[1]/config is the snapshot.
    # An Ansible-installed copy lives in ~/.config/atari-kickoff/ and the
    # repo-relative path does not exist there.
    if bundled.is_file() and Path(__file__).resolve().parent.name == "scripts":
        return bundled
    candidates = [
        home / ".config" / "atari-kickoff" / "stella_keymap_joy.json",
        Path(__file__).resolve().with_name("stella_keymap_joy.json"),
        bundled,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_keymap(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_text(encoding="utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a JSON list of keymap entries")
    pairs = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"{path} contains a non-object keymap entry")
        pairs.add((item.get("event"), item.get("key")))
    missing = [pair for pair in REQUIRED_BINDINGS if pair not in pairs]
    if missing:
        formatted = ", ".join(f"{event}={key}" for event, key in missing)
        raise ValueError(f"{path} is missing bindings: {formatted}")
    return payload


def resolve_targets(
    target: str,
    home: Path,
    *,
    app_id: str = FLATPAK_APP_ID,
    xdg_config_home: str | None = None,
    native_stella_installed: bool | None = None,
) -> list[DbTarget]:
    """Databases to update for a target name.

    ``auto`` follows the host: macOS uses the app-support DB (it must already
    exist). Linux always prepares the Flatpak sandbox DB, because
    ``play --target aws`` launches Flatpak Stella, and also updates a native
    ``~/.config/stella`` DB when that file or a ``stella`` binary is present.
    """
    flatpak = DbTarget(
        "flatpak", flatpak_settings_db(home, app_id), create=True
    )
    native = DbTarget(
        "linux",
        linux_settings_db(home, xdg_config_home),
        create=True,
    )
    macos = DbTarget("macos", macos_settings_db(home), create=False)

    if target == "flatpak":
        return [flatpak]
    if target == "linux":
        return [native]
    if target == "macos":
        return [macos]
    if target != "auto":
        raise ValueError(f"unknown target {target}")

    if sys.platform == "darwin":
        return [macos]

    targets = [flatpak]
    native_path = native.path
    if native_stella_installed is None:
        native_stella_installed = _stella_on_path()
    if native_path.is_file() or native_stella_installed:
        # Avoid creating a second DB that Flatpak will not read unless a
        # native binary or an existing settings file is actually in play.
        targets.append(native)
    return targets


def _stella_on_path() -> bool:
    from shutil import which

    return which("stella") is not None


def _json_equal(stored: str | None, payload: str) -> bool:
    if stored is None:
        return False
    try:
        return json.loads(stored) == json.loads(payload)
    except json.JSONDecodeError:
        return False


def _backup(con: sqlite3.Connection, db: Path) -> Path:
    """Snapshot via the sqlite backup API so a Stella WAL file is included."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db.with_suffix(f".sqlite3.bak-{stamp}")
    n = 0
    while backup.exists():
        n += 1
        backup = db.with_suffix(f".sqlite3.bak-{stamp}-{n}")
    dest = sqlite3.connect(backup)
    try:
        con.backup(dest)
        dest.commit()
    finally:
        dest.close()
    return backup


def apply_keymap(db: Path, payload: str, *, create: bool) -> ApplyResult:
    messages: list[str] = []
    if not db.is_file() and not create:
        return ApplyResult(
            ok=False,
            changed=False,
            db=db,
            messages=[
                f"FAIL: Stella settings DB not found at {db}",
                "      Launch Stella once so it creates the database, then re-run.",
            ],
        )

    created = not db.is_file()
    db.parent.mkdir(parents=True, exist_ok=True)
    try:
        db.parent.chmod(0o755)
    except OSError:
        pass

    try:
        con = sqlite3.connect(db, timeout=5)
    except sqlite3.OperationalError as exc:
        return ApplyResult(
            ok=False,
            changed=False,
            db=db,
            messages=[f"FAIL: cannot open {db}: {exc}"],
        )

    changed = False
    try:
        con.execute(SETTINGS_DDL)
        user_version = con.execute("PRAGMA user_version").fetchone()[0]
        # Stella 7 accepts user_version 0 (first-run import) or 1. Any other
        # value makes StellaDb::migrate() throw and settings are not loaded.
        if user_version not in (0, 1):
            return ApplyResult(
                ok=False,
                changed=False,
                db=db,
                messages=[
                    f"FAIL: {db} has sqlite user_version {user_version}; "
                    "Stella 7 only opens version 0 or 1."
                ],
            )

        row = con.execute(
            "SELECT value FROM settings WHERE setting = 'keymap_joy'"
        ).fetchone()
        stored = row[0] if row else None
        keymap_changed = not _json_equal(stored, payload)
        event_needs = _event_ver_needs_update(con)
        version_needs = created or user_version == 0
        if not keymap_changed and not event_needs and not version_needs:
            messages.append(f"PASS: keymap_joy already current in {db}")
            messages.append(f"PASS: event_ver kept at {_event_ver(con)}")
            messages.append(f"PASS: database {db}")
            return ApplyResult(ok=True, changed=False, db=db, messages=messages)

        if not created:
            backup = _backup(con, db)
            messages.append(f"PASS: backup at {backup}")
        if version_needs:
            con.execute("PRAGMA user_version = 1")
            changed = True
            messages.append("PASS: updated user_version to 1")
        if keymap_changed:
            con.execute(
                "INSERT INTO settings(setting, value) VALUES('keymap_joy', ?)"
                " ON CONFLICT(setting) DO UPDATE SET value=excluded.value",
                (payload,),
            )
            changed = True
            messages.append("PASS: wrote keymap_joy")
        else:
            messages.append(f"PASS: keymap_joy already current in {db}")
        if _set_event_ver(con, messages):
            changed = True

        con.commit()
        written = con.execute(
            "SELECT value FROM settings WHERE setting = 'keymap_joy'"
        ).fetchone()
        if written is None or not _json_equal(written[0], payload):
            return ApplyResult(
                ok=False,
                changed=False,
                db=db,
                messages=[f"FAIL: keymap_joy readback mismatch in {db}"],
            )
    except sqlite3.OperationalError as exc:
        locked = "locked" in str(exc).lower()
        hint = " Quit Stella and re-run." if locked else ""
        return ApplyResult(
            ok=False,
            changed=False,
            db=db,
            messages=[f"FAIL: sqlite error on {db}: {exc}.{hint}"],
        )
    finally:
        try:
            con.close()
        except sqlite3.ProgrammingError:
            pass

    try:
        os.chmod(db, 0o644)
    except OSError:
        pass

    messages.append(f"PASS: database {db}")
    return ApplyResult(ok=True, changed=changed, db=db, messages=messages)


def _event_ver(con: sqlite3.Connection) -> str | None:
    row = con.execute(
        "SELECT value FROM settings WHERE setting = 'event_ver'"
    ).fetchone()
    if row is None:
        return None
    return str(row[0]).strip()


def _event_ver_needs_update(con: sqlite3.Connection) -> bool:
    current = _event_ver(con)
    return current is None or current in DEFAULT_EVENT_VERSIONS


def _set_event_ver(con: sqlite3.Connection, messages: list[str]) -> bool:
    current = _event_ver(con)
    if current is None or current in DEFAULT_EVENT_VERSIONS:
        con.execute(
            "INSERT INTO settings(setting, value) VALUES('event_ver', ?)"
            " ON CONFLICT(setting) DO UPDATE SET value=excluded.value",
            (STELLA7_EVENT_VERSION,),
        )
        messages.append(f"PASS: updated event_ver to {STELLA7_EVENT_VERSION}")
        return True
    messages.append(f"PASS: event_ver kept at {current}")
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=["auto", "macos", "linux", "flatpak"],
        default="auto",
        help="which Stella settings DB to update (default: auto)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        help="keymap snapshot (default: repo config or ~/.config/atari-kickoff/)",
    )
    parser.add_argument(
        "--db",
        help="write this sqlite file instead of the target's default path",
    )
    parser.add_argument(
        "--home",
        help="home directory used to resolve default DB paths (tests and alternate users)",
    )
    parser.add_argument(
        "--flatpak-id",
        default=FLATPAK_APP_ID,
        help=f"Flatpak application id (default: {FLATPAK_APP_ID})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.home).expanduser() if args.home else Path.home()
    src = find_keymap_json(args.json_path, home)
    try:
        payload = load_keymap(src)
    except FileNotFoundError:
        print(f"FAIL: missing {src}")
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    xdg = None if args.home else os.environ.get("XDG_CONFIG_HOME")
    try:
        if args.db:
            targets = [DbTarget("explicit", Path(args.db).expanduser(), create=True)]
        else:
            targets = resolve_targets(
                args.target,
                home,
                app_id=args.flatpak_id,
                xdg_config_home=xdg,
            )
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"Keymap source: {src}")
    print("NOTE: quit Stella before applying; a running app can overwrite the database on exit.")
    failed = False
    for target in targets:
        result = apply_keymap(target.path, payload, create=target.create)
        print(f"Target: {target.label}")
        for line in result.messages:
            print(line)
        if not result.ok:
            failed = True
    if failed:
        return 1
    print("NOTE: relaunch Stella to pick up the mapping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
