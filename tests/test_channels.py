import json

import pytest

from framecast.channels import ChannelError, ChannelStore, logo_type

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20


def test_add_and_reload(tmp_path):
    store = ChannelStore(tmp_path)
    news = store.add("  News   24 ", "Watch https://site/live/news24 now")
    assert news.name == "News 24"
    assert news.url == "https://site/live/news24"
    again = ChannelStore(tmp_path)
    assert [c.name for c in again.all()] == ["News 24"]
    assert again.get(news.id).url == "https://site/live/news24"


def test_validation(tmp_path):
    store = ChannelStore(tmp_path)
    with pytest.raises(ChannelError, match="name"):
        store.add("   ", "https://site/x")
    with pytest.raises(ChannelError, match="web address"):
        store.add("Thing", "not a link")
    long = store.add("x" * 200, "https://site/x")
    assert len(long.name) == 60


def test_update_delete_and_move(tmp_path):
    store = ChannelStore(tmp_path)
    a = store.add("A", "https://site/a")
    b = store.add("B", "https://site/b")
    c = store.add("C", "https://site/c")
    store.update(b.id, name="Bee", url="https://site/bee")
    assert store.get(b.id).name == "Bee" and store.get(b.id).url == "https://site/bee"
    store.move(c.id, -1)
    assert [x.name for x in store.all()] == ["A", "C", "Bee"]
    store.move(a.id, -5)  # already at the top
    assert [x.name for x in store.all()] == ["A", "C", "Bee"]
    store.delete(c.id)
    assert [x.name for x in ChannelStore(tmp_path).all()] == ["A", "Bee"]
    with pytest.raises(ChannelError, match="doesn't exist"):
        store.delete("nope")


def test_neighbour_wraps(tmp_path):
    store = ChannelStore(tmp_path)
    a = store.add("A", "https://site/a")
    b = store.add("B", "https://site/b")
    assert store.neighbour(a.id, 1).id == b.id
    assert store.neighbour(b.id, 1).id == a.id
    assert store.neighbour(a.id, -1).id == b.id
    assert store.neighbour("unknown", 1).id == a.id
    assert ChannelStore(tmp_path / "empty").neighbour("x", 1) is None


def test_logo_lifecycle(tmp_path):
    store = ChannelStore(tmp_path)
    channel = store.add("A", "https://site/a")
    store.set_logo(channel.id, PNG)
    path, media_type = store.logo_file(channel.id)
    assert media_type == "image/png" and path.read_bytes() == PNG
    assert store.get(channel.id).public()["has_logo"] is True
    store.set_logo(channel.id, JPEG)
    path, media_type = store.logo_file(channel.id)
    assert media_type == "image/jpeg"
    assert not (tmp_path / "logos" / f"{channel.id}.png").exists()
    assert store.get(channel.id).logo_version == 2
    store.remove_logo(channel.id)
    assert store.logo_file(channel.id) is None
    store.set_logo(channel.id, PNG)
    store.delete(channel.id)
    assert list((tmp_path / "logos").iterdir()) == []


def test_logo_rejections(tmp_path):
    store = ChannelStore(tmp_path)
    channel = store.add("A", "https://site/a")
    with pytest.raises(ChannelError, match="PNG, JPEG"):
        store.set_logo(channel.id, b"<svg></svg>")
    with pytest.raises(ChannelError, match="empty"):
        store.set_logo(channel.id, b"")
    with pytest.raises(ChannelError, match="too big"):
        store.set_logo(channel.id, PNG + b"\x00" * (3 * 1024 * 1024))


def test_logo_type():
    assert logo_type(PNG) == ("png", "image/png")
    assert logo_type(b"GIF89a....") == ("gif", "image/gif")
    assert logo_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("webp", "image/webp")
    assert logo_type(b"hello") is None


def test_broken_file_set_aside(tmp_path):
    (tmp_path / "channels.json").write_text("{not json")
    store = ChannelStore(tmp_path)
    assert store.all() == []
    assert (tmp_path / "channels.broken.json").exists()
    store.add("A", "https://site/a")
    assert json.loads((tmp_path / "channels.json").read_text())[0]["name"] == "A"
