"""End to end in a real browser: phone shares a link, hub finds it, TV app plays it.

The TV app runs in headless Chromium with the stand-in player (tv/js/fakeplayer.js), so this
checks everything except Samsung's own player. Skipped if Playwright or Chromium is missing.
Set PLAYWRIGHT_CHROMIUM to a Chromium binary to use one Playwright didn't install.
"""

import os
import time
from pathlib import Path

import httpx
import pytest

playwright_api = pytest.importorskip("playwright.sync_api")


def _chromium_path():
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if configured:
        return configured
    bundled = Path("/opt/pw-browsers/chromium")
    return str(bundled) if bundled.exists() else None


@pytest.fixture
def tv_page(live_server):
    with playwright_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=_chromium_path())
        except Exception as err:  # no browser available on this machine
            pytest.skip(f"Chromium not available: {err}")
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{live_server.url}/tv/")
        page.wait_for_function("document.getElementById('hub-status').textContent.startsWith('Ready')")
        page.wait_for_function("document.body.classList.contains('mode-dashboard')")  # the app opens on it
        yield page, live_server
        browser.close()
        assert errors == [], errors


def to_grid(page):
    """From the dashboard, OK opens the channel grid."""
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-idle')")


def calls(page, name):
    return [c for c in page.evaluate("window.__avplayCalls") if c[0] == name]


def send(server, url):
    return httpx.post(f"{server.url}/api/send", json={"url": url}, timeout=15).json()


def test_shared_link_plays_on_tv(tv_page):
    page, server = tv_page
    reply = send(server, "https://site.example/video/42")
    assert reply["message"] == "Sent to the TV: Video at 42"

    page.wait_for_function("document.body.classList.contains('mode-playing')")
    # The master playlist comes via the hub (best quality first); the video stays direct.
    opened = calls(page, "open")[-1][1]
    assert opened.startswith(f"{server.url}/p/") and opened.endswith("/master.m3u8")
    all_calls = page.evaluate("window.__avplayCalls")
    assert ["setStreamingProperty", "USER_AGENT", "TestUA"] in all_calls
    assert ["setStreamingProperty", "ADAPTIVE_INFO", "STARTBITRATE=HIGHEST"] in all_calls
    assert calls(page, "play")
    assert page.text_content("#osd-title") == "Video at 42"

    hub = server.app.state.hub
    deadline = time.time() + 5
    while hub.tv_status["state"] != "playing" and time.time() < deadline:
        time.sleep(0.05)
    assert hub.tv_status["state"] == "playing"
    assert hub.tv_status["title"] == "Video at 42"


def test_relayed_stream_uses_hub_address(tv_page):
    page, server = tv_page
    send(server, "https://site.example/protected/7")
    page.wait_for_function("document.body.classList.contains('mode-playing')")
    opened = calls(page, "open")[-1][1]
    assert opened.startswith(f"{server.url}/p/")
    assert opened.endswith("/master.m3u8")


def test_phone_controls_reach_tv(tv_page):
    page, server = tv_page
    send(server, "https://site.example/video/1")
    page.wait_for_function("document.body.classList.contains('mode-playing')")

    def control(**body):
        return httpx.post(f"{server.url}/api/control", json=body, timeout=5)

    assert control(action="toggle").status_code == 200
    page.wait_for_function("window.FrameCast.player.state === 'paused'")
    assert calls(page, "pause")
    control(action="seek", seconds=30)
    page.wait_for_function("window.__avplayCalls.some(c => c[0] === 'jumpForward' && c[1] === 30000)")
    control(action="stop")
    page.wait_for_function("document.body.classList.contains('mode-idle')")


