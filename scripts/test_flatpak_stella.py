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
        AUDIO_AUTO,
        AUDIO_OFF,
        AUDIO_ON,
        FLATPAK_STELLA,
        REMOTE_AUDIO_CAPTURE_BIN,
        REMOTE_AUDIO_MODE_FILE,
        REMOTE_STELLA_BIN,
        build_remote_audio_capture_cmd,
        build_remote_stella_cmd,
        parse_remote_launch_output,
    )

    rom = "/home/ec2-user/roms/Pac-Man (NA).a26"
    foreground = build_remote_stella_cmd(rom, foreground=True)
    background = build_remote_stella_cmd(rom, foreground=False)
    forced_off = build_remote_stella_cmd(rom, foreground=False, audio=AUDIO_OFF)
    forced_on = build_remote_stella_cmd(rom, foreground=True, audio=AUDIO_ON)
    wrapper = (
        ROOT / "ansible" / "roles" / "stella" / "files" / "stella-flatpak"
    ).read_text(encoding="utf-8")

    required = [
        "export DISPLAY=:1",
        "export XAUTHORITY=$HOME/.Xauthority",
        'export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"',
        f"export ATARI_AUDIO={AUDIO_AUTO}",
        REMOTE_STELLA_BIN,
        "'/home/ec2-user/roms/Pac-Man (NA).a26'",
    ]
    for label, command in (("foreground", foreground), ("background", background)):
        for token in required:
            if token not in command:
                fail(f"{label} command missing {token!r}: {command}")
        if "SDL_AUDIODRIVER=dummy" in command or "-audio.enabled 0" in command:
            fail(f"{label} command must not hardcode silent audio: {command}")
    if "nohup" not in background or "/tmp/atari-kickoff-stella.log" not in background:
        fail(f"background command should detach: {background}")
    if REMOTE_AUDIO_MODE_FILE not in background or "echo unknown" not in background:
        fail(f"background command should report the audio driver: {background}")
    if "nohup" in foreground:
        fail("foreground command should stay attached")
    if f"export ATARI_AUDIO={AUDIO_OFF}" not in forced_off:
        fail(f"--no-audio command missing ATARI_AUDIO=off: {forced_off}")
    if f"export ATARI_AUDIO={AUDIO_ON}" not in forced_on:
        fail(f"--audio command missing ATARI_AUDIO=on: {forced_on}")

    for token in (
        "ATARI_AUDIO",
        "stella-audio-setup",
        "driver=pulseaudio",
        "driver=dummy",
        "audio_enabled=0",
        "SDL_VIDEODRIVER=x11",
        "LIBGL_ALWAYS_SOFTWARE=1",
        '--env="SDL_AUDIODRIVER=${SDL_AUDIODRIVER}"',
        "--socket=pulseaudio",
        "-video software",
        '-audio.enabled "${audio_enabled}"',
        "PULSE_SERVER",
        REMOTE_AUDIO_MODE_FILE,
        FLATPAK_STELLA,
    ):
        if token not in wrapper:
            fail(f"stella-flatpak wrapper missing {token!r}")
    executable_lines = "\n".join(
        line for line in wrapper.splitlines() if not line.lstrip().startswith("#")
    )
    if "-audio.enabled 0" in executable_lines:
        fail("wrapper must not hardcode -audio.enabled 0")

    capture = build_remote_audio_capture_cmd()
    if REMOTE_AUDIO_CAPTURE_BIN not in capture or "XDG_RUNTIME_DIR" not in capture:
        fail(f"capture command incomplete: {capture}")
    pid, mode = parse_remote_launch_output("4242\npulseaudio\n")
    if pid != "4242" or mode != "pulseaudio":
        fail(f"launch output parse failed: {pid!r} {mode!r}")
    unknown_pid, unknown_mode = parse_remote_launch_output("")
    if unknown_pid != "(unknown)" or unknown_mode != "unknown":
        fail(f"empty launch output parse failed: {unknown_pid!r} {unknown_mode!r}")

    import subprocess

    for label, snippet in (
        ("foreground", foreground),
        ("background", background),
        ("capture", build_remote_audio_capture_cmd()),
    ):
        checked = subprocess.run(
            ["bash", "-n", "-c", snippet],
            check=False,
            capture_output=True,
            text=True,
        )
        if checked.returncode != 0:
            fail(f"bash -n {label} failed: {checked.stderr}\n{snippet}")
    print("PASS: remote launch command")


