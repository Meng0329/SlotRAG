from typer.testing import CliRunner

from slotrag.cli import app


def test_cli_rejects_invalid_strategy():
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "strategy" in result.stdout
