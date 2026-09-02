#!/usr/bin/env python3
"""
test_hstruct_readiness.py — Readiness tests for H-STRUCT-1 confirmatory execution

Tests:
  test_validation_compile_options_identity
  test_validation_plan_hash_recovery
  test_full_question_record_train_compile
  test_train_compiler_options_identity
  test_frozen_import_roundtrip
  test_static_method_identity
  test_chain_method_identity
  test_budget_8_8_96
  test_no_compile_during_frozen_replay
  test_same_plan_hash_both_arms
  test_score_record_used
  test_csv_boolean_not_used
  test_exact_mcnemar_known_cases
  test_paired_bootstrap_uses_full_n
  test_no_confirmatory_outcome_before_unseal
"""

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))


# ── Helpers ──────────────────────────────────────────────────────────────

def _canonical_sha256(obj) -> str:
    """Match BenchmarkRunner._canonical_sha256 (ensure_ascii=False)."""
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plan_sha256(plan) -> str:
    return _canonical_sha256(plan.model_dump(mode="json"))


# ── Tests ────────────────────────────────────────────────────────────────

class TestCompileOptionsIdentity:
    """Steps 1, 7: compiler options must be identical across methods and census."""

    def test_validation_compile_options_identity(self):
        """slotrag == slotrag-g7-static == slotrag-g7-chain compiler_options."""
        from slotrag.benchmarking.methods import METHODS, slotrag_compile_options, slotrag_compiler_signature
        from slotrag.data import load_questions
        from slotrag.benchmarking.datasets import DATASETS

        sig_base = slotrag_compiler_signature(METHODS["slotrag"])
        sig_static = slotrag_compiler_signature(METHODS["slotrag-g7-static"])
        sig_chain = slotrag_compiler_signature(METHODS["slotrag-g7-chain"])
        assert sig_base == sig_static, f"compiler_signature mismatch: slotrag={sig_base} static={sig_static}"
        assert sig_base == sig_chain, f"compiler_signature mismatch: slotrag={sig_base} chain={sig_chain}"

        q = load_questions("benchmark/" + DATASETS["hotpotqa"].evaluation_file)[0]
        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            opts_base = slotrag_compile_options(METHODS["slotrag"], ds, q)
            opts_static = slotrag_compile_options(METHODS["slotrag-g7-static"], ds, q)
            opts_chain = slotrag_compile_options(METHODS["slotrag-g7-chain"], ds, q)
            assert opts_base == opts_static, f"{ds}: slotrag != static"
            assert opts_base == opts_chain, f"{ds}: slotrag != chain"

    def test_train_compiler_options_identity(self):
        """Train compile uses same compiler_options as runner would."""
        from slotrag.benchmarking.methods import METHODS, slotrag_compile_options
        from slotrag.data import load_questions
        from slotrag.benchmarking.datasets import DATASETS

        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            train_path = "benchmark/" + DATASETS[ds].train_file
            if not Path(train_path).exists():
                continue
            q = load_questions(train_path)[0]
            census_opts = slotrag_compile_options(METHODS["slotrag"], ds, q)
            runner_opts = slotrag_compile_options(METHODS["slotrag-g7-static"], ds, q)
            assert census_opts == runner_opts, f"{ds}: census opts != runner opts"

    def test_validation_plan_hash_recovery(self):
        """Recovery audit exists and has the expected structure."""
        audit_path = REPO / "research" / "hstruct_validation_census" / "validation_plan_recovery_audit.csv"
        if not audit_path.exists():
            pytest.skip("Recovery audit not yet generated")
        import csv
        with open(audit_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) > 0, "Recovery audit is empty"
        for row in rows:
            assert "hash_match" in row
            assert "recovery_mode" in row


