from framecast.links import extract_url


def test_bare_url():
    assert extract_url("https://example.com/watch?v=1") == "https://example.com/watch?v=1"


def test_url_inside_shared_text():
    text = "Great match highlights\nhttps://example.com/live/stream-1 via SomeApp"
    assert extract_url(text) == "https://example.com/live/stream-1"


def test_trailing_punctuation_removed():
    assert extract_url("Watch this: https://example.com/a.") == "https://example.com/a"
    assert extract_url("(see https://example.com/a)") == "https://example.com/a"


def test_balanced_brackets_kept():
    url = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert extract_url(url) == url


def test_no_url():
    assert extract_url("nothing here") is None
    assert extract_url("") is None
