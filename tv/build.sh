#!/usr/bin/env bash
# Build the Frame Cast TV app and, optionally, install it on the TV.
#
#   tv/build.sh --hub http://192.168.1.20:8090
#       makes tv/build/FrameCast.wgt with the home server's address built in
#
#   tv/build.sh --hub http://192.168.1.20:8090 --install 192.168.1.50
#       also connects to the TV (in Developer Mode) and installs it
#
# Needs Tizen Studio with the Samsung TV extensions, and a Samsung certificate profile made
# in its Certificate Manager (see the README). Set CERT_PROFILE to pick a profile by name;
# otherwise Tizen Studio's active profile is used.
#
# Not yet run against a real Tizen Studio install: if a step fails, the README has the
# same steps done by hand in the Tizen Studio app.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB=""
TV_IP=""

usage() {
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --hub) HUB="${2:-}"; shift 2 ;;
    --install) TV_IP="${2:-}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

if [ -n "$HUB" ] && ! printf '%s' "$HUB" | grep -Eq '^https?://[A-Za-z0-9.:-]+$'; then
  echo "--hub should look like http://192.168.1.20:8090 (no path or spaces)" >&2
  exit 1
fi

find_tool() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then command -v "$name"; return; fi
  for dir in "$HOME/tizen-studio/tools/ide/bin" "$HOME/tizen-studio/tools" \
             "/c/tizen-studio/tools/ide/bin" "/c/tizen-studio/tools"; do
    for candidate in "$dir/$name" "$dir/$name.bat" "$dir/$name.exe"; do
      if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
  done
  echo "Couldn't find '$name'. Install Tizen Studio, or add its tools folders to PATH." >&2
  exit 1
}

TIZEN="$(find_tool tizen)"
BUILD="$HERE/build"
STAGE="$BUILD/app"

echo "Staging the app in $STAGE"
rm -rf "$BUILD"
mkdir -p "$STAGE"
cp -R "$HERE/config.xml" "$HERE/index.html" "$HERE/icon.png" "$HERE/css" "$HERE/js" \
      "$HERE/.project" "$HERE/.tproject" "$STAGE/"
# The stand-in player is only for desktop browsers; it steps aside on the TV, but leave it out.
: > "$STAGE/js/fakeplayer.js"
if [ -n "$HUB" ]; then
  printf 'window.FRAMECAST_CONFIG = { hubUrl: "%s" };\n' "$HUB" > "$STAGE/js/config.js"
  echo "Home server address built in: $HUB"
else
  echo "No --hub given: you'll type the home server address on the TV the first time."
fi

echo "Building"
"$TIZEN" build-web -- "$STAGE"

echo "Packaging and signing"
if [ -n "${CERT_PROFILE:-}" ]; then
  "$TIZEN" package -t wgt -s "$CERT_PROFILE" -o "$BUILD" -- "$STAGE/.buildResult"
else
  "$TIZEN" package -t wgt -o "$BUILD" -- "$STAGE/.buildResult"
fi
WGT="$(ls -t "$BUILD"/*.wgt | head -n 1)"
if [ "$WGT" != "$BUILD/FrameCast.wgt" ]; then mv "$WGT" "$BUILD/FrameCast.wgt"; fi
echo "Built $BUILD/FrameCast.wgt"

if [ -n "$TV_IP" ]; then
  SDB="$(find_tool sdb)"
  echo "Connecting to the TV at $TV_IP"
  "$SDB" connect "$TV_IP"
  TV_NAME="$("$SDB" devices | awk -v ip="$TV_IP" 'index($1, ip) == 1 { print $3 }')"
  if [ -z "$TV_NAME" ]; then
    echo "The TV didn't show up in 'sdb devices'. Is Developer Mode on, with this computer's IP?" >&2
    exit 1
  fi
  echo "Installing on $TV_NAME"
  "$TIZEN" install -n FrameCast.wgt -t "$TV_NAME" -- "$BUILD"
  echo "Done. Frame Cast should now be in the TV's Apps."
fi