def test_remote_keys(tv_page):
    page, server = tv_page
    send(server, "https://site.example/video/2")
    page.wait_for_function("document.body.classList.contains('mode-playing')")
    page.keyboard.press("Enter")  # OK: pause
    page.wait_for_function("window.FrameCast.player.state === 'paused'")
    page.keyboard.press("ArrowLeft")  # back 10 s
    page.wait_for_function("window.__avplayCalls.some(c => c[0] === 'jumpBackward' && c[1] === 10000)")
    page.keyboard.press("Escape")  # Back: stop
    page.wait_for_function("document.body.classList.contains('mode-idle')")
    assert calls(page, "close")


def test_player_failure_shows_error_and_reaches_phone(tv_page):
    page, server = tv_page
    hub = server.app.state.hub
    from framecast.hub import PlayCommand

    # Sent straight through the hub so the address can trigger the stand-in player's failure.
    command = PlayCommand(url="https://cdn.example/fail-me.m3u8", title="Broken", kind="hls", page_url="x")
    server_loop_call(server, lambda: hub.play(command))
    page.wait_for_function("document.body.classList.contains('mode-error')")
    assert "Couldn't connect" in page.text_content("#error-message")
    deadline = time.time() + 5
    while hub.tv_status["state"] != "error" and time.time() < deadline:
        time.sleep(0.05)
    assert hub.tv_status["state"] == "error"
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-idle')")


def test_link_shared_while_tv_closed_plays_when_opened(live_server):
    reply = send(live_server, "https://site.example/video/5")
    assert "Open Frame Cast on the TV" in reply["message"]
    with playwright_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=_chromium_path())
        except Exception as err:
            pytest.skip(f"Chromium not available: {err}")
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"{live_server.url}/tv/")
        page.wait_for_function("document.body.classList.contains('mode-playing')")
        assert page.text_content("#osd-title") == "Video at 5"
        browser.close()


def test_settings_screen_saves_address(tv_page):
    page, server = tv_page
    to_grid(page)
    page.keyboard.press("ArrowRight")  # past the Dashboard tile to Server address
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-settings')")
    page.fill("#hub-input", server.url.replace("http://", ""))
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")  # Save
    page.wait_for_function("document.getElementById('hub-status').textContent.startsWith('Ready')")
    assert page.evaluate("localStorage.getItem('framecast.hubUrl')") == server.url


def test_phone_page_shows_tv_state(tv_page):
    page, server = tv_page
    phone = page.context.browser.new_page()
    phone.goto(server.url)
    phone.wait_for_function("document.getElementById('tv-pill').textContent === 'TV app open'")
    phone.fill("#url", "https://site.example/video/77")
    phone.click("#send-button")
    phone.wait_for_function("document.getElementById('message').textContent.includes('Sent to the TV')")
    phone.wait_for_function("document.getElementById('now-state').textContent.startsWith('Playing')")
    assert phone.text_content("#now-title") == "Video at 77"


def server_loop_call(server, fn):
    """Run fn on the server's event loop (hub methods expect to be called there)."""
    import asyncio

    loop = server.app.state.loop
    future = asyncio.run_coroutine_threadsafe(_call(fn), loop)
    return future.result(5)


async def _call(fn):
    return fn()


# Saved channels ---------------------------------------------------------------

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def add_channel(server, name, path):
    response = httpx.post(f"{server.url}/api/channels", json={"name": name, "url": f"https://site.example/video/{path}"}, timeout=5)
    assert response.status_code == 201
    return response.json()


def tile_names(page):
    return page.eval_on_selector_all("#grid .tile .tile-name", "els => els.map(e => e.textContent)")


