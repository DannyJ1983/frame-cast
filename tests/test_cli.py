from pathlib import Path

import pytest

from framecast.__main__ import load_config_file, main
from framecast.config import Settings


def test_config_file_fills_gaps_only(tmp_path):
    path = tmp_path / "frame-cast.env"
    path.write_text("# comment\nFRAMECAST_PORT=9000\nFRAMECAST_TV_HOST='192.168.1.50'\n\nnot a setting\n")
    environ = {"FRAMECAST_PORT": "8100"}
    load_config_file(path, environ)
    assert environ == {"FRAMECAST_PORT": "8100", "FRAMECAST_TV_HOST": "192.168.1.50"}


def test_settings_from_env():
    settings = Settings.from_env(
        {
            "FRAMECAST_PORT": "9001",
            "FRAMECAST_RELAY": "always",
            "FRAMECAST_TV_HOST": "10.0.0.9",
            "FRAMECAST_STATE_DIR": "/var/lib/frame-cast",
        }
    )
    assert settings.port == 9001
    assert settings.relay == "always"
    assert settings.tv_host == "10.0.0.9"
    assert settings.token_file == Path("/var/lib/frame-cast/tv-token.txt")


def test_bad_relay_mode_rejected():
    with pytest.raises(ValueError):
        Settings.from_env({"FRAMECAST_RELAY": "sometimes"})


def test_resolve_rejects_non_links(capsys):
    assert main(["resolve", "no link here"]) == 2
    assert "doesn't look like a web address" in capsys.readouterr().err


def test_tv_commands_need_an_address(capsys, monkeypatch):
    monkeypatch.delenv("FRAMECAST_TV_HOST", raising=False)
    assert main(["tv-pair"]) == 2
    assert "--tv-host" in capsys.readouterr().err
