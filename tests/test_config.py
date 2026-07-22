from slotrag.config import AppConfig


def test_default_config_caps_operational_rpm_below_provider_allowance():
    config = AppConfig.from_yaml("configs/default.yaml")
    assert config.rate_limit.provider_rpm == 30
    assert config.rate_limit.operational_rpm == 20
    assert config.rate_limit.max_concurrency == 4


def test_public_config_contains_no_secret_value(monkeypatch):
    monkeypatch.setenv("SLOTRAG_AGNES_API_KEY", "do-not-leak")
    config = AppConfig.from_yaml("configs/default.yaml")
    assert "do-not-leak" not in str(config.public_dict())
