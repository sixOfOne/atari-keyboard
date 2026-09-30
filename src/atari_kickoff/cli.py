"""Placeholder CLI for the local-first Atari kickoff."""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keyboard-controlled Atari kickoff")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("up", help="placeholder: start the local smoke path")
    subparsers.add_parser("apply", help="placeholder: apply Terraform later")
    subparsers.add_parser("configure", help="placeholder: configure with Ansible later")
    play = subparsers.add_parser("play", help="print the Stella command that would run")
    play.add_argument("rom", nargs="?", default="roms/<game>.bin")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "up":
        print("UP placeholder: would start the local Stella smoke path.")
    elif args.command == "apply":
        print("APPLY placeholder: would run Terraform after AWS resources are defined.")
    elif args.command == "configure":
        print("CONFIGURE placeholder: would run Ansible against the local host.")
    elif args.command == "play":
        print(f"PLAY placeholder: would run stella {args.rom}")
        print("Keymap: see config/keymap.yaml; verify Stella bindings for this host/game.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