def test_channels_show_on_tv_and_play_with_ok(tv_page):
    page, server = tv_page
    news = add_channel(server, "News 24", "news")
    add_channel(server, "Sport", "sport")
    httpx.put(f"{server.url}/api/channels/{news['id']}/logo", content=PNG, timeout=5)
    page.wait_for_function("document.querySelectorAll('#grid .tile').length === 4")
    assert tile_names(page) == ["News 24", "Sport", "Dashboard", "Server address"]
    page.wait_for_function("document.querySelector('#grid .tile img') !== null")
    assert "/logo?v=1" in page.get_attribute("#grid .tile img", "src")
    assert page.is_hidden("#grid-empty")

    to_grid(page)
    page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('#grid .tile.focused .tile-name').textContent === 'Sport'")
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-playing')")
    assert page.text_content("#osd-title") == "Sport"
    assert calls(page, "open")[-1][1].endswith("/master.m3u8")

    # CH+ goes on to the next channel, wrapping round to the first.
    page.keyboard.press("PageUp")
    page.wait_for_function("document.getElementById('osd-title').textContent === 'News 24'")
    page.wait_for_function("document.body.classList.contains('mode-playing')")

    # Back stops and returns to the grid, focused on the channel that was playing.
    page.keyboard.press("Escape")
    page.wait_for_function("document.body.classList.contains('mode-idle')")
    assert page.text_content("#grid .tile.focused .tile-name") == "News 24"


def test_channel_that_fails_to_resolve_shows_error(tv_page):
    page, server = tv_page
    httpx.post(f"{server.url}/api/channels", json={"name": "Gone", "url": "https://site.example/novideo"}, timeout=5)
    page.wait_for_function("document.querySelectorAll('#grid .tile').length === 3")
    to_grid(page)
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-error')")
    assert "Couldn't find a video" in page.text_content("#error-message")
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-idle')")


def test_grid_reaches_settings_tile(tv_page):
    page, server = tv_page
    add_channel(server, "One", "one")
    page.wait_for_function("document.querySelectorAll('#grid .tile').length === 3")
    to_grid(page)
    page.keyboard.press("ArrowRight")  # Dashboard
    page.keyboard.press("ArrowRight")  # Server address
    page.keyboard.press("Enter")
    page.wait_for_function("document.body.classList.contains('mode-settings')")


def test_phone_page_saves_channel_with_logo_and_tv_shows_it(tv_page, tmp_path):
    page, server = tv_page
    logo = tmp_path / "logo.png"
    logo.write_bytes(PNG)
    phone = page.context.browser.new_page()
    phone.goto(server.url)
    phone.click("#add-channel")
    phone.fill("#channel-name", "Golazo")
    phone.fill("#channel-url", "https://site.example/video/golazo")
    phone.set_input_files("#channel-logo", str(logo))
    phone.click("#channel-save")
    phone.wait_for_function("document.getElementById('message').textContent.startsWith('Saved Golazo')")
    phone.wait_for_function("document.querySelectorAll('#channels li').length === 1")
    page.wait_for_function("document.querySelectorAll('#grid .tile img').length === 1")
    assert tile_names(page)[0] == "Golazo"
    channel = httpx.get(f"{server.url}/api/channels", timeout=5).json()["channels"][0]
    assert channel["has_logo"] is True

    # Play it from the phone.
    phone.click("#channels li button:has-text('Play')")
    page.wait_for_function("document.getElementById('osd-title').textContent === 'Golazo'")


# Dashboard --------------------------------------------------------------------


def test_tv_opens_on_the_dashboard(tv_page):
    page, server = tv_page
    assert page.get_attribute("#dashboard-frame", "src") == f"{server.url}/dashboard/"
    frame = page.frame_locator("#dashboard-frame")
    frame.locator("#news .headline").first.wait_for()
    assert frame.locator("#news-source").text_content() == "BBC News"
    assert frame.locator("#setup").is_visible()  # no location yet
    frame.locator("#ticker-track .tick").first.wait_for()
    assert "Arsenal" in frame.locator("#ticker-track").text_content()

    # OK goes to the channels; Back comes home again.
    to_grid(page)
    assert page.get_attribute("#dashboard-frame", "src") == "about:blank"
    page.keyboard.press("Escape")
    page.wait_for_function("document.body.classList.contains('mode-dashboard')")
    frame.locator("#news .headline").first.wait_for()


