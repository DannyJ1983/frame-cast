"""Turning Spotify's player and queue answers into what the Now Playing screen shows. No I/O here."""

from __future__ import annotations

from typing import Any

QUEUE_LENGTH = 5


def pick_image(images: Any, width: int) -> str:
    """The smallest image at least ``width`` wide, or the largest there is; "" if none."""
    usable = [i for i in images or [] if isinstance(i, dict) and i.get("url")]
    if not usable:
        return ""
    usable.sort(key=lambda i: i.get("width") or 0)
    for image in usable:
        if (image.get("width") or 0) >= width:
            return str(image["url"])
    return str(usable[-1]["url"])


def item_info(item: Any) -> dict[str, Any] | None:
    """Title, artist, album, art and length of a track or podcast episode."""
    if not isinstance(item, dict):
        return None
    if item.get("type") == "episode":
        show = item.get("show") or {}
        images = item.get("images") or show.get("images")
        artists, album = str(show.get("publisher") or show.get("name") or ""), str(show.get("name") or "")
    else:
        album_data = item.get("album") or {}
        images = album_data.get("images")
        artists = ", ".join(str(a.get("name")) for a in item.get("artists") or [] if isinstance(a, dict) and a.get("name"))
        album = str(album_data.get("name") or "")
    return {
        "id": str(item.get("id") or item.get("uri") or item.get("name") or ""),
        "title": str(item.get("name") or ""),
        "artists": artists,
        "album": album,
        "art": pick_image(images, 600),
        "thumb": pick_image(images, 64),
        "duration_ms": int(item.get("duration_ms") or 0),
        "kind": "episode" if item.get("type") == "episode" else "track",
    }


def same_device(name: Any, wanted: str) -> bool:
    """Device names match ignoring case and spaces at the ends."""
    return isinstance(name, str) and name.strip().casefold() == wanted.strip().casefold()


def playback(state: Any, device_name: str) -> dict[str, Any]:
    """What's happening on ``device_name``, from GET /me/player (None when Spotify answered 204)."""
    if not isinstance(state, dict) or not state.get("device"):
        return {"state": "idle", "device": device_name}
    device = state["device"]
    if not same_device(device.get("name"), device_name):
        return {"state": "elsewhere", "device": device_name, "active_device": str(device.get("name") or "")}
    if state.get("currently_playing_type") == "ad":
        return {"state": "advert", "device": str(device.get("name"))}
    track = item_info(state.get("item"))
    if track is None:
        return {"state": "idle", "device": str(device.get("name"))}
    return {
        "state": "playing" if state.get("is_playing") else "paused",
        "device": str(device.get("name")),
        "track": track,
        "progress_ms": int(state.get("progress_ms") or 0),
        "shuffle": bool(state.get("shuffle_state")),
        "repeat": str(state.get("repeat_state") or "off"),
    }


def up_next(queue: Any, limit: int = QUEUE_LENGTH) -> list[dict[str, Any]]:
    """The next few tracks from GET /me/player/queue."""
    items = queue.get("queue") if isinstance(queue, dict) else None
    upcoming = [item_info(item) for item in items or []]
    return [item for item in upcoming if item][:limit]
