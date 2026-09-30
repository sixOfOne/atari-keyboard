"""CLI for the local-first Atari kickoff."""
from __future__ import annotations

import argparse
import json
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional until deps installed
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAMES = REPO_ROOT / "config" / "games.yaml"

# AWS / remote play defaults
SSH_USER = "ec2-user"
SSH_KEY_DEFAULT = Path.home() / ".ssh" / "neo-atari.pem"
REMOTE_ROM_DIR = "~/roms"  # expands on the remote host to /home/ec2-user/roms
FLATPAK_STELLA = "io.github.stella_emu.Stella"
VNC_DISPLAY = ":1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keyboard-controlled Atari kickoff")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("up", help="placeholder: start the local smoke path")
    apply = subparsers.add_parser(
        "apply", help="run Terraform (local-ready by default; AWS when enable_aws=true)"
    )
    apply.add_argument(
        "--dry-run",
        action="store_true",
        help="run terraform plan instead of apply",
    )
    apply.add_argument(
        "--init",
        action="store_true",
        help="run terraform init before plan/apply",
    )

    configure = subparsers.add_parser(
        "configure", help="run Ansible to configure Stella (local or aws inventory)"
    )
    configure.add_argument(
        "--target",
        choices=["local", "aws"],
        default="local",
        help="inventory target: local (default) or aws (from Terraform outputs)",
    )
    configure.add_argument(
        "--dry-run", action="store_true", help="print the Ansible command only"
    )

    play = subparsers.add_parser("play", help="launch Stella with a ROM")
    play.add_argument(
        "rom",
        nargs="?",
        help="ROM path (absolute, relative to repo, or a game name from config/games.yaml)",
    )
    play.add_argument(
        "--target",
        choices=["local", "aws"],
        default="local",
        help="where to launch: local Stella (default) or AWS EC2 + VNC",
    )
    play.add_argument(
        "--foreground",
        action="store_true",
        help="run Stella in the foreground (local: blocks until quit; aws: keep SSH session open)",
    )
    play.add_argument(
        "--dry-run",
        action="store_true",
        help="print the launch (and sync) command(s) without running them",
    )
    play.add_argument(
        "--ssh-key",
        default=str(SSH_KEY_DEFAULT),
        help=f"SSH private key for AWS target (default: {SSH_KEY_DEFAULT})",
    )
    return parser


def load_games_config() -> list:
    if not DEFAULT_GAMES.is_file():
        return []
    text = DEFAULT_GAMES.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
        return list(data.get("games") or [])
    games = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current:
                games.append(current)
            current = {"name": stripped.split(":", 1)[1].strip().strip("\"'" )}
        elif stripped.startswith("rom:") and current is not None:
            current["rom"] = stripped.split(":", 1)[1].strip().strip("\"'" )
    if current:
        games.append(current)
    return games


def resolve_rom(rom_arg):
    games = load_games_config()
    if rom_arg is None:
        if not games:
            raise SystemExit(
                "No ROM given and config/games.yaml has no games. "
                "Pass a ROM path or add an entry under games:."
            )
        rom_arg = str(games[0].get("rom") or "")
        if not rom_arg:
            raise SystemExit("First games.yaml entry is missing a rom: path.")
    else:
        for game in games:
            name = str(game.get("name") or "").lower()
            if name and name == rom_arg.lower():
                rom_arg = str(game.get("rom") or "")
                break

    path = Path(rom_arg).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        raise SystemExit(f"ROM not found: {path}")
    if path.stat().st_size <= 0:
        raise SystemExit(f"ROM is empty: {path}")
    return path


def find_stella_binary():
    which = shutil.which("stella")
    if which:
        return Path(which).resolve()
    mac_app = Path("/Applications/Stella.app/Contents/MacOS/stella")
    if mac_app.is_file():
        return mac_app
    return None


def launch_command(rom, *, foreground: bool):
    if platform.system() == "Darwin" and not foreground:
        app = Path("/Applications/Stella.app")
        if app.exists():
            return ["open", "-a", "Stella", "--args", str(rom)]
    stella = find_stella_binary()
    if not stella:
        raise SystemExit(
            "Stella not found on PATH and /Applications/Stella.app is missing."
        )
    return [str(stella), str(rom)]


