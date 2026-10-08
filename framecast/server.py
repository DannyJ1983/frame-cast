"""The hub's web server: the phone page, the share endpoint, the TV's event stream and the relay."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .hub import CONTROL_ACTIONS, Event, Hub, PlayCommand, sse
from .links import extract_url
from .relay import Relay
from .resolver import Resolver, ResolveError, Stream
from .tvlaunch import TvLauncher

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
ACK_TIMEOUT = 6.0  # How long a connected TV app has to confirm it got a link.
LAUNCH_WAIT = 25.0  # How long to wait for the app to start after asking the TV to open it.
PING_SECONDS = 15.0
# A well-known public HLS test stream (Big Buck Bunny, H.264), for checking the TV side alone.
TEST_STREAM_URL = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"


def make_command(stream: Stream, settings: Settings, relay: Relay) -> PlayCommand:
    """Build the TV's play command, relaying the stream if it needs headers the TV can't send."""
    use_relay = settings.relay == "always" or (settings.relay == "auto" and stream.needs_relay)
    if stream.needs_relay and settings.relay == "never":
        log.warning("Stream needs extra headers but relaying is off; it may not play")
    if use_relay:
        session_id = relay.open_session(stream.headers, stream.cookies)
        url = relay.path_for(session_id, stream.url)
        user_agent = None
    else:
        url = stream.url
        user_agent = stream.user_agent
    return PlayCommand(
        url=url,
        title=stream.title,
        kind=stream.kind,
        page_url=stream.page_url,
        is_live=stream.is_live,
        user_agent=user_agent,
        relayed=use_relay,
    )


async def read_shared_text(request: Request) -> str:
    """Get the shared link from JSON ({"url": ...} or {"text": ...}), a form, a plain body or ?url=."""
    content_type = request.headers.get("content-type", "")
    body = (await request.body()).decode("utf-8", errors="replace")
    if "json" in content_type or body.lstrip().startswith(("{", '"')):
        with contextlib.suppress(ValueError):
            data = json.loads(body)
            if isinstance(data, dict):
                return str(data.get("url") or data.get("text") or "")
            if isinstance(data, str):
                return data
    if "x-www-form-urlencoded" in content_type:
        form = parse_qs(body)
        return (form.get("url") or form.get("text") or [""])[0]
    if body.strip():
        return body
    return request.query_params.get("url") or request.query_params.get("text") or ""


def reply(request: Request, status: int, message: str, **extra: Any) -> Response:
    """Answer in JSON, or plain text if asked (?reply=text or Accept: text/plain)."""
    accept = request.headers.get("accept", "")
    if request.query_params.get("reply") == "text" or ("text/plain" in accept and "json" not in accept):
        return PlainTextResponse(message, status_code=status)
    return JSONResponse({"ok": status < 400, "message": message, **extra}, status_code=status)


async def event_stream(
    queue: asyncio.Queue[Event], unsubscribe: Callable[[asyncio.Queue[Event]], None]
) -> AsyncIterator[str]:
    """Yield queued events as Server-Sent Events, with a ping to keep connections alive."""
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            yield sse(event, data)
    finally:
        unsubscribe(queue)


def sse_response(stream: AsyncIterator[str]) -> StreamingResponse:
    """Wrap an event stream so proxies and browsers don't buffer it."""
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


