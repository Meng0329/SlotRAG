import os

import pytest

from slotrag.config import AppConfig
from slotrag.doctor import check_services


@pytest.mark.live
def test_configured_services_are_reachable():
    """Live smoke test; run only when all three service keys are configured."""
    required = ["SLOTRAG_AGNES_API_KEY", "SLOTRAG_EMBEDDING_API_KEY", "SLOTRAG_RERANKER_API_KEY"]
    if not all(os.getenv(name) for name in required):
        pytest.skip("set all SlotRAG service API keys to run live smoke test")
    statuses = check_services(AppConfig.from_yaml("configs/default.yaml"))
    assert all(status.ok for status in statuses), statuses