def _fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def resolve_aws_ssh_host() -> str:
    """Return the EC2 public IP from Terraform outputs, or exit with a clear error."""
    tf_dir = REPO_ROOT / "terraform"
    if not (tf_dir / "main.tf").is_file():
        raise SystemExit(f"Terraform files missing under {tf_dir}")
    terraform = shutil.which("terraform")
    if not terraform:
        raise SystemExit(
            "terraform not found on PATH. Install Terraform "
            "(e.g. brew install hashicorp/tap/terraform) to resolve the AWS host."
        )
    try:
        raw = subprocess.check_output(
            [terraform, "output", "-json"],
            cwd=str(tf_dir),
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip() or str(exc)
        raise SystemExit(
            "Failed to read Terraform outputs. Run "
            "`PYTHONPATH=src python3 -m atari_kickoff apply` with enable_aws=true first.\n"
            f"Detail: {err}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Terraform output -json was not valid JSON: {exc}") from exc

    mode = (data.get("mode") or {}).get("value")
    ip = (data.get("public_ip") or {}).get("value") or (
        data.get("ssh_host") or {}
    ).get("value")
    if mode != "aws" or not ip:
        raise SystemExit(
            "AWS host unavailable: Terraform mode is not 'aws' or public_ip/ssh_host "
            "is empty. Set enable_aws=true in terraform/terraform.tfvars and run "
            "`PYTHONPATH=src python3 -m atari_kickoff apply`."
        )
    return str(ip)


def ssh_base_args(host: str, key: Path) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        f"{SSH_USER}@{host}",
    ]


def scp_base_args(key: Path) -> list[str]:
    return [
        "scp",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
    ]


def remote_rom_path(rom: Path) -> str:
    """Absolute remote path under ~/roms (quoted-safe basename preserved)."""
    # Keep the original filename so Stella / VNC users recognize it.
    return f"/home/{SSH_USER}/roms/{rom.name}"


def build_remote_mkdir_cmd() -> str:
    return f"mkdir -p {REMOTE_ROM_DIR}"


def build_remote_stella_cmd(remote_rom: str, *, foreground: bool) -> str:
    """Shell snippet run on the EC2 host to launch Flatpak Stella on the VNC display."""
    # Quote the ROM path for remote sh; Flatpak needs the real file path.
    rom_q = shlex.quote(remote_rom)
    # Prefer XAUTHORITY so a non-VNC SSH session can talk to :1.
    env = (
        f"export DISPLAY={shlex.quote(VNC_DISPLAY)}; "
        f"export XAUTHORITY=$HOME/.Xauthority; "
        "export SDL_AUDIODRIVER=dummy; "
        "export SDL_VIDEODRIVER=x11; "
        "export LIBGL_ALWAYS_SOFTWARE=1; "
    )
    run = f"flatpak run {FLATPAK_STELLA} -video software -audio.enabled 0 {rom_q}"
    if foreground:
        return env + run
    # Detach so the local CLI returns immediately.
    return (
        env
        + f"nohup {run} >/tmp/atari-kickoff-stella.log 2>&1 </dev/null & "
        + "echo $!; sleep 0.3"
    )


