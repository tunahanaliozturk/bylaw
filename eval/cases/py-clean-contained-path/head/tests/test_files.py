from pathlib import Path

import pytest

from app import files


def test_an_upload_is_read_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "UPLOAD_DIR", tmp_path)
    (tmp_path / "a.txt").write_bytes(b"hi")

    assert files.read_upload("a.txt") == b"hi"


def test_a_name_that_leaves_the_upload_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "UPLOAD_DIR", tmp_path)

    with pytest.raises(PermissionError):
        files.read_upload("../secret.txt")
