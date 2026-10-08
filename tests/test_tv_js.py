"""Run the TV app's JavaScript unit tests under Node, if Node is installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

TV_TESTS = sorted((Path(__file__).resolve().parent.parent / "tv" / "tests").glob("*.test.js"))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")
def test_tv_javascript():
    result = subprocess.run(
        ["node", "--test", *map(str, TV_TESTS)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


TV_DIR = Path(__file__).resolve().parent.parent / "tv"
# The 2019 Frame's web engine is Chromium 63. These would break it but pass in a modern browser.
TOO_NEW = {
    "?.": "optional chaining (Chrome 80)",
    "??": "nullish coalescing (Chrome 80)",
    ".replaceAll(": "String.replaceAll (Chrome 85)",
    ".flat(": "Array.flat (Chrome 69)",
    ".flatMap(": "Array.flatMap (Chrome 69)",
    ".at(": "Array.at (Chrome 92)",
    "import ": "ES modules don't load from the app's file:// origin",
}
TOO_NEW_CSS = {
    "inset:": "inset (Chrome 87)",
    "gap:": "flexbox gap (Chrome 84)",
    "aspect-ratio": "aspect-ratio (Chrome 88)",
    ":is(": ":is() (Chrome 88)",
}


def test_tv_code_avoids_features_newer_than_chromium_63():
    problems = []
    for path in sorted((TV_DIR / "js").glob("*.js")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("//", 1)[0]
            problems += [f"{path.name}:{number}: {why}" for token, why in TOO_NEW.items() if token in code]
    for path in sorted((TV_DIR / "css").glob("*.css")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith(("/*", "*")) or "`" in line:
                continue
            problems += [f"{path.name}:{number}: {why}" for token, why in TOO_NEW_CSS.items() if token in line]
    assert problems == []