def cmd_play_aws(
    rom_arg,
    *,
    dry_run: bool,
    foreground: bool,
    ssh_key: str,
) -> int:
    rom = resolve_rom(rom_arg)
    key = Path(ssh_key).expanduser()
    if not dry_run and not key.is_file():
        raise SystemExit(
            f"SSH key not found: {key}. Pass --ssh-key or place neo-atari.pem at "
            f"{SSH_KEY_DEFAULT}."
        )

    host = resolve_aws_ssh_host()
    remote_rom = remote_rom_path(rom)
    mkdir_remote = build_remote_mkdir_cmd()
    scp_cmd = scp_base_args(key) + [str(rom), f"{SSH_USER}@{host}:{remote_rom}"]
    launch_remote = build_remote_stella_cmd(remote_rom, foreground=foreground)
    ssh_mkdir = ssh_base_args(host, key) + [mkdir_remote]
    ssh_launch = ssh_base_args(host, key) + [launch_remote]

    print(f"Target: aws ({SSH_USER}@{host})")
    print(f"ROM (local): {rom}")
    print(f"ROM (remote): {remote_rom}")
    print(f"Keymap: {REPO_ROOT / 'config' / 'keymap.yaml'}")
    print(f"VNC display: {VNC_DISPLAY} (connect vnc://{host}:5901)")
    print("1) Ensure remote ROM dir:", _fmt_cmd(ssh_mkdir))
    print("2) Sync ROM:", _fmt_cmd(scp_cmd))
    print("3) Launch Stella:", _fmt_cmd(ssh_launch))

    if dry_run:
        print("Dry run only; no SSH/SCP performed.")
        return 0

    for label, cmd in (
        ("mkdir", ssh_mkdir),
        ("scp", scp_cmd),
    ):
        completed = subprocess.run(cmd, check=False)
        if completed.returncode != 0:
            print(f"FAIL: {label} exited {completed.returncode}", file=sys.stderr)
            return completed.returncode

    if foreground:
        print("Starting remote Stella in the foreground (quit Stella / Ctrl-C to return).")
        completed = subprocess.run(ssh_launch, check=False)
        return completed.returncode

    completed = subprocess.run(ssh_launch, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        print(
            f"FAIL: remote launch exited {completed.returncode}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}",
            file=sys.stderr,
        )
        return completed.returncode
    pid = (completed.stdout or "").strip().splitlines()
    pid_msg = pid[0] if pid else "(unknown)"
    print(f"Stella launched on AWS (remote pid ~{pid_msg}); log: /tmp/atari-kickoff-stella.log")
    print(f"View via VNC: vnc://{host}:5901")
    return 0


def cmd_play(
    rom_arg,
    *,
    foreground: bool,
    dry_run: bool,
    target: str = "local",
    ssh_key: str = str(SSH_KEY_DEFAULT),
) -> int:
    if target == "aws":
        return cmd_play_aws(
            rom_arg, dry_run=dry_run, foreground=foreground, ssh_key=ssh_key
        )

    rom = resolve_rom(rom_arg)
    cmd = launch_command(rom, foreground=foreground)
    print(f"ROM: {rom}")
    print(f"Keymap: {REPO_ROOT / 'config' / 'keymap.yaml'}")
    print("Launch:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry_run:
        print("Dry run only; Stella not started.")
        return 0
    if platform.system() == "Darwin" and not foreground and cmd[:3] == ["open", "-a", "Stella"]:
        subprocess.run(cmd, check=False)
        print("Stella launched via open (terminal stays free).")
        return 0
    print("Starting Stella in the foreground (quit the app to return to the shell).")
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def cmd_configure(*, target: str = "local", dry_run: bool = False) -> int:
    playbook = REPO_ROOT / "ansible" / "playbook.yml"
    if not playbook.is_file():
        raise SystemExit(f"Ansible playbook missing: {playbook}")
    ansible = shutil.which("ansible-playbook")
    if not ansible:
        raise SystemExit(
            "ansible-playbook not found on PATH. Install Ansible (e.g. brew install ansible)."
        )

    if target == "aws":
        render = REPO_ROOT / "scripts" / "render_aws_inventory.py"
        code = subprocess.run([sys.executable, str(render)], check=False).returncode
        if code != 0:
            return code
        inventory = REPO_ROOT / "ansible" / "inventory" / "aws.yml"
    else:
        inventory = REPO_ROOT / "ansible" / "inventory" / "localhost.yml"

    if not inventory.is_file():
        raise SystemExit(f"Inventory missing: {inventory}")

    cmd = [ansible, "-i", str(inventory), str(playbook)]
    print("Launch:", " ".join(cmd))
    if dry_run:
        print("Dry run only; Ansible not started.")
        return 0
    completed = subprocess.run(cmd, cwd=str(REPO_ROOT / "ansible"), check=False)
    return completed.returncode


def cmd_apply(*, dry_run: bool = False, do_init: bool = False) -> int:
    tf_dir = REPO_ROOT / "terraform"
    if not (tf_dir / "main.tf").is_file():
        raise SystemExit(f"Terraform files missing under {tf_dir}")
    terraform = shutil.which("terraform")
    if not terraform:
        raise SystemExit(
            "terraform not found on PATH. Install Terraform (e.g. brew install hashicorp/tap/terraform)."
        )

    def run(cmd: list[str]) -> int:
        print("Launch:", " ".join(cmd))
        return subprocess.run(cmd, cwd=str(tf_dir), check=False).returncode

    if do_init or not (tf_dir / ".terraform").exists():
        code = run([terraform, "init", "-input=false"])
        if code != 0:
            return code

    action = "plan" if dry_run else "apply"
    cmd = [terraform, action, "-input=false"]
    if action == "apply":
        cmd.append("-auto-approve")
    return run(cmd)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "up":
        print("UP placeholder: would start the local Stella smoke path.")
        return 0
    if args.command == "apply":
        return cmd_apply(dry_run=args.dry_run, do_init=args.init)
    if args.command == "configure":
        return cmd_configure(target=args.target, dry_run=args.dry_run)
    if args.command == "play":
        return cmd_play(
            args.rom,
            foreground=args.foreground,
            dry_run=args.dry_run,
            target=args.target,
            ssh_key=args.ssh_key,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
