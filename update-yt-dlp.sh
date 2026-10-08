#!/usr/bin/env bash
# Update yt-dlp, the part that finds videos on pages, and restart Frame Cast.
# Sites change often, so if pages that used to work stop working, run: sudo ./update-yt-dlp.sh
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo ./update-yt-dlp.sh" >&2
  exit 1
fi
/opt/frame-cast/.venv/bin/pip install --quiet --upgrade yt-dlp
/opt/frame-cast/.venv/bin/python -m yt_dlp --version | sed 's/^/yt-dlp is now version /'
systemctl restart frame-cast
echo "Frame Cast restarted."
