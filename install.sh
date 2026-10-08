#!/usr/bin/env bash
# Install the Frame Cast home server as a service on a Raspberry Pi
# (or any Debian-based Linux with systemd). Run from the repo: sudo ./install.sh
#
# What it does, and nothing else:
#   - installs python3-venv with apt if it's missing
#   - creates a "framecast" system user to run the service
#   - copies the app to /opt/frame-cast and makes a virtual environment there
#   - writes /etc/frame-cast.env (only if it doesn't exist) for your settings
#   - installs and starts the frame-cast systemd service on port 8090
#   - adds a "frame-cast" command (/usr/local/bin/frame-cast) for pairing and checking pages
# Running it again updates the app and keeps your settings.
set -euo pipefail

APP_DIR=/opt/frame-cast
STATE_DIR=/var/lib/frame-cast
ENV_FILE=/etc/frame-cast.env
SERVICE=frame-cast
SERVICE_USER=framecast
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo ./install.sh" >&2
  exit 1
fi

say() { printf '\n==> %s\n' "$*"; }

if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  say "Installing python3-venv with apt"
  apt-get update
  apt-get install -y python3-venv
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  say "Creating system user $SERVICE_USER"
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

say "Copying the app to $APP_DIR"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/framecast" "$APP_DIR/tv"
cp -R "$SRC/framecast" "$SRC/tv" "$SRC/requirements.txt" "$APP_DIR/"
rm -rf "$APP_DIR/tv/build"

say "Setting up the virtual environment in $APP_DIR/.venv (this takes a few minutes on a Pi)"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

say "Preparing $STATE_DIR for the TV pairing token"
mkdir -p "$STATE_DIR"
chown "$SERVICE_USER": "$STATE_DIR"
chmod 700 "$STATE_DIR"

if [ ! -f "$ENV_FILE" ]; then
  say "Writing settings to $ENV_FILE"
  cat > "$ENV_FILE" <<EOF
# Frame Cast settings. Restart after changing: sudo systemctl restart $SERVICE
FRAMECAST_PORT=8090
FRAMECAST_STATE_DIR=$STATE_DIR
# The TV's IP address, so sharing a link opens Frame Cast on the TV by itself.
# Then restart and pair once with: frame-cast tv-pair
#FRAMECAST_TV_HOST=192.168.1.50
# When to pass streams through this computer: auto, always or never.
#FRAMECAST_RELAY=auto
EOF
else
  say "Keeping your settings in $ENV_FILE"
fi

say "Adding the frame-cast command"
cat > /usr/local/bin/frame-cast <<WRAPPER
#!/bin/sh
# Run Frame Cast commands with the service's settings, e.g. "frame-cast resolve <page>".
cd $APP_DIR || exit 1
exec sudo -u $SERVICE_USER $APP_DIR/.venv/bin/python -m framecast --config $ENV_FILE "\$@"
WRAPPER
chmod 755 /usr/local/bin/frame-cast

say "Installing the $SERVICE service"
cp "$SRC/frame-cast.service" "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

sleep 2
if systemctl is-active --quiet "$SERVICE"; then
  PORT="$(grep -E '^FRAMECAST_PORT=' "$ENV_FILE" | cut -d= -f2 || true)"
  ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
  say "Frame Cast is running."
  echo "    Phone page:         http://${ADDRESS:-this-computer}:${PORT:-8090}"
  echo "    For the TV app:     tv/build.sh --hub http://${ADDRESS:-this-computer}:${PORT:-8090}"
  echo "    Logs:               journalctl -u $SERVICE -f"
  echo "    Check a page:       frame-cast resolve https://..."
else
  say "The service didn't start. See: journalctl -u $SERVICE -n 50"
  exit 1
fi