def test_dashboard_tile_and_keys_pressed_inside_the_page(tv_page):
    page, server = tv_page
    to_grid(page)
    page.keyboard.press("Enter")  # no channels: the first tile is Dashboard
    page.wait_for_function("document.body.classList.contains('mode-dashboard')")
    # If the page itself has focus, it hands keys to the app.
    page.frame_locator("#dashboard-frame").locator("#time").press("ArrowDown")
    page.wait_for_function("document.body.classList.contains('mode-idle')")


def test_phone_shows_the_dashboard_over_a_video(tv_page):
    page, server = tv_page
    send(server, "https://site.example/video/9")
    page.wait_for_function("document.body.classList.contains('mode-playing')")
    reply = httpx.post(f"{server.url}/api/dashboard/show", timeout=5)
    assert reply.status_code == 200
    page.wait_for_function("document.body.classList.contains('mode-dashboard')")
    assert page.evaluate("window.FrameCast.player.state") == "stopped"


def test_dashboard_settings_from_the_phone(tv_page):
    page, server = tv_page
    phone = page.context.browser.new_page()
    phone.goto(server.url)
    phone.click("#dash-details summary")
    phone.wait_for_function("document.querySelectorAll('#dash-leagues input').length > 5")
    assert phone.is_checked("#dash-leagues input[value='eng.1']")
    phone.fill("#dash-place", "LS1 4AP")
    phone.fill("#dash-station", "LDS")
    phone.fill("#dash-rail-key", "secret-key")
    phone.check("#dash-leagues input[value='eng.2']")
    phone.click("#dash-save")
    phone.wait_for_function("document.getElementById('dash-message').textContent.startsWith('Saved')")
    assert phone.text_content("#dash-place-found") == "Found: Leeds"
    assert phone.input_value("#dash-rail-key") == ""
    assert "Saved" in phone.get_attribute("#dash-rail-key", "placeholder")
    settings = httpx.get(f"{server.url}/api/dashboard/settings", timeout=5).json()["settings"]
    assert settings["leagues"] == ["eng.1", "eng.2"] and settings["has_rail_key"]

    # The TV's dashboard picks the changes up on its next refresh.
    frame = page.frame_locator("#dashboard-frame")
    page.evaluate("document.getElementById('dashboard-frame').contentWindow.Dashboard.load()")
    frame.locator("#departures tr").first.wait_for()
    assert frame.locator("#trains-station").text_content() == "Leeds"
    assert frame.locator("#now-temp").text_content() == "14°"
    assert frame.locator("#setup").is_hidden()

    phone.click("#dash-show")
    phone.wait_for_function("document.getElementById('dash-message').textContent.includes('Showing')")


def test_bus_settings_from_the_phone_and_buses_on_the_tv(tv_page):
    page, server = tv_page
    phone = page.context.browser.new_page()
    phone.goto(server.url)
    phone.click("#dash-details summary")
    phone.wait_for_function("document.querySelectorAll('#dash-bus-region option').length > 5")
    phone.fill("#dash-place", "LS1 4AP")
    phone.fill("#dash-bus-stops", "149000006934")
    phone.fill("#dash-bus-key", "bus-key")
    phone.click("#dash-save")
    phone.wait_for_function("document.getElementById('dash-message').textContent.startsWith('Saved')")
    assert "Saved" in phone.get_attribute("#dash-bus-key", "placeholder")
    assert phone.is_visible("#dash-bus-forget")

    frame = page.frame_locator("#dashboard-frame")
    reload = "document.getElementById('dashboard-frame').contentWindow.Dashboard.load()"
    page.evaluate(reload)
    frame.locator("#buses-preparing").wait_for()  # the timetable is fetched the first time
    deadline = time.time() + 15
    while frame.locator("#bus-rows tr").count() == 0 and time.time() < deadline:
        time.sleep(0.3)
        page.evaluate(reload)
    assert frame.locator("#bus-rows tr").count() > 0
    assert frame.locator("#buses-stop").text_content() == "Churchill Square (Stop D)"
    assert frame.locator("#buses-preparing").is_hidden()
