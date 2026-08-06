from __future__ import annotations

import socket
import subprocess
import sys
import sysconfig
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


def test_importing_module_entry_point_has_no_side_effects() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import archsift.__main__"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_console_entry_point_reports_installed_version() -> None:
    executable_name = "archsift.exe" if sys.platform == "win32" else "archsift"
    executable = Path(sysconfig.get_path("scripts")) / executable_name
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
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == version("archsift")


def test_network_guard_blocks_connection_paths() -> None:
    with pytest.raises(AssertionError):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(AssertionError):
        socket.create_connection(("127.0.0.1", 1))
    with socket.socket() as client:
        with pytest.raises(AssertionError):
            client.connect(("127.0.0.1", 1))
        with pytest.raises(AssertionError):
            client.connect_ex(("127.0.0.1", 1))


def test_no_arguments_prints_honest_foundation_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "Evidence-calibrated architecture decision support" in output
    assert "assess" not in output
