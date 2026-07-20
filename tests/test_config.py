from slotrag.config import AppConfig


def test_public_config_contains_no_secret_value(monkeypatch):
    monkeypatch.setenv("SLOTRAG_AGNES_API_KEY", "do-not-leak")
    config = AppConfig.from_yaml("configs/default.yaml")
    assert "do-not-leak" not in str(config.public_dict())
