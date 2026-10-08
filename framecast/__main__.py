"""Command line: run the hub, or check a page or the TV connection by hand.

    python -m framecast                       run the hub (default port 8090)
    python -m framecast resolve <page>        show which stream would be sent
    python -m framecast tv-pair --tv-host IP  make the TV ask to allow Frame Cast
    python -m framecast tv-apps --tv-host IP  list the app IDs the TV reports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import RELAY_MODES, Settings
from .links import extract_url

log = logging.getLogger("framecast")


def _parser(defaults: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m framecast", description="Frame Cast home server")
    parser.add_argument("--host", default=defaults.host, help="address to listen on (default %(default)s)")
    parser.add_argument("--port", type=int, default=defaults.port, help="port to listen on (default %(default)s)")
    parser.add_argument("--relay", choices=RELAY_MODES, default=defaults.relay, help="when to relay streams through the hub (default %(default)s)")
    parser.add_argument("--tv-host", default=defaults.tv_host, help="the TV's IP address, to open the app when a link is shared")
    parser.add_argument("--tv-app-id", default=defaults.tv_app_id, help="the TV app's ID (default %(default)s)")
    parser.add_argument("--state-dir", default=str(defaults.state_dir), help="where to keep the TV token (default %(default)s)")
    parser.add_argument("--verbose", "-v", action="store_true", help="log more detail")
    sub = parser.add_subparsers(dest="command")
    resolve = sub.add_parser("resolve", help="show which stream would be sent for a page")
    resolve.add_argument("page", help="the page's address")
    sub.add_parser("tv-pair", help="connect to the TV so it asks to allow Frame Cast")
    sub.add_parser("tv-apps", help="list the app IDs the TV reports")
    return parser


def _settings_from(args: argparse.Namespace) -> Settings:
    from pathlib import Path

    return Settings(
        host=args.host,
        port=args.port,
        relay=args.relay,
        tv_host=args.tv_host,
        tv_app_id=args.tv_app_id,
        state_dir=Path(args.state_dir),
    )


def _serve(settings: Settings) -> int:
    import uvicorn

    from .server import create_app

    log.info("Frame Cast hub on http://%s:%d (relay: %s, TV: %s)", settings.host, settings.port, settings.relay, settings.tv_host or "open the app by hand")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")
    return 0


def _resolve(settings: Settings, page: str) -> int:
    from .resolver import Resolver, ResolveError

    url = extract_url(page)
    if not url:
        print("That doesn't look like a web address.", file=sys.stderr)
        return 2
    try:
        stream = Resolver().resolve(url)
    except ResolveError as err:
        print(err, file=sys.stderr)
        return 1
    relayed = settings.relay == "always" or (settings.relay == "auto" and stream.needs_relay)
    print(json.dumps(
        {
            "title": stream.title,
            "kind": stream.kind,
            "url": stream.url,
            "is_live": stream.is_live,
            "headers": stream.headers,
            "has_cookies": bool(stream.cookie_header()),
            "relayed": relayed,
        },
        indent=2,
    ))
    return 0


def _tv(settings: Settings, command: str) -> int:
    from .tvlaunch import TvLauncher

    if not settings.tv_host:
        print("Give the TV's address with --tv-host (or FRAMECAST_TV_HOST).", file=sys.stderr)
        return 2
    launcher = TvLauncher(settings.tv_host, settings.tv_app_id, settings.token_file)
    info = asyncio.run(launcher.device_info())
    if info is None:
        print(f"The TV at {settings.tv_host} didn't answer on port 8001. Is it on and on the same network?", file=sys.stderr)
        return 1
    device = info.get("device", {})
    print(f"Found {device.get('name', 'a TV')} ({device.get('modelName', 'unknown model')})")
    try:
        if command == "tv-pair":
            print("Look at the TV and choose Allow if it asks...")
            launcher.pair()
            print(f"Paired. Token saved to {settings.token_file}")
        else:
            apps = launcher.installed_apps()
            if not apps:
                print("The TV didn't list its apps (not every model does).")
            for app in apps:
                print(f"{app.get('appId')}\t{app.get('name')}")
    except Exception as err:  # samsungtvws and socket errors
        print(f"Couldn't talk to the TV: {err!r}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m framecast``."""
    args = _parser(Settings.from_env()).parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("yt_dlp").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = _settings_from(args)
    if args.command == "resolve":
        return _resolve(settings, args.page)
    if args.command in ("tv-pair", "tv-apps"):
        return _tv(settings, args.command)
    return _serve(settings)


if __name__ == "__main__":
    sys.exit(main())
