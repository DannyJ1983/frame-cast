#!/usr/bin/env bash
# One-line setup for a freshly flashed Raspberry Pi OS:
#
#   curl -fsSL https://raw.githubusercontent.com/DannyJ1983/frame-cast/main/setup.sh | sudo bash
#
# Downloads Frame Cast to /opt/frame-cast-src (or updates it if it's already there), then runs
# install.sh, which sets up the service. Running it again later updates Frame Cast.
set -euo pipefail

REPO=https://github.com/DannyJ1983/frame-cast
SRC=/opt/frame-cast-src

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo, for example: curl -fsSL $REPO/raw/main/setup.sh | sudo bash" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "==> Installing git"
  apt-get update
  apt-get install -y git
fi

if [ -d "$SRC/.git" ]; then
  echo "==> Updating Frame Cast in $SRC"
  git -C "$SRC" pull --ff-only
else
  echo "==> Downloading Frame Cast to $SRC"
  git clone --depth 1 "$REPO" "$SRC"
fi

exec "$SRC/install.sh"
