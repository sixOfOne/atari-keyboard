# atari-keyboard

Keyboard-controlled Atari 2600 play via [Stella](https://stella-emu.github.io/), with a Python kickoff CLI, Ansible for host config, and Terraform for an optional AWS EC2 host.

## What’s working today

- **Local (macOS):** Stella app + PATH symlink, WASD/arrows/fire keymap, Pac-Man ROM (gitignored), smoke test, `play` / `configure` / `apply` CLI.
- **AWS (us-east-2):** EC2 `t3.small`, 8 GB gp3 root, SSH locked to your IP, Ansible inventory from Terraform outputs, Flatpak Stella (`io.github.stella_emu.Stella`).
- **AWS VNC:** TigerVNC on display `:1` (TCP **5901**), minimal metacity + xterm session; password only in `~/.config/atari-kickoff/vnc-password.txt` (mode 600, never committed).
- **Remote play:** `play --target aws` syncs a ROM over SCP to `~/roms/` on EC2 and launches Flatpak Stella on `DISPLAY=:1` (non-blocking by default).

## Layout

```
config/           keymap + Stella joy map snapshot + games.yaml
roms/             local ROMs only (gitignored; keep .gitkeep)
scripts/          smoke_test, apply_stella_keymap, render_aws_inventory
src/atari_kickoff CLI entrypoint
ansible/          localhost + aws inventories, stella role
terraform/        local marker by default; EC2 when enable_aws=true
```

## Local quick start

1. Install Stella (macOS app). Symlink if needed:
   `ln -sfn /Applications/Stella.app/Contents/MacOS/stella ~/.local/bin/stella`
2. Place a ROM under `roms/` and list it in `config/games.yaml`.
3. Apply keymap (quit Stella first):
   `python3 scripts/apply_stella_keymap.py`
4. Smoke check:
   `python3 scripts/smoke_test.py "roms/YourGame.a26"`
5. Play:
   `PYTHONPATH=src python3 -m atari_kickoff play`
   (uses `open -a Stella` on macOS so the terminal doesn’t block)

Optional local Ansible (symlink + keymap):

`PYTHONPATH=src python3 -m atari_kickoff configure --target local`

## AWS path

1. Copy `terraform/terraform.tfvars.example` → `terraform/terraform.tfvars` (gitignored).
2. Set `enable_aws`, `aws_region`, `key_name`, `ssh_ingress_cidr` (your `/32`), and `enable_vnc = true` for remote desktop.
3. Keep the private key at `~/.ssh/<name>.pem` mode `600` — never in the repo.
4. Credentials via `~/.aws/credentials` (AWS CLI optional).
5. Apply / configure / SSH:

```bash
PYTHONPATH=src python3 -m atari_kickoff apply --dry-run
PYTHONPATH=src python3 -m atari_kickoff apply
PYTHONPATH=src python3 -m atari_kickoff configure --target aws
ssh -i ~/.ssh/neo-atari.pem ec2-user@$(cd terraform && terraform output -raw public_ip)
```

On the instance, Stella runs as:

`flatpak run io.github.stella_emu.Stella`

### Remote desktop (VNC)

Terraform must have `enable_vnc = true` (opens **5900–5901/tcp** from `ssh_ingress_cidr`). Ansible (`configure --target aws`) installs TigerVNC + a minimal metacity/xterm session and enables `vncserver@:1`.

1. Password file on the Mac (create once; never commit):

```bash
mkdir -p ~/.config/atari-kickoff
# VNC passwords are effectively 8 characters
openssl rand -base64 6 | tr -d '/+=' | head -c 8 > ~/.config/atari-kickoff/vnc-password.txt
chmod 600 ~/.config/atari-kickoff/vnc-password.txt
```

2. Apply SG + configure host:

```bash
PYTHONPATH=src python3 -m atari_kickoff apply
PYTHONPATH=src python3 -m atari_kickoff configure --target aws
```

3. Connect from macOS:

- **Screen Sharing / Finder → Go → Connect to Server:** `vnc://<public_ip>:5901`
- Or any VNC client to `<public_ip>:5901`
- Public IP: `cd terraform && terraform output -raw public_ip`
- Password: contents of `~/.config/atari-kickoff/vnc-password.txt`

4. **Remote play from the Mac** (sync ROM + launch Stella on the VNC display):

```bash
# Dry-run: print scp + remote flatpak command (uses Terraform public_ip)
PYTHONPATH=src python3 -m atari_kickoff play --target aws --dry-run
PYTHONPATH=src python3 -m atari_kickoff play Pac-Man --target aws --dry-run

# Sync ROM to ~/roms/ on EC2 and launch Stella on DISPLAY=:1 (returns immediately)
PYTHONPATH=src python3 -m atari_kickoff play --target aws
PYTHONPATH=src python3 -m atari_kickoff play Pac-Man --target aws
```

SSH identity defaults to `~/.ssh/neo-atari.pem` (`--ssh-key` to override). Host comes from `terraform output` (`public_ip` / `ssh_host`), not a hardcoded IP. Use `--foreground` to keep the SSH session attached to Stella.

Or launch manually inside the VNC xterm:

```bash
flatpak run io.github.stella_emu.Stella ~/roms/"Pac-Man (NA).a26"
```

5. Quick port check from the Mac:

```bash
nc -vz "$(cd terraform && terraform output -raw public_ip)" 5901
```


Keymap intent + joy JSON land in `~/.config/atari-kickoff/` on the remote host.

## CLI cheat sheet

| Command | Purpose |
|--------|---------|
| `play [--target local|aws] [--dry-run] [rom|name]` | Launch Stella locally or sync+launch on AWS/VNC |
| `configure [--target local|aws]` | Ansible configure |
| `apply [--dry-run] [--init]` | Terraform plan/apply |
| `up` | Placeholder for a one-shot local bootstrap |

## Costs / teardown notes

- Default AWS shape: `t3.small` + 8 GB gp3 in your chosen region. Stop or destroy when idle.
- Tear down cloud resources: `cd terraform && terraform destroy` (or flip `enable_aws=false` and apply carefully).
- Local Stella/ROMs are unaffected by destroy.

## Next up

1. Apply Flatpak/Stella keymap inside the VNC session (joy map currently copied to `~/.config/atari-kickoff/` but not wired into Flatpak Stella settings).
2. Harden SSH further if the host stays up long-term (optional: prefer SSH tunnel + `localhost` VNC).
