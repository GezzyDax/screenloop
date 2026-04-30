# Quickstart

This guide gets Screenloop running on a Linux host with Docker and one TV on the same LAN.

## 1. Install

Stable build:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh'
```

Dev build:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --dev'
```

These commands work from `bash`, `fish`, and `zsh`. If installing to `/opt/screenloop` without root, the installer asks for sudo automatically. Explicit sudo form:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && sudo bash /tmp/screenloop-install.sh --dev'
```

If Docker or the Docker Compose plugin is missing, the installer asks before installing it.

## 2. Open The Panel

Open:

```text
http://<server-ip>:8099
```

Sign in with the bootstrap admin credentials from the installer.

## 3. Upload Media

Open `Media`, upload a short video, and wait until transcode jobs are ready.

## 4. Create Playlist

Open `Playlists`, create a playlist, and add the uploaded video.

## 5. Add TV

Open `TVs` and either:

- Use `Scan network` to discover DLNA MediaRenderer devices.
- Add the TV IP manually.

Assign the playlist and click `Skip / Play next`.

## 6. Update Later

Stable:

```bash
cd /opt/screenloop
./update.sh
```

Dev:

```bash
cd /opt/screenloop
./update.sh -dev
```

Fetch and run the latest updater in one command:

```bash
cd /opt/screenloop
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/update.sh -o /tmp/screenloop-update.sh && bash /tmp/screenloop-update.sh --dev'
```
