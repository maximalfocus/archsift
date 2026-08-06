from __future__ import annotations

import socket
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from archsift.cli import main


def test_version_matches_installed_distribution(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == version("archsift")


def test_module_entry_point_reports_installed_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "archsift", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == version("archsift")
    assert result.stderr == ""


def test_console_entry_point_reports_installed_version() -> None:
    executable_name = "archsift.exe" if sys.platform == "win32" else "archsift"
    executable = Path(sys.executable).parent / executable_name
    assert executable.is_file()
    result = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == version("archsift")
    assert result.stderr == ""


def test_version_does_not_open_network_connections(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def blocked_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("ArchSift attempted an outbound network connection")

    monkeypatch.setattr(socket, "create_connection", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect", blocked_connect)

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == version("archsift")


def test_no_arguments_prints_honest_foundation_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "Evidence-calibrated architecture decision support" in output
    assert "assess" not in output
