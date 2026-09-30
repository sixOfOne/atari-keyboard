# Atari Keyboard Smoke Path

A local-first kickoff for controlling an Atari emulator with a keyboard through [Stella](https://stella-emu.github.io/). The first milestone is a small, repeatable smoke path: install Stella locally, supply a ROM outside git, and verify the emulator's command-line entry point.

The project leaves room for a Python CLI kickoff, Ansible configuration, and Terraform for AWS later. The cloud and automation pieces are intentionally stubs until the local path is reliable.

## Quick start

1. Install Stella and make sure `stella` is on `PATH`.
2. Put legally obtained ROMs under `roms/` (ROMs are not tracked in git).
3. Run `python3 scripts/smoke_test.py [path/to/game.bin]`.
4. Inspect `config/keymap.yaml`; Stella's exact keyboard names/mapping may need adjustment for the selected game and host.

The `up`, `apply`, and `configure` CLI commands are placeholders. `play` only prints the Stella command it would run.
