# atari-keyboard

Keyboard-controlled Atari 2600 play via [Stella](https://stella-emu.github.io/), with a Python kickoff CLI, Ansible for host config, and Terraform for an optional AWS EC2 host.

## What’s working today

- **Local (macOS):** Stella app + PATH symlink, WASD/arrows/fire keymap, Pac-Man ROM (gitignored), smoke test, `play` / `configure` / `apply` CLI.
- **AWS (us-east-2):** EC2 `t3.small`, 8 GB gp3 root, SSH locked to your IP, Ansible inventory from Terraform outputs, Flatpak Stella (`io.github.stella_emu.Stella`) with the same WASD/arrows/fire map as local.
- **AWS VNC:** TigerVNC on display `:1` (TCP **5901**), minimal metacity + xterm session; password only in `~/.config/atari-kickoff/vnc-password.txt` (mode 600, never committed).
- **Remote play:** `play --target aws` syncs a ROM over SCP to `~/roms/` on EC2 and launches Flatpak Stella on `DISPLAY=:1` with software video and audio disabled so the window stays up under TigerVNC (non-blocking by default).

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

Or launch manually inside the VNC xterm (same flags `play --target aws` uses):

```bash
stella-flatpak ~/roms/"Pac-Man (NA).a26"
```

`stella-flatpak` is installed by `configure --target aws`. It runs Flatpak Stella with software video and the dummy SDL audio driver. Under TigerVNC the default OpenGL path and SDL audio device abort Stella (`std::out_of_range` after SDL audio warnings). The wrapper injects `SDL_AUDIODRIVER`, `SDL_VIDEODRIVER`, and `LIBGL_ALWAYS_SOFTWARE` with `flatpak run --env` so the sandbox receives them.

Equivalent command:

```bash
DISPLAY=:1 XAUTHORITY=$HOME/.Xauthority \
SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 \
flatpak run \
  --env=SDL_AUDIODRIVER=dummy \
  --env=SDL_VIDEODRIVER=x11 \
  --env=LIBGL_ALWAYS_SOFTWARE=1 \
  io.github.stella_emu.Stella \
  -video software -audio.enabled 0 \
  ~/roms/"Pac-Man (NA).a26"
```

### Flatpak keymap (WASD / arrows / fire)

`configure --target aws` loads `config/stella_keymap_joy.json` into Flatpak Stella’s settings database:

`~/.var/app/io.github.stella_emu.Stella/config/stella/stella.sqlite3`

Stella 7 reads `$XDG_CONFIG_HOME/stella/stella.sqlite3`. Inside this Flatpak, `XDG_CONFIG_HOME` is `~/.var/app/io.github.stella_emu.Stella/config`, so the database is the path above. The copies under `~/.config/atari-kickoff/` are the snapshot the apply script reads. Stella loads `keymap_joy` when `event_ver` is `6` (Stella 7’s event-list version). The apply step sets that when the database is new or still on Stella’s default `1`, and leaves any other saved version as it is.

Quit Stella before re-applying (a running process writes the database on exit), then relaunch.

Re-apply on the instance without a full playbook:

```bash
python3 ~/.config/atari-kickoff/apply_stella_keymap.py --target flatpak
```

Check the rows, then confirm in the VNC window that WASD and the arrow keys move and space or left ctrl fires:

```bash
python3 - <<'PY'
import json, sqlite3
from pathlib import Path
db = Path.home() / ".var/app/io.github.stella_emu.Stella/config/stella/stella.sqlite3"
rows = dict(sqlite3.connect(db).execute(
    "SELECT setting, value FROM settings WHERE setting IN ('keymap_joy','event_ver')"
))
keys = {item["key"] for item in json.loads(rows["keymap_joy"])}
print("event_ver", rows.get("event_ver"))
for key in ("w", "a", "s", "d", "up", "down", "left", "right", "space"):
    print(key, "yes" if key in keys else "no")
PY
```

5. Quick port check from the Mac:

```bash
nc -vz "$(cd terraform && terraform output -raw public_ip)" 5901
```


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

1. Harden SSH further if the host stays up long-term (optional: prefer SSH tunnel + `localhost` VNC).
