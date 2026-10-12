#!/usr/bin/env bash
# Build the Frame Cast TV app and, optionally, install it on the TV.
#
#   tv/build.sh --hub http://192.168.1.20:8090
#       makes tv/build/FrameCast.wgt with the home server's address built in
#
#   tv/build.sh --hub http://192.168.1.20:8090 --install 192.168.1.50
#       also connects to the TV (in Developer Mode) and installs it
#
# Needs the Tizen SDK's command-line tools (the "Tizen SDK with CLI" installer, or the SDK the
# VS Code extension installs; Tizen Studio itself is retired) and a Samsung certificate profile
# made in the VS Code extension's Certificate Manager (see the README). Set CERT_PROFILE to pick
# a profile by name; otherwise the active profile is used. If the SDK isn't in a usual place,
# set TIZEN_SDK to its folder.
#
# Not yet run against a real SDK install or TV: if a step fails, send the error.
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
  for dir in "${TIZEN_SDK:-/nonexistent}/tools/ide/bin" "${TIZEN_SDK:-/nonexistent}/tools" \
             "$HOME/tizen-studio/tools/ide/bin" "$HOME/tizen-studio/tools" \
             "$HOME/tizen-sdk/tools/ide/bin" "$HOME/tizen-sdk/tools" \
             "/c/tizen-studio/tools/ide/bin" "/c/tizen-studio/tools"; do
    for candidate in "$dir/$name" "$dir/$name.bat" "$dir/$name.exe"; do
      if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
  done
  echo "Couldn't find '$name'. Install the Tizen SDK, or set TIZEN_SDK to the folder it went into." >&2
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
  echo "Allowing this certificate to install on $TV_NAME"
  # A Samsung certificate needs the TV's permission once; harmless to repeat.
  "$TIZEN" install-permit -t "$TV_NAME" || echo "(install-permit didn't work; trying the install anyway)"
  echo "Installing on $TV_NAME"
  "$TIZEN" install -n FrameCast.wgt -t "$TV_NAME" -- "$BUILD"
  echo "Done. Frame Cast should now be in the TV's Apps."
fi
