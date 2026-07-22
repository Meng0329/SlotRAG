import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from slotrag.concurrency import FileConcurrencyLimiter, FileRateLimiter, locked_update_json


def test_locked_update_json_preserves_all_concurrent_updates(tmp_path):
    path = tmp_path / "counter.json"

    def increment(_index):
        def update(current):
            current["count"] = current.get("count", 0) + 1
            return current

        locked_update_json(path, update, default={})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(increment, range(80)))

    assert json.loads(path.read_text(encoding="utf-8")) == {"count": 80}
    assert not list(tmp_path.glob("*.part*"))


def test_file_rate_limiter_spaces_requests_at_operational_rpm(tmp_path):
    now = [100.0]
    sleeps = []

    def clock():
        return now[0]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = FileRateLimiter(tmp_path / "agnes.json", rpm=20, clock=clock, sleeper=sleep)

    assert limiter.acquire() == pytest.approx(0.0)
    assert limiter.acquire() == pytest.approx(3.0)
    assert sleeps == pytest.approx([3.0])
    state = json.loads((tmp_path / "agnes.json").read_text(encoding="utf-8"))
    assert state["rpm"] == 20
    assert state["acquisitions"] == 2


def test_file_rate_limiter_serializes_concurrent_callers(tmp_path):
    limiter_path = tmp_path / "shared.json"

    def acquire(_index):
        return FileRateLimiter(limiter_path, rpm=6000).acquire()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(acquire, range(6)))

    state = json.loads(limiter_path.read_text(encoding="utf-8"))
    assert state["acquisitions"] == 6
    assert state["rpm"] == 6000


def test_file_concurrency_limiter_caps_inflight_requests(tmp_path):
    limiter = FileConcurrencyLimiter(tmp_path / "agnes", limit=2)
    mutex = threading.Lock()
    active = 0
    peak = 0

    def work(_index):
        nonlocal active, peak
        with limiter.permit():
            with mutex:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with mutex:
                active -= 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(work, range(6)))

    assert peak == 2
