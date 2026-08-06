from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import sysconfig
from importlib.metadata import version
from pathlib import Path

import pytest

from archsift.cli import main
from archsift.diagnostics import ExitCode


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


def test_non_ascii_output_survives_ascii_only_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii", line_buffering=True)
    monkeypatch.setattr(sys, "stdout", stream)
    target = tmp_path / "crème-case"

    assert main(["init", str(target)]) == ExitCode.SUCCESS

    expected = f"Created ArchSift case workspace: {target}\n"
    actual = stream.buffer.getvalue().decode("ascii")
    assert actual == expected.encode("ascii", "backslashreplace").decode("ascii")


def test_json_output_parses_on_ascii_only_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii", line_buffering=True)
    monkeypatch.setattr(sys, "stdout", stream)
    target = tmp_path / "😀"

    assert main(["init", str(target), "--json"]) == ExitCode.SUCCESS

    payload = json.loads(stream.buffer.getvalue().decode("ascii"))
    assert payload["status"] == "created"
    assert payload["exit_code"] == 0
    assert payload["workspace"] == str(target)
