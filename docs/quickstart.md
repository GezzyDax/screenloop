# Quickstart

This guide gets Screenloop running on a Linux host with Docker and one TV on the same LAN.

## 1. Install

Stable build:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh)
```

Dev build:

```bash
SCREENLOOP_INSTALL_BRANCH=dev SCREENLOOP_IMAGE=ghcr.io/gezzydax/screenloop:dev \
  bash <(curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh)
```

For `fish` shell:

```bash
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh | \
  SCREENLOOP_INSTALL_BRANCH=dev SCREENLOOP_IMAGE=ghcr.io/gezzydax/screenloop:dev bash
```

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
