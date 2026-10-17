"""Draw Frame Cast's icons as SVG and render the PNGs the TV and phones need.

The icon is The Frame in miniature: a slim frame and mat around a sunset
picture with a play button, and cast waves coming off the corner. Run it
after changing the drawing:

    .venv/bin/python scripts/render_icons.py

It writes tv/icon.svg and tv/icon.png (512x423, the size Samsung TV apps
use), and the phone page's favicon, home-screen icons and web app manifest.
Rendering uses Playwright's Chromium; set PLAYWRIGHT_CHROMIUM to use another.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TV = ROOT / "tv"
STATIC = ROOT / "framecast" / "static"
log = logging.getLogger("render_icons")

DEFS = """
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#121c45"/>
      <stop offset="0.55" stop-color="#26388f"/>
      <stop offset="1" stop-color="#5a43c4"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.42" cy="0.58" r="0.62">
      <stop offset="0" stop-color="#9cc0ff" stop-opacity="0.38"/>
      <stop offset="1" stop-color="#9cc0ff" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="art" x1="0" y1="0" x2="0.35" y2="1">
      <stop offset="0" stop-color="#ffb46b"/>
      <stop offset="0.5" stop-color="#ff6b7a"/>
      <stop offset="1" stop-color="#a24fd0"/>
    </linearGradient>
    <linearGradient id="bezel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#e3ddd1"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.28"/>
      <stop offset="0.45" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <filter id="shadow" x="-25%" y="-25%" width="150%" height="160%">
      <feDropShadow dx="0" dy="12" stdDeviation="14" flood-color="#050a22" flood-opacity="0.6"/>
    </filter>
  </defs>"""


def frame(x: float, y: float, width: float, waves: bool = True) -> str:
    """The frame, mat, picture and play button, with its top-left corner at (x, y)."""
    height = width * 0.62
    bezel = width * 0.045
    mat = width * 0.068
    art_x, art_y = x + bezel + mat, y + bezel + mat
    art_w, art_h = width - 2 * (bezel + mat), height - 2 * (bezel + mat)
    cx, cy = art_x + art_w / 2, art_y + art_h / 2
    t = art_h * 0.24  # half the play button's height
    play = f"{cx - t * 0.75:.1f},{cy - t:.1f} {cx - t * 0.75:.1f},{cy + t:.1f} {cx + t * 0.95:.1f},{cy:.1f}"
    parts = [
        f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{width}" height="{height:.1f}" rx="{width * 0.03:.1f}" fill="url(#bezel)"/></g>',
        f'<rect x="{x + bezel:.1f}" y="{y + bezel:.1f}" width="{width - 2 * bezel:.1f}" height="{height - 2 * bezel:.1f}" fill="#fbf8f2"/>',
        f'<rect x="{art_x:.1f}" y="{art_y:.1f}" width="{art_w:.1f}" height="{art_h:.1f}" fill="url(#art)"/>',
        f'<rect x="{art_x:.1f}" y="{art_y:.1f}" width="{art_w:.1f}" height="{art_h:.1f}" fill="url(#sheen)"/>',
        f'<rect x="{art_x:.1f}" y="{art_y:.1f}" width="{art_w:.1f}" height="{art_h:.1f}" fill="none" stroke="#000" stroke-opacity="0.12" stroke-width="{width * 0.008:.1f}"/>',
        f'<polygon points="{play}" fill="#ffffff" stroke="#ffffff" stroke-width="{t * 0.28:.1f}" stroke-linejoin="round"/>',
    ]
    if waves:
        corner_x, corner_y = x + width, y
        stroke = width * 0.034
        for index, opacity in enumerate((1.0, 0.75, 0.5)):
            r = width * (0.07 + 0.068 * index)
            parts.append(
                f'<path d="M{corner_x:.1f} {corner_y - r:.1f} A{r:.1f} {r:.1f} 0 0 1 {corner_x + r:.1f} {corner_y:.1f}" '
                f'fill="none" stroke="#ffffff" stroke-opacity="{opacity}" stroke-width="{stroke:.1f}" stroke-linecap="round"/>'
            )
    return "\n  ".join(parts)


def icon(width: int, height: int, size: float, waves: bool = True, corner: float = 0) -> str:
    """An icon of the given canvas size, with the frame (and waves) centred as a group."""
    frame_h = size * 0.62
    reach = size * 0.225 if waves else 0  # how far the waves stick out up and right
    x = (width - (size + reach)) / 2
    y = (height - (frame_h + reach)) / 2 + reach
    back = (
        f'<rect width="100%" height="100%" rx="{corner}" fill="url(#bg)"/>\n'
        f'  <rect width="100%" height="100%" rx="{corner}" fill="url(#glow)"/>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f"{DEFS}\n  {back}\n  {frame(x, y, size, waves)}\n</svg>\n"
    )


def render(svg: str, path: Path, width: int, height: int, browser) -> None:
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_content(f'<html><body style="margin:0">{svg}</body></html>')
    page.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": width, "height": height})
    page.close()
    log.info("Wrote %s", path.relative_to(ROOT))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tv_svg = icon(512, 423, 300)
    square = icon(512, 512, 330)
    small = icon(64, 64, 52, waves=False, corner=14)  # the browser tab icon: just the frame, on a rounded tile
    (TV / "icon.svg").write_text(tv_svg)
    (STATIC / "icon.svg").write_text(square)
    (STATIC / "favicon.svg").write_text(small)
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable)
        render(tv_svg, TV / "icon.png", 512, 423, browser)
        for size, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
            render(icon(size, size, size * 0.645), STATIC / name, size, size, browser)
        browser.close()
    manifest = {
        "name": "Frame Cast",
        "short_name": "Frame Cast",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#111418",
        "theme_color": "#111418",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (STATIC / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log.info("Wrote framecast/static/manifest.json")


if __name__ == "__main__":
    main()
