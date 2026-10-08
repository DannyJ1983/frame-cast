# Frame Cast

Share a webpage from a phone; a home server (Pi) finds the video stream with yt-dlp; a Tizen web app on a 2019 Samsung Frame (Tizen 5.0) plays it with AVPlay. README.md has the full picture.

## Layout

- `framecast/`: the home server (Python 3.11, FastAPI, uvicorn, Server-Sent Events)
  - `resolver.py`: page to stream (pure `choose_stream` plus a yt-dlp wrapper)
  - `relay.py`: signed relay for streams that need headers or cookies
  - `hub.py`: in-memory state and event queues
  - `server.py`: routes
  - `tvlaunch.py`: opens the app over Samsung's local API
- `tv/`: the Tizen web app. `core.js` is pure and tested under Node; `fakeplayer.js` stands in for `webapis.avplay` in desktop browsers.
- `tests/`: pytest, including the Node tests and Playwright end-to-end tests.

## Rules

- **The TV runs Chromium 63.** No optional chaining, `??`, ES modules, CSS `inset` or flexbox `gap`. `tests/test_tv_js.py` guards the common ones.
- **Nobody can test on the TV from here.** Say "needs hardware" for AVPlay behaviour, remote keys, Tizen packaging and Samsung's remote API rather than claiming they work.
- **Don't guess Samsung API details.** Check them against Samsung's documentation, and say so when you can't.
- **Style:** small modules, type hints, docstrings on public functions, `logging` not `print` (except CLI output), and British English in anything a user sees.
- **Tests:** run `.venv/bin/pytest` and keep it passing.
