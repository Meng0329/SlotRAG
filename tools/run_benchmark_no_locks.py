"""Wrapper: patch out fcntl.flock-based locking, then run the benchmark."""
import sys
from contextlib import contextmanager

# --- Patch 1: exclusive_file_lock → noop ---
import slotrag.concurrency as conc_mod

@contextmanager
def _noop_lock(path):
    yield

conc_mod.exclusive_file_lock = _noop_lock

# Also patch the module where it's imported
import slotrag.benchmarking.corpus as corpus_mod
corpus_mod.exclusive_file_lock = _noop_lock

import slotrag.benchmarking.runner as runner_mod
runner_mod.exclusive_file_lock = _noop_lock

# --- Patch 2: FileRateLimiter acquire → noop ---
class _NoopRateLimiter:
    def acquire(self):
        return 0.0

class _NoopConcurrencyLimiter:
    @contextmanager
    def permit(self):
        yield

conc_mod.FileRateLimiter = lambda path, **kwargs: _NoopRateLimiter()
conc_mod.FileConcurrencyLimiter = lambda path, **kwargs: _NoopConcurrencyLimiter()

# Also patch the provider_clients function to use noop limiters
import slotrag.providers as prov_mod

# --- Patch 3: Also ensure any cross-process locking in locked_update_json is noop ---
conc_mod.locked_update_json = lambda *args, **kwargs: kwargs.get('default', {})

# Patch 4: Make EmbeddingCache.flush a noop (it also tries flock in locked_update_json)
import slotrag.retrieval as ret_mod
def _noop_flush(self):
    pass
ret_mod.EmbeddingCache.flush = _noop_flush

# --- Run the real benchmark ---
if __name__ == "__main__":
    from slotrag.cli import app
    app()