def create_app(
    settings: Settings,
    resolver: Resolver | None = None,
    relay: Relay | None = None,
    launcher: TvLauncher | None = None,
    hub: Hub | None = None,
) -> FastAPI:
    """Build the FastAPI app. Collaborators can be swapped for tests."""
    resolver = resolver or Resolver()
    relay = relay or Relay()
    hub = hub or Hub()
    if launcher is None and settings.tv_host:
        launcher = TvLauncher(settings.tv_host, settings.tv_app_id, settings.token_file)
    tasks: set[asyncio.Task[None]] = set()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.loop = asyncio.get_running_loop()
        yield
        for task in tasks:
            task.cancel()
        await relay.aclose()

    app = FastAPI(title="Frame Cast", lifespan=lifespan)
    app.state.hub = hub
    app.state.relay = relay
    app.state.settings = settings
    app.state.tasks = tasks
    # The TV app runs from a local file, so its requests come from another origin.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    async def open_app_on_tv(command: PlayCommand) -> None:
        assert launcher is not None
        if await launcher.device_info() is None:
            hub.note("The TV didn't answer. Is it switched on? Open Frame Cast with the remote and the video will start.", "error")
            return
        for name, attempt in launcher.attempts():
            if hub.pending is None or hub.pending.id != command.id:
                return  # Played already, or replaced by a newer link.
            hub.note("Opening Frame Cast on the TV…")
            log.info("Trying %s launch", name)
            if await attempt() and await hub.wait_for_ack(command.id, LAUNCH_WAIT):
                hub.note(f"Sent to the TV: {command.title}")
                return
        if hub.pending is not None and hub.pending.id == command.id:
            hub.note("Couldn't open Frame Cast on the TV. Open it with the remote and the video will start.", "error")

    async def dispatch(command: PlayCommand) -> str:
        sent = hub.play(command)
        if sent and await hub.wait_for_ack(command.id, ACK_TIMEOUT):
            message = f"Sent to the TV: {command.title}"
            hub.note(message)
            return message
        if launcher is not None:
            task = asyncio.create_task(open_app_on_tv(command))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return f"Found “{command.title}”. Opening Frame Cast on the TV…"
        if sent:
            message = f"Sent “{command.title}”, but the TV hasn't confirmed it yet."
        else:
            message = f"Found “{command.title}”. Open Frame Cast on the TV and it'll start."
        hub.note(message)
        return message

    @app.post("/api/send")
    async def send(request: Request) -> Response:
        url = extract_url(await read_shared_text(request))
        if not url:
            return reply(request, 400, "That doesn't look like a web address.")
        hub.note(f"Looking for the video on {urlsplit(url).hostname}…")
        try:
            stream = await asyncio.wait_for(asyncio.to_thread(resolver.resolve, url), settings.resolve_timeout)
        except ResolveError as err:
            hub.note(str(err), "error")
            return reply(request, 422, str(err))
        except asyncio.TimeoutError:
            message = "Took too long to find the video on that page."
            hub.note(message, "error")
            return reply(request, 504, message)
        command = make_command(stream, settings, relay)
        message = await dispatch(command)
        return reply(request, 200, message, title=command.title)

    @app.post("/api/test")
    async def send_test(request: Request) -> Response:
        command = PlayCommand(
            url=TEST_STREAM_URL,
            title="Test video (Big Buck Bunny)",
            kind="hls",
            page_url=TEST_STREAM_URL,
        )
        message = await dispatch(command)
        return reply(request, 200, message, title=command.title)

    @app.post("/api/control")
    async def control(request: Request) -> Response:
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            data = {}
        action = str(data.get("action", ""))
        if action not in CONTROL_ACTIONS:
            return reply(request, 400, "Unknown control.")
        seconds = data.get("seconds")
        sent = hub.control(action, float(seconds) if seconds is not None else None)
        if not sent:
            return reply(request, 409, "The TV app isn't open.")
        return reply(request, 200, "OK")

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return hub.state()

    @app.get("/api/events")
    async def phone_events() -> StreamingResponse:
        return sse_response(event_stream(hub.subscribe_phone(), hub.unsubscribe_phone))

    @app.get("/api/tv/events")
    async def tv_events() -> StreamingResponse:
        return sse_response(event_stream(hub.subscribe_tv(), hub.unsubscribe_tv))

    @app.post("/api/tv/status")
    async def tv_status(request: Request) -> Response:
        # Sent as text/plain by the TV app to avoid a CORS preflight; the body is JSON.
        try:
            data = json.loads(await request.body())
        except ValueError:
            return reply(request, 400, "Expected JSON.")
        if not isinstance(data, dict):
            return reply(request, 400, "Expected a JSON object.")
        hub.report_status(data)
        return Response(status_code=204)

    @app.api_route("/p/{rest:path}", methods=["GET", "HEAD"])
    async def relay_stream(request: Request) -> Response:
        raw_path = request.scope.get("raw_path", b"").decode("latin-1") or request.url.path
        query = request.scope.get("query_string", b"").decode("latin-1")
        return await relay.serve(raw_path, query, request.method, request.headers.get("range"))

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "tv_connected": hub.tv_count > 0}

    @app.get("/")
    async def phone_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if settings.tv_dir is not None:
        app.mount("/tv", StaticFiles(directory=settings.tv_dir, html=True), name="tv")
    return app
