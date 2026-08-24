import pytest

from jarvis.tools import filesystem


def test_filesystem_read_within_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    sample = tmp_path / "notes.txt"
    sample.write_text("hello from the workspace", encoding="utf-8")

    result = filesystem.FILESYSTEM_READ.handler({"path": "notes.txt"})

    assert result == "hello from the workspace"


def test_filesystem_read_rejects_traversal_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read me", encoding="utf-8")
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(workspace))

    with pytest.raises(ValueError, match="outside the allowed workspace"):
        filesystem.FILESYSTEM_READ.handler({"path": "../secret.txt"})


def test_filesystem_read_rejects_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="not a file"):
        filesystem.FILESYSTEM_READ.handler({"path": "does-not-exist.txt"})


def test_filesystem_read_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (filesystem.MAX_READ_BYTES + 1))

    with pytest.raises(ValueError, match="too large"):
        filesystem.FILESYSTEM_READ.handler({"path": "big.txt"})


@pytest.mark.parametrize("protected_path", [".env", "secrets.pem", "id.key"])
def test_filesystem_read_rejects_protected_files(tmp_path, monkeypatch, protected_path):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    target = tmp_path / protected_path
    target.write_text("super secret", encoding="utf-8")

    with pytest.raises(ValueError, match="protected file"):
        filesystem.FILESYSTEM_READ.handler({"path": protected_path})


def test_filesystem_read_rejects_inside_git_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.git"):
        filesystem.FILESYSTEM_READ.handler({"path": ".git/config"})


def test_filesystem_write_creates_new_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    result = filesystem.FILESYSTEM_WRITE.handler({"path": "new.txt", "content": "hello"})

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"
    assert result.startswith("Created")


def test_filesystem_write_overwrites_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))
    existing = tmp_path / "existing.txt"
    existing.write_text("old content", encoding="utf-8")

    result = filesystem.FILESYSTEM_WRITE.handler({"path": "existing.txt", "content": "new content"})

    assert existing.read_text(encoding="utf-8") == "new content"
    assert result.startswith("Overwrote")


def test_filesystem_write_creates_parent_directories_within_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    filesystem.FILESYSTEM_WRITE.handler({"path": "sub/dir/file.txt", "content": "nested"})

    assert (tmp_path / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "nested"


def test_filesystem_write_rejects_traversal_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(workspace))

    with pytest.raises(ValueError, match="outside the allowed workspace"):
        filesystem.FILESYSTEM_WRITE.handler({"path": "../escape.txt", "content": "x"})


def test_filesystem_write_rejects_protected_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="protected file"):
        filesystem.FILESYSTEM_WRITE.handler({"path": ".env", "content": "ANTHROPIC_API_KEY=evil"})
    assert not (tmp_path / ".env").exists()


def test_filesystem_write_rejects_oversized_content(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="too large"):
        filesystem.FILESYSTEM_WRITE.handler(
            {"path": "big.txt", "content": "x" * (filesystem.MAX_WRITE_BYTES + 1)}
        )
    assert not (tmp_path / "big.txt").exists()


def test_filesystem_write_rejects_non_string_content(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLS_WORKSPACE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="must be a string"):
        filesystem.FILESYSTEM_WRITE.handler({"path": "bad.txt", "content": 12345})