def _run_wrapper(tmp: Path, *, audio: str, setup_rc: int | None, probe_rc: int) -> tuple[str, list[str]]:
    """Run stella-flatpak with fakes. setup_rc None means the setup script is absent."""
    import os
    import subprocess

    fake = tmp / "bin"
    fake.mkdir(parents=True)
    log = tmp / "flatpak.log"
    mode = tmp / "audio-mode"
    setup = tmp / "setup"
    flatpak = fake / "flatpak"
    flatpak.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$@" >> "$FLATPAK_LOG"\n'
        'printf "\\n---\\n" >> "$FLATPAK_LOG"\n'
        'if [[ " $* " == *" --command=sh "* ]]; then\n'
        '  exit "${PROBE_RC:-1}"\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    flatpak.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake}:{env.get('PATH', '')}"
    env["ATARI_AUDIO"] = audio
    env["ATARI_AUDIO_MODE_FILE"] = str(mode)
    env["FLATPAK_LOG"] = str(log)
    env["PROBE_RC"] = str(probe_rc)
    env["DISPLAY"] = ":1"
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    if setup_rc is None:
        env["STELLA_AUDIO_SETUP"] = str(tmp / "missing-setup")
    else:
        setup.write_text(f"#!/bin/bash\nexit {setup_rc}\n", encoding="utf-8")
        setup.chmod(0o755)
        env["STELLA_AUDIO_SETUP"] = str(setup)
    wrapper = ROOT / "ansible" / "roles" / "stella" / "files" / "stella-flatpak"
    completed = subprocess.run(
        ["bash", str(wrapper), str(tmp / "game.a26")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        fail(
            f"wrapper exited {completed.returncode} audio={audio}: "
            f"{completed.stderr}"
        )
    if not mode.is_file():
        fail("wrapper did not write the audio mode file")
    recorded = log.read_text(encoding="utf-8") if log.is_file() else ""
    launches = [
        block.splitlines()
        for block in recorded.split("\n---\n")
        if block.strip() and "--command=sh" not in block
    ]
    if len(launches) != 1:
        fail(f"expected one Stella launch, got {launches!r} from {recorded!r}")
    return mode.read_text(encoding="utf-8").strip(), launches[0]


def _assert_launch(args: list[str], *, driver: str, enabled: str) -> None:
    joined = "\n".join(args)
    if "io.github.stella_emu.Stella" not in args:
        fail(f"launch missing app id: {args}")
    if "-video" not in args or "software" not in args:
        fail(f"launch missing software video: {args}")
    if f"--env=SDL_AUDIODRIVER={driver}" not in args:
        fail(f"launch driver env {driver!r} not in {args}")
    if "--env=LIBGL_ALWAYS_SOFTWARE=1" not in args or "--env=SDL_VIDEODRIVER=x11" not in args:
        fail(f"launch missing software GL env: {args}")
    enabled_at = args.index("-audio.enabled") + 1
    if args[enabled_at] != enabled:
        fail(f"audio enabled {args[enabled_at]!r}, expected {enabled} in {joined}")


def test_wrapper_audio_decision(tmp: Path) -> None:
    mode, args = _run_wrapper(tmp / "off", audio="off", setup_rc=0, probe_rc=0)
    if mode != "dummy":
        fail(f"--no-audio should stay dummy, got {mode}")
    _assert_launch(args, driver="dummy", enabled="0")
    if any("--command=sh" in arg for arg in args):
        fail("silent launch should not be the sandbox probe")

    mode, args = _run_wrapper(tmp / "auto-missing", audio="auto", setup_rc=None, probe_rc=0)
    if mode != "dummy":
        fail(f"missing sink should stay dummy, got {mode}")
    _assert_launch(args, driver="dummy", enabled="0")

    mode, args = _run_wrapper(tmp / "setup-fail", audio="on", setup_rc=1, probe_rc=0)
    if mode != "dummy":
        fail(f"failed setup should stay dummy, got {mode}")
    _assert_launch(args, driver="dummy", enabled="0")

    mode, args = _run_wrapper(tmp / "probe-fail", audio="on", setup_rc=0, probe_rc=1)
    if mode != "dummy":
        fail(f"failed sandbox probe should stay dummy, got {mode}")
    _assert_launch(args, driver="dummy", enabled="0")

    mode, args = _run_wrapper(tmp / "pulse", audio="auto", setup_rc=0, probe_rc=0)
    if mode != "pulseaudio":
        fail(f"ready sink should use pulseaudio, got {mode}")
    _assert_launch(args, driver="pulseaudio", enabled="1")
    if "--socket=pulseaudio" not in args:
        fail(f"pulse launch missing pulse socket: {args}")
    print("PASS: wrapper audio decision")


def test_audio_player_and_flags() -> None:
    import atari_kickoff.cli as cli

    original_which = cli.shutil.which

    def which_ffplay(name: str) -> str | None:
        return "/usr/bin/ffplay" if name == "ffplay" else None

    def which_sox(name: str) -> str | None:
        return "/usr/bin/sox" if name == "sox" else None

    def which_none(_name: str) -> str | None:
        return None

    cli.shutil.which = which_ffplay
    try:
        player = cli.local_pcm_player_command()
    finally:
        cli.shutil.which = original_which
    if (
        not player
        or player[0] != "ffplay"
        or "s16le" not in player
        or "48000" not in player
        or "-ch_layout" not in player
        or "stereo" not in player
        or "-ac" in player
    ):
        fail(f"ffplay command unexpected: {player}")

    cli.shutil.which = which_sox
    try:
        sox_player = cli.local_pcm_player_command()
    finally:
        cli.shutil.which = original_which
    if not sox_player or sox_player[0] != "sox" or "-d" not in sox_player:
        fail(f"sox command unexpected: {sox_player}")

    cli.shutil.which = which_none
    try:
        missing = cli.local_pcm_player_command()
    finally:
        cli.shutil.which = original_which
    if missing is not None:
        fail(f"expected no player, got {missing}")

    import contextlib
    import io

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            cli.build_parser().parse_args(
                ["play", "--target", "aws", "--audio", "--no-audio", "--dry-run"]
            )
        except SystemExit:
            pass
        else:
            fail("--audio and --no-audio should conflict")
    if "not allowed with argument" not in err.getvalue():
        fail(f"expected an argparse conflict, got {err.getvalue()!r}")

    off = cli.build_parser().parse_args(["play", "--no-audio", "--dry-run"])
    on = cli.build_parser().parse_args(["play", "--audio", "--dry-run"])
    auto = cli.build_parser().parse_args(["play", "--dry-run"])
    if (off.audio, on.audio, auto.audio) != ("off", "on", "auto"):
        fail(f"audio flags parsed wrong: {off.audio} {on.audio} {auto.audio}")
    print("PASS: audio player and flags")


def test_audio_scripts_and_ansible() -> None:
    import subprocess

    role = ROOT / "ansible" / "roles" / "stella"
    scripts = [
        role / "files" / "stella-flatpak",
        role / "files" / "stella-audio-setup",
        role / "files" / "stella-audio-capture",
        role / "files" / "stella-vnc-session.sh",
    ]
    for path in scripts:
        completed = subprocess.run(
            ["bash", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            fail(f"bash -n {path.name} failed: {completed.stderr}")

    setup = (role / "files" / "stella-audio-setup").read_text(encoding="utf-8")
    capture = (role / "files" / "stella-audio-capture").read_text(encoding="utf-8")
    session = (role / "files" / "stella-vnc-session.sh").read_text(encoding="utf-8")
    unit = (role / "files" / "stella-audio.service").read_text(encoding="utf-8")
    tasks = (role / "tasks" / "main.yml").read_text(encoding="utf-8")
    for token in (
        "sink_name=stella",
        "set-default-sink stella",
        "grep -qxF stella",
        "grep -qxF stella.monitor",
        "pipewire-pulse.service",
        "pactl info",
    ):
        if token not in setup:
            fail(f"stella-audio-setup missing {token!r}")
    for token in (
        "--device=stella.monitor",
        "--format=s16le",
        "--rate=48000",
        "--channels=2",
        "stella-audio-setup",
    ):
        if token not in capture:
            fail(f"stella-audio-capture missing {token!r}")
    if "stella-audio-setup" not in session or "XDG_RUNTIME_DIR" not in session:
        fail("VNC session does not start the audio sink")
    if "ExecStart=/usr/local/bin/stella-audio-setup" not in unit:
        fail("user service does not run stella-audio-setup")

    for package in (
        "- pipewire\n",
        "- pipewire-pulseaudio\n",
        "- pipewire-utils\n",
        "- wireplumber\n",
        "- pulseaudio-utils\n",
    ):
        if package not in tasks:
            fail(f"ansible audio packages missing {package!r}")
    if "\n      - pulseaudio\n" in tasks:
        fail("ansible must not install the pulseaudio daemon")
    for token in (
        "loginctl enable-linger",
        "stella-audio.service",
        "pipewire-pulse.service",
        "wireplumber.service",
        "stella-audio-setup",
        "stella-audio-capture",
        "Do not install the pulseaudio daemon",
    ):
        if token not in tasks:
            fail(f"ansible tasks missing {token!r}")
    print("PASS: audio scripts and ansible")


def main() -> int:
    import tempfile

    apply = load_apply()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        keymap_home = root / "keymap"
        keymap_home.mkdir()
        test_keymap_apply(apply, keymap_home)
        test_wrapper_audio_decision(root / "wrapper")
    test_launch_command()
    test_audio_player_and_flags()
    test_audio_scripts_and_ansible()
    print("PASS: flatpak stella checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
