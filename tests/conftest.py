import socket
import threading
import time

import pytest
import uvicorn

from framecast.config import Settings
from framecast.resolver import ResolveError, Resolver, choose_stream
from framecast.server import create_app


def fake_extract(url: str):
    """Pretend yt-dlp: pages under /video/ have an HLS stream, /protected/ needs a Referer."""
    if "/novideo" in url:
        raise ResolveError("Couldn't find a video on that page.")
    headers = {"User-Agent": "TestUA"}
    if "/protected/" in url:
        headers["Referer"] = "https://site.example/"
    info = {
        "title": f"Video at {url.rsplit('/', 1)[-1]}",
        "formats": [
            {
                "url": "https://cdn.example/v/720.m3u8",
                "manifest_url": "https://cdn.example/v/master.m3u8",
                "protocol": "m3u8_native",
                "height": 720,
                "http_headers": headers,
            }
        ],
    }
    return info, None


@pytest.fixture
def fake_resolver():
    return Resolver(fake_extract)


@pytest.fixture
def settings(tmp_path):
    return Settings(state_dir=tmp_path)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, app):
        self.app = app
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server didn't start")
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture
def live_server(settings, fake_resolver):
    server = LiveServer(create_app(settings, resolver=fake_resolver))
    server.start()
    yield server
    server.stop()
