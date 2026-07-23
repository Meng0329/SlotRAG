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


def test_qwen36_environment_alias_normalizes_chat_endpoint_without_leaking_key(monkeypatch):
    monkeypatch.setenv("QWEN36_BASE_URL", "http://qwen.local/v1/chat/completions")
    monkeypatch.setenv("QWEN36_MODEL", "qwen3.6-27b")
    monkeypatch.setenv("QWEN36_API_KEY", "qwen-secret")
    config = AppConfig.from_yaml("configs/default.yaml")
    assert config.agnes.base_url == "http://qwen.local/v1"
    assert config.agnes.model == "qwen3.6-27b"
    assert config.agnes.api_key_env == "QWEN36_API_KEY"
    assert "qwen-secret" not in str(config.public_dict())


def test_provider_specific_limits_override_global_defaults(monkeypatch):
    monkeypatch.setenv("SLOTRAG_AGNES_MAX_CONCURRENCY", "64")
    monkeypatch.setenv("SLOTRAG_AGNES_OPERATIONAL_RPM", "480")
    monkeypatch.setenv("SLOTRAG_AGNES_PROVIDER_RPM", "600")
    config = AppConfig.from_yaml("configs/default.yaml")
    assert config.rate_limit.agnes_max_concurrency == 64
    assert config.rate_limit.agnes_operational_rpm == 480
    assert config.rate_limit.agnes_provider_rpm == 600