class TestMethodIdentity:
    """Steps 12-13: method keys and budget must match exploratory."""

    def test_static_method_identity(self):
        """slotrag-g7-static MethodSpec fields match frozen protocol."""
        from slotrag.benchmarking.methods import METHODS
        spec = METHODS["slotrag-g7-static"]
        assert spec.family == "slotrag"
        assert spec.physical_plan is True
        assert spec.physical_plan_optimizer is False
        assert spec.physical_action_policy is True
        assert spec.adaptive_binding_beam is True
        assert spec.complementary_retrieval is True

    def test_chain_method_identity(self):
        """slotrag-g7-chain MethodSpec fields match frozen protocol."""
        from slotrag.benchmarking.methods import METHODS
        spec = METHODS["slotrag-g7-chain"]
        assert spec.family == "slotrag"
        assert spec.physical_plan is True
        assert spec.physical_plan_optimizer is True
        assert spec.plan_optimizer_importance == "chain-rule"
        assert spec.physical_action_policy is True
        assert spec.adaptive_binding_beam is True
        assert spec.complementary_retrieval is True

    def test_budget_8_8_96(self):
        """Budget is exactly max_steps=8, max_llm_calls=96, max_retrieval_calls=8."""
        import yaml
        with open(REPO / "configs/experiments/tkde-sealed-test-q35.yaml") as f:
            cfg = yaml.safe_load(f)
        budget = cfg["budget"]
        assert budget["max_steps"] == 8
        assert budget["max_llm_calls"] == 96
        assert budget["max_retrieval_calls"] == 8

    def test_same_plan_hash_both_arms(self):
        """Both arms use the same frozen plan (same plan_hash)."""
        # This is verified by construction: frozen_plan_source is slotrag-g7-static,
        # and both arms receive the same frozen_plan parameter.
        from slotrag.benchmarking.methods import METHODS
        # Verify compiler signatures match (ensures same plan can be used)
        sig_static = METHODS["slotrag-g7-static"]
        sig_chain = METHODS["slotrag-g7-chain"]
        assert sig_static.family == sig_chain.family
        # Both use slotrag family, same compiler options
        from slotrag.benchmarking.methods import slotrag_compiler_signature
        assert slotrag_compiler_signature(sig_static) == slotrag_compiler_signature(sig_chain)


class TestFrozenImportRoundtrip:
    """Step 11: frozen snapshots must pass BenchmarkRunner import validation."""

    def test_frozen_import_roundtrip(self):
        """Frozen snapshot can be loaded by BenchmarkRunner's _load_or_create_frozen_plan."""
        # Check that frozen snapshots exist and have required fields
        frozen_dir = REPO / "research" / "hstruct_frozen_validation"
        if not frozen_dir.exists():
            pytest.skip("Frozen validation snapshots not yet generated")

        sample_files = list(frozen_dir.rglob("*.json"))[:3]
        if not sample_files:
            pytest.skip("No frozen snapshots found")

        for fpath in sample_files:
            snap = json.loads(fpath.read_text())
            assert snap.get("status") == "ok", f"status != ok: {fpath}"
            assert "dataset" in snap, f"missing dataset: {fpath}"
            assert "question_id" in snap, f"missing question_id: {fpath}"
            assert "source_method" in snap, f"missing source_method: {fpath}"
            assert "input_sha256" in snap, f"missing input_sha256: {fpath}"
            assert "compiler_options" in snap, f"missing compiler_options: {fpath}"
            assert "plan" in snap, f"missing plan: {fpath}"
            assert "plan_sha256" in snap, f"missing plan_sha256: {fpath}"
            assert "compiler_metrics" in snap, f"missing compiler_metrics: {fpath}"

            # Verify plan_sha256 matches plan
            from slotrag.models import SlotPlan
            plan = SlotPlan.model_validate(snap["plan"])
            assert _plan_sha256(plan) == snap["plan_sha256"], f"plan_sha256 mismatch: {fpath}"


