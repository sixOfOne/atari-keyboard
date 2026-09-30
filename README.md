# atari-keyboard

Keyboard-controlled Atari 2600 play via [Stella](https://stella-emu.github.io/), with a Python kickoff CLI, Ansible for host config, and Terraform for an optional AWS EC2 host.

## What’s working today

- **Local (macOS):** Stella app + PATH symlink, WASD/arrows/fire keymap, Pac-Man ROM (gitignored), smoke test, `play` / `configure` / `apply` CLI.
- **AWS (us-east-2):** EC2 `t3.small`, 8 GB gp3 root, SSH locked to your IP, Ansible inventory from Terraform outputs, Flatpak Stella (`io.github.stella_emu.Stella`) with the same WASD/arrows/fire map as local.
- **AWS VNC:** TigerVNC on display `:1` (TCP **5901**), minimal metacity + xterm session; password only in `~/.config/atari-kickoff/vnc-password.txt` (mode 600, never committed).
- **Remote play:** `play --target aws` syncs a ROM over SCP to `~/roms/` on EC2 and launches Flatpak Stella on `DISPLAY=:1` with software video. Audio uses a PipeWire pulse sink when that server is up, and stays silent (dummy SDL driver) when it is not, so a missing sound device cannot crash Stella. TigerVNC carries the picture only; the CLI plays the sink back on this machine over SSH.

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

SSH identity defaults to `~/.ssh/neo-atari.pem` (`--ssh-key` to override). Host comes from `terraform output` (`public_ip` / `ssh_host`), not a hardcoded IP. Use `--foreground` to keep the SSH session attached to Stella. `--no-audio` forces the silent driver. `--audio` asks for sound explicitly; the default is already on when the sink is up.

Re-run `configure --target aws` after pulling this audio change so the host gets PipeWire and the updated `stella-flatpak`.

Or launch manually inside the VNC xterm:

```bash
stella-flatpak ~/roms/"Pac-Man (NA).a26"
```

That starts the game window only. Hearing it still needs the capture pipeline below (or `play --target aws` from the Mac).

### Remote audio

TigerVNC carries the picture and the keyboard. It does not carry sound. `configure --target aws` installs PipeWire on Amazon Linux 2023 and starts it as a user service next to the VNC session:

- `pipewire`, `pipewire-pulseaudio`, `wireplumber`, `pipewire-utils`, `pulseaudio-utils`
- not the `pulseaudio` daemon package, which conflicts with `pipewire-pulseaudio`

`pipewire-pulse` listens on the user socket `$XDG_RUNTIME_DIR/pulse/native` (the socket Flatpak’s `--socket=pulseaudio` expects). EC2 has no sound card, so `stella-audio-setup` loads a null sink named `stella`, makes it the default, and the Mac records `stella.monitor`. The PulseAudio server stays on that unix socket. It is not published on the network.

`stella-flatpak` always keeps software video (`-video software`, `SDL_VIDEODRIVER=x11`, `LIBGL_ALWAYS_SOFTWARE=1`). The default OpenGL path still aborts Stella under TigerVNC. SDL audio used to abort as well (`std::out_of_range` after SDL audio warnings) when no device existed. The wrapper therefore enables `SDL_AUDIODRIVER=pulseaudio` and `-audio.enabled 1` only after both of these are true:

1. `stella-audio-setup` created the `stella` sink.
2. A Flatpak probe can see the PulseAudio socket inside the sandbox.

Otherwise it launches with `SDL_AUDIODRIVER=dummy` and `-audio.enabled 0`. `ATARI_AUDIO=auto` (what `play` exports by default) and `ATARI_AUDIO=on` (`--audio`) use that probe. `ATARI_AUDIO=off` (`--no-audio`) skips it. The chosen driver is written to `/tmp/atari-kickoff-audio-mode`.

`play --target aws` then SSHs `stella-audio-capture` (raw s16le, 48 kHz, stereo) into `ffplay`, `mpv`, or `sox` on the machine you ran `play` from. The player is detached; its log is `~/.cache/atari-kickoff/vnc-audio.log`. Screen Sharing’s volume control does not affect this stream.

#### Verify

On the instance, after `configure --target aws`:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
systemctl --user --no-pager --full status pipewire pipewire-pulse wireplumber stella-audio
test -S "$XDG_RUNTIME_DIR/pulse/native" && echo pulse-socket-ok
pactl info
pactl get-default-sink
pactl list short sources | grep stella.monitor
```

`pactl info` should name PipeWire, and the default sink should be `stella`. Two seconds of a 440 Hz tone:

```bash
python3 - <<'PY' | paplay --device=stella --format=s16le --rate=48000 --channels=1 --raw -
import math, struct, sys
rate = 48000
for i in range(rate * 2):
    sample = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
    sys.stdout.buffer.write(struct.pack("<h", sample))
PY
```

On the Mac, install a player once (`brew install ffmpeg`) and listen:

```bash
ssh -i ~/.ssh/neo-atari.pem ec2-user@<public_ip> /usr/local/bin/stella-audio-capture \
  | ffplay -nodisp -loglevel error -fflags nobuffer -flags low_delay \
      -probesize 32 -analyzeduration 0 -f s16le -ar 48000 -ac 2 -i pipe:0
```

You should hear the tone. Stop `ffplay`, then launch the game:

```bash
PYTHONPATH=src python3 -m atari_kickoff play Pac-Man --target aws
```

The VNC window is the picture. The local player is the sound. A dry run prints the same pipeline without connecting:

```bash
PYTHONPATH=src python3 -m atari_kickoff play Pac-Man --target aws --dry-run
```

#### Troubleshooting

- **The game is silent and `/tmp/atari-kickoff-audio-mode` says `dummy`.** Re-run `configure --target aws`. On the host, `pactl info` should succeed. Stella’s own log is `/tmp/atari-kickoff-stella.log`.
- **`std::out_of_range` or SDL audio warnings in that log.** The probe should have stayed on the dummy driver. Force it with `--no-audio` and keep playing. Software video stays on either way.
- **`pactl` looks fine but the Mac is quiet.** Screen Sharing will not play this audio. Install `ffmpeg`, `mpv`, or `sox` locally and re-run `play`. `~/.cache/atari-kickoff/vnc-audio.log` has the player and SSH errors.
- **`stella-audio` failed at configure time.** On the instance: `journalctl --user -u pipewire-pulse -u wireplumber -u stella-audio --no-pager -n 100`. Lingering is `/var/lib/systemd/linger/ec2-user`; the user bus is `/run/user/$(id -u)/bus`.
- **Flatpak cannot open the socket (SELinux).** `sudo ausearch -m avc -ts recent`. A failed sandbox probe leaves Stella silent instead of crashing.
- **Crackling or a short delay.** EC2 is a VM, so PipeWire already uses a larger quantum there. The SSH stream adds a bit more delay. That delay is separate from the VNC picture.

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
| `play [--target local or aws] [--audio or --no-audio] [--dry-run] [rom or name]` | Launch Stella locally, or sync and launch on AWS/VNC. AWS audio is on when the PipeWire sink is up |
| `configure [--target local|aws]` | Ansible configure |
| `apply [--dry-run] [--init]` | Terraform plan/apply |
| `up` | Placeholder for a one-shot local bootstrap |

## Costs / teardown notes

- Default AWS shape: `t3.small` + 8 GB gp3 in your chosen region. Stop or destroy when idle.
- Tear down cloud resources: `cd terraform && terraform destroy` (or flip `enable_aws=false` and apply carefully).
- Local Stella/ROMs are unaffected by destroy.

## Next up

1. Harden SSH further if the host stays up long-term (optional: prefer SSH tunnel + `localhost` VNC).
