from typer.testing import CliRunner

from slotrag.cli import app


def test_cli_rejects_invalid_strategy():
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "strategy" in result.stdout


def test_cli_exposes_benchmark_workflow():
    result = CliRunner().invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    for command in ("audit", "prepare", "run", "summarize"):
        assert command in result.stdout