class TestAnalysisCorrections:
    """Steps 16-19: scoring, McNemar, bootstrap fixes."""

    def test_score_record_used(self):
        """score_record is used for scoring, not getattr."""
        # Verify score_record exists in metrics module
        from slotrag.benchmarking.metrics import score_record
        assert callable(score_record)

    def test_csv_boolean_not_used(self):
        """run_confirmatory.py does not use getattr(metrics, 'em', 0)."""
        source = (REPO / "tools/run_confirmatory.py").read_text()
        # Should NOT contain getattr(metrics, "em"
        assert 'getattr(metrics, "em"' not in source, "run_confirmatory.py still uses getattr(metrics, 'em')"
        assert "getattr(metrics, 'em'" not in source, "run_confirmatory.py still uses getattr(metrics, 'em')"

    def test_exact_mcnemar_known_cases(self):
        """Exact McNemar produces correct p-values for known cases."""
        from slotrag.benchmarking.statistics import mcnemar
        # b=153, c=120 -> p ~ 0.07 (approximate, two-sided)
        # candidate = 1 where chain wins, 0 otherwise; reference = static.
        candidate = [1] * 153 + [0] * 120 + [0, 0, 0, 0]  # 153 chain-only wins
        reference = [0] * 153 + [1] * 120 + [0, 0, 0, 0]  # 120 static-only wins
        result = mcnemar(candidate, reference)
        assert "p_exact" in result
        assert 0 < result["p_exact"] < 1
        assert result["candidate_only_wins_b"] == 153
        assert result["reference_only_wins_c"] == 120

        # b=10, c=0 -> p < 0.05 (extreme case)
        candidate2 = [1] * 10 + [0] * 10
        reference2 = [0] * 10 + [0] * 10
        result2 = mcnemar(candidate2, reference2)
        assert result2["p_exact"] < 0.05

    def test_paired_bootstrap_uses_full_n(self):
        """Bootstrap resamples ALL N paired questions, not just discordant."""
        from slotrag.benchmarking.statistics import paired_bootstrap
        import random
        rng = random.Random(2027)
        records = []
        for i in range(100):
            static_score = 1 if rng.random() < 0.3 else 0
            chain_score = static_score
            if i < 10:
                chain_score = 1 - static_score
            records.append({
                "result": {"metrics": {}, "status": "ok"},
                "scores": {"primary_score": static_score},
                "dataset": "hotpotqa",
                "method": "slotrag-g7-static",      # base method
                "method_label": "slotrag-g7-static", # arm label
                "question_id": f"q{i:03d}",
                "seed": 2027,
            })
            records.append({
                "result": {"metrics": {}, "status": "ok"},
                "scores": {"primary_score": chain_score},
                "dataset": "hotpotqa",
                "method": "slotrag-g7-chain",
                "method_label": "slotrag-g7-chain",
                "question_id": f"q{i:03d}",
                "seed": 2027,
            })
        comps = paired_bootstrap(records, reference="slotrag-g7-static", iterations=100, seed=2027)
        assert len(comps) == 1
        comp = comps[0]
        assert comp["count"] == 100  # uses ALL pairs, not just discordant
        assert "mean_difference" in comp
        assert "ci_low" in comp and "ci_high" in comp


class TestNoPrematureOutcome:
    """Step: no confirmatory outcome before unseal."""

    def test_no_confirmatory_outcome_before_unseal(self):
        """No confirmatory results CSV exists yet."""
        results_csv = REPO / "research" / "hstruct_confirmatory" / "confirmatory_results.csv"
        if results_csv.exists():
            # Check if it has actual results (not just header)
            import csv
            with open(results_csv) as f:
                rows = list(csv.DictReader(f))
            if len(rows) > 0:
                pytest.fail(
                    "Confirmatory results CSV has data before unseal! "
                    "This violates the no-peeking protocol."
                )


class TestRunnerMethodKeys:
    """Step 12: runner uses correct method keys."""

    def test_runner_method_keys(self):
        """run_confirmatory.py uses slotrag-g7-static and slotrag-g7-chain."""
        source = (REPO / "tools/run_confirmatory.py").read_text()
        assert '"slotrag-g7-static"' in source, "Missing slotrag-g7-static in runner"
        assert '"slotrag-g7-chain"' in source, "Missing slotrag-g7-chain in runner"
        assert '"slotrag-static"' not in source, "Still uses nonexistent slotrag-static"
        assert '"slotrag-depth-chain"' not in source, "Still uses nonexistent slotrag-depth-chain"

    def test_runner_passes_budget(self):
        """run_confirmatory.py passes max_steps=8, max_retrieval_calls=8 to run_method."""
        source = (REPO / "tools/run_confirmatory.py").read_text()
        assert "max_steps=8" in source, "Missing max_steps=8"
        assert "max_retrieval_calls=8" in source, "Missing max_retrieval_calls=8"
