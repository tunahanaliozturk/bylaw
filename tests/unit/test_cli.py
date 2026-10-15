from importlib.metadata import version

import pytest

from bylaw.cli import main


def test_version_flag_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"bylaw {version('bylaw')}"
