import pytest

from jarvis.tools import shell


def test_allowed_command_runs_and_returns_output():
    result = shell.SHELL_EXECUTE.handler({"command": "python --version"})

    assert result.startswith("exit code 0")
    assert "Python" in result


def test_disallowed_executable_is_rejected():
    with pytest.raises(ValueError, match="not an allowed command"):
        shell.SHELL_EXECUTE.handler({"command": "del somefile.txt"})


@pytest.mark.parametrize(
    "command",
    [
        "git status && del file.txt",
        "git status; rm -rf .",
        "git log | findstr secret",
        "echo hi > out.txt",
        "git status `whoami`",
    ],
)
def test_forbidden_characters_are_rejected(command):
    with pytest.raises(ValueError, match="forbidden"):
        shell.SHELL_EXECUTE.handler({"command": command})


def test_empty_command_is_rejected():
    with pytest.raises(ValueError, match="no command provided"):
        shell.SHELL_EXECUTE.handler({"command": ""})


def test_command_times_out(monkeypatch):
    monkeypatch.setattr(shell, "TIMEOUT_SECONDS", 1)

    with pytest.raises(ValueError, match="timed out"):
        shell.SHELL_EXECUTE.handler({"command": 'python -c __import__("time").sleep(3)'})


def test_nonzero_exit_code_is_reported_not_raised():
    result = shell.SHELL_EXECUTE.handler({"command": "python -c exit(1)"})

    assert result.startswith("exit code 1")


def test_command_runs_with_workspace_as_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    result = shell.SHELL_EXECUTE.handler({"command": "python -c print(__import__('os').getcwd())"})

    assert result.startswith("exit code 0")
    assert str(tmp_path.resolve()) in result
