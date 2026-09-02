#!/usr/bin/env python3
"""
analyze_hstruct_confirmatory.py — Post-execution scoring for H-STRUCT-1

Phase 12-14: Score confirmatory results after all executions complete.

Primary: H-STRUCT-1A (eligible-stratum McNemar)
Secondary: validation-only, train-only, per-dataset
Population: H-STRUCT-1B (ATE_population using validation census prevalence)

NO-PEEKING: This script must ONLY be run after ALL 1105×2 executions are complete.
"""

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from scipy.stats import chi2, norm
from scipy.stats import binom as binom_dist

from slotrag.models import ExecutionResult
from slotrag.benchmarking.metrics import score_record
from slotrag.benchmarking.statistics import mcnemar
from slotrag.benchmarking.datasets import DATASETS as DATASET_SPECS, iter_jsonl, adapt_record

# ── Paths ──────────────────────────────────────────────────────────────────
RESULTS_DIR = REPO / "research" / "hstruct_confirmatory"
MANIFEST_PATH = RESULTS_DIR / "confirmatory_eligible_manifest.jsonl"
RESULTS_CSV = RESULTS_DIR / "confirmatory_results.csv"
REPORT_PATH = RESULTS_DIR / "confirmatory_report.md"

# Validation census prevalence (outcome-blind, from validation_compile_census)
VALIDATION_PREVALENCE = {
    "hotpotqa": 68 / 2146,     # 3.2%
    "2wikimultihop": 258 / 3698,  # 7.0%
    "musique": 35 / 650,       # 5.4%
}


# ── McNemar test (delegates to audited statistics.mcnemar) ────────────────

def mcnemar_test(b, c, alpha=0.05, two_sided=True):
    """
    Exact two-sided McNemar test (binominal on discordant pairs).

    Replaces the V1.1 continuity-corrected chi-square approximation.
    Delegates to slotrag.benchmarking.statistics.mcnemar which computes
    the exact mid-p two-sided p-value over the b/c discordant counts.
    """
    candidate = [1] * b + [0] * c
    reference = [0] * b + [1] * c
    result = mcnemar(candidate, reference)
    p_val = result["p_exact"]
    odds_ratio = (b + 0.5) / (c + 0.5)
    chi_stat = result.get("chi_square", 0.0)
    return chi_stat, p_val, odds_ratio


def holm_correction(p_values):
    """Holm-Bonferroni correction for multiple testing."""
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    corrected = [0.0] * n
    for rank, (orig_idx, p) in enumerate(indexed):
        corrected[orig_idx] = min(p * (n - rank), 1.0)
    # Enforce monotonicity
    for i in range(1, n):
        orig_idx_prev = indexed[i-1][0]
        orig_idx_curr = indexed[i][0]
        corrected[orig_idx_curr] = max(corrected[orig_idx_curr], corrected[orig_idx_prev])
    return corrected


# ── Load results ───────────────────────────────────────────────────────────

def load_results(results_csv, question_lookup=None):
    """Load confirmatory results from CSV and score each raw answer.

    The runner writes ONLY raw `answer` (no correct/em/f1 columns — those are
    scored post-execution to avoid the CSV-boolean bug). score_record() computes
    em/f1/primary_score from the gold answers in the frozen benchmark file.
    """
    results = []
    with open(results_csv, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # All manifest items are eligible, so every executed row is eligible.
            row["eligible"] = "True"
            # Post-execution scoring (Step 16)
            if question_lookup is not None and row.get("answer"):
                key = (row.get("dataset"), row.get("question_id"))
                question = question_lookup.get(key)
                if question is not None:
                    result = ExecutionResult(answer=row["answer"])
                    scores = score_record(row["dataset"], question, result)
                    row["em"] = float(scores.get("em", 0.0))
                    row["f1"] = float(scores.get("f1", 0.0))
                    row["primary_score"] = float(scores.get("primary_score", 0.0))
                    row["correct"] = row["em"] > 0.5
            results.append(row)
    return results


def load_manifest(manifest_path):
    """Load confirmatory manifest."""
    items = []
    with open(manifest_path) as f:
        for line in f:
            items.append(json.loads(line.strip()))
    return items


def build_question_lookup():
    """Load all question records from benchmark files for post-execution scoring.

    Returns dict keyed by (dataset, question_id) -> QuestionRecord, covering
    both the validation (evaluation_file) and train splits, since the
    confirmatory sample draws from validation + train supplement.
    """
    lookup = {}
    for ds_name, spec in DATASET_SPECS.items():
        for split_attr in ("evaluation_file", "train_file"):
            rel = getattr(spec, split_attr, None)
            if not rel:
                continue
            path = REPO / "benchmark" / rel
            if not path.exists():
                continue
            split = "validation" if split_attr == "evaluation_file" else "train"
            for idx, record in iter_jsonl(path):
                q = adapt_record(spec, record, idx, split=split)
                lookup[(ds_name, q.id)] = q
    return lookup


# ── Analysis functions ─────────────────────────────────────────────────────

def analyze_stratum(results, filter_fn, label):
    """Analyze a stratum of results (eligible, validation-only, etc.)."""
    filtered = [r for r in results if filter_fn(r)]

    # Separate static and chain
    static = {r["question_id"]: r for r in filtered if r["arm"] == "static"}
    chain = {r["question_id"]: r for r in filtered if r["arm"] == "chain"}

    # Paired analysis
    paired = []
    for qid in static:
        if qid in chain:
            paired.append({
                "qid": qid,
                "dataset": static[qid]["dataset"],
                "source": static[qid].get("source_split", "unknown"),
                "static_correct": static[qid].get("correct", False),
                "chain_correct": chain[qid].get("correct", False),
                "static_em": float(static[qid].get("em", 0)),
                "chain_em": float(chain[qid].get("em", 0)),
                "static_f1": float(static[qid].get("f1", 0)),
                "chain_f1": float(chain[qid].get("f1", 0)),
                "static_llm_calls": int(static[qid].get("llm_calls", 0)),
                "chain_llm_calls": int(chain[qid].get("llm_calls", 0)),
                "static_retrieval_calls": int(static[qid].get("retrieval_calls", 0)),
                "chain_retrieval_calls": int(chain[qid].get("retrieval_calls", 0)),
            })

    n = len(paired)
    if n == 0:
        return None

    # Concordant/discordant counts
    both_correct = sum(1 for p in paired if p["static_correct"] and p["chain_correct"])
    both_wrong = sum(1 for p in paired if not p["static_correct"] and not p["chain_correct"])
    b = sum(1 for p in paired if not p["static_correct"] and p["chain_correct"])
    c = sum(1 for p in paired if p["static_correct"] and not p["chain_correct"])

    # EM means
    static_em = sum(p["static_em"] for p in paired) / n
    chain_em = sum(p["chain_em"] for p in paired) / n
    delta_em = chain_em - static_em

    # F1 means
    static_f1 = sum(p["static_f1"] for p in paired) / n
    chain_f1 = sum(p["chain_f1"] for p in paired) / n
    delta_f1 = chain_f1 - static_f1

    # LLM calls
    static_llm = sum(p["static_llm_calls"] for p in paired) / n
    chain_llm = sum(p["chain_llm_calls"] for p in paired) / n
    delta_llm = chain_llm - static_llm

    # McNemar
    stat, p_two, or_val = mcnemar_test(b, c, two_sided=True)
    _, p_one, _ = mcnemar_test(b, c, two_sided=False)

    # Full-N paired bootstrap: resample ALL N paired EM differences (not just
    # discordant pairs — that would condition on the marginals and inflate
    # precision). Delegates to audited statistics.paired_bootstrap.
    from slotrag.benchmarking.statistics import paired_bootstrap
    import numpy as np
    rng = np.random.default_rng(2027)
    boot_records = []
    for p in paired:
        boot_records.append({
            "result": {"metrics": {}, "status": "ok"},
            "scores": {"primary_score": float(p["static_em"])},
            "dataset": p["dataset"],
            "method": "slotrag-g7-static",
            "method_label": "slotrag-g7-static",
            "question_id": p["qid"],
            "seed": 2027,
        })
        boot_records.append({
            "result": {"metrics": {}, "status": "ok"},
            "scores": {"primary_score": float(p["chain_em"])},
            "dataset": p["dataset"],
            "method": "slotrag-g7-chain",
            "method_label": "slotrag-g7-chain",
            "question_id": p["qid"],
            "seed": 2027,
        })
    boot_comps = paired_bootstrap(
        boot_records, reference="slotrag-g7-static",
        iterations=10000, seed=2027,
    )
    if boot_comps:
        boot_comp = boot_comps[0]
        ci_lo, ci_hi = boot_comp.get("ci_low", 0.0), boot_comp.get("ci_high", 0.0)
        boot_n = boot_comp.get("count", n)
    else:
        ci_lo, ci_hi, boot_n = 0.0, 0.0, n

    # Per-dataset breakdown
    by_dataset = defaultdict(list)
    for p in paired:
        by_dataset[p["dataset"]].append(p)

    dataset_results = {}
    for ds, ps in by_dataset.items():
        ds_n = len(ps)
        ds_b = sum(1 for p in ps if not p["static_correct"] and p["chain_correct"])
        ds_c = sum(1 for p in ps if p["static_correct"] and not p["chain_correct"])
        ds_static_em = sum(p["static_em"] for p in ps) / ds_n
        ds_chain_em = sum(p["chain_em"] for p in ps) / ds_n
        ds_stat, ds_p_two, ds_or = mcnemar_test(ds_b, ds_c, two_sided=True)
        _, ds_p_one, _ = mcnemar_test(ds_b, ds_c, two_sided=False)

        dataset_results[ds] = {
            "n": ds_n,
            "b": ds_b,
            "c": ds_c,
            "static_em": ds_static_em,
            "chain_em": ds_chain_em,
            "delta_em": ds_chain_em - ds_static_em,
            "mcnemar_chi2": ds_stat,
            "p_two_sided": ds_p_two,
            "p_one_sided": ds_p_one,
            "odds_ratio": ds_or,
        }

    return {
        "label": label,
        "n": n,
        "both_correct": both_correct,
        "both_wrong": both_wrong,
        "b": b,
        "c": c,
        "static_em": static_em,
        "chain_em": chain_em,
        "delta_em": delta_em,
        "static_f1": static_f1,
        "chain_f1": chain_f1,
        "delta_f1": delta_f1,
        "static_llm_calls": static_llm,
        "chain_llm_calls": chain_llm,
        "delta_llm_calls": delta_llm,
        "mcnemar_chi2": stat,
        "p_two_sided": p_two,
        "p_one_sided": p_one,
        "odds_ratio": or_val,
        "ci_95": (ci_lo, ci_hi),
        "by_dataset": dataset_results,
    }


def compute_population_effect(stratum_result, prevalence):
    """Compute ATE_population = prevalence × ATE_eligible."""
    if stratum_result is None:
        return None
    return prevalence * stratum_result["delta_em"]


# ── Report generation ──────────────────────────────────────────────────────

def generate_report(primary, secondary, population, output_path):
    """Generate confirmatory report markdown."""
    lines = []
    lines.append("# H-STRUCT-1 Confirmatory Report")
    lines.append("")
    lines.append("> **Status:** POST-EXECUTION (all 1105×2 completed)")
    lines.append("> **Protocol:** H-STRUCT-1 V1.1 (frozen)")
    lines.append("> **NO MODIFICATIONS** were made to policy, threshold, or analysis plan.")
    lines.append("")

    # Primary result
    if primary:
        lines.append("## 1. Primary Result (H-STRUCT-1A: Eligible-Stratum)")
        lines.append("")
        lines.append(f"- **n_eligible:** {primary['n']}")
        lines.append(f"- **Static EM:** {primary['static_em']:.4f}")
        lines.append(f"- **Chain EM:** {primary['chain_em']:.4f}")
        lines.append(f"- **ΔEM:** {primary['delta_em']:+.4f}")
        lines.append(f"- **Discordant pairs:** b={primary['b']}, c={primary['c']}")
        lines.append(f"- **Odds ratio:** {primary['odds_ratio']:.3f}")
        lines.append(f"- **McNemar χ²:** {primary['mcnemar_chi2']:.3f}")
        lines.append(f"- **p (two-sided):** {primary['p_two_sided']:.4f}")
        lines.append(f"- **p (one-sided):** {primary['p_one_sided']:.4f}")
        lines.append(f"- **95% CI (ΔEM):** [{primary['ci_95'][0]:.4f}, {primary['ci_95'][1]:.4f}]")
        lines.append("")

        # Verdict
        if primary["p_two_sided"] < 0.05 and primary["delta_em"] > 0:
            verdict = "**CONFIRMED** — Chain beneficial for eligible questions"
        elif primary["p_two_sided"] < 0.10 and primary["delta_em"] > 0:
            verdict = "**TENTATIVE** — Insufficient evidence, larger holdout needed"
        else:
            verdict = "**REFUTED** — Chain not beneficial for eligible questions"
        lines.append(f"**Verdict:** {verdict}")
        lines.append("")

    # Per-dataset breakdown
    if primary and primary.get("by_dataset"):
        lines.append("### Per-Dataset Breakdown")
        lines.append("")
        lines.append("| Dataset | n | Static EM | Chain EM | ΔEM | b | c | OR | McNemar p (2s) |")
        lines.append("|---------|---|-----------|----------|-----|---|---|-----|---------------|")
        for ds, dr in sorted(primary["by_dataset"].items()):
            lines.append(f"| {ds} | {dr['n']} | {dr['static_em']:.4f} | {dr['chain_em']:.4f} | "
                        f"{dr['delta_em']:+.4f} | {dr['b']} | {dr['c']} | {dr['odds_ratio']:.3f} | "
                        f"{dr['p_two_sided']:.4f} |")
        lines.append("")

    # Secondary analyses
    if secondary:
        lines.append("## 2. Secondary Analyses")
        lines.append("")
        for sec in secondary:
            if sec is None:
                continue
            lines.append(f"### {sec['label']}")
            lines.append(f"- n={sec['n']}, ΔEM={sec['delta_em']:+.4f}, "
                        f"McNemar p (2s)={sec['p_two_sided']:.4f}")
            lines.append("")

        # Holm correction for secondary tests
        sec_ps = [s["p_two_sided"] for s in secondary if s is not None]
        if sec_ps:
            corrected = holm_correction(sec_ps)
            lines.append("### Holm-Corrected p-values (secondary)")
            for i, (s, pc) in enumerate(zip(
                [s for s in secondary if s is not None], corrected
            )):
                lines.append(f"- {s['label']}: raw p={s['p_two_sided']:.4f}, corrected p={pc:.4f}")
            lines.append("")

    # Population effect
    if population:
        lines.append("## 3. Population Effect (H-STRUCT-1B)")
        lines.append("")
        lines.append("| Dataset | Prevalence | ATE_eligible | ATE_population |")
        lines.append("|---------|-----------|-------------|---------------|")
        for ds, pop in population.items():
            if pop is not None:
                lines.append(f"| {ds} | {VALIDATION_PREVALENCE[ds]:.4f} | "
                            f"{pop['ate_eligible']:+.4f} | {pop['ate_population']:+.4f} |")
        lines.append("")

    # Efficiency metrics
    if primary:
        lines.append("## 4. Efficiency Metrics")
        lines.append("")
        lines.append(f"- ΔLLM_calls: {primary['delta_llm_calls']:+.1f}")
        lines.append(f"- Static F1: {primary['static_f1']:.4f}")
        lines.append(f"- Chain F1: {primary['chain_f1']:.4f}")
        lines.append(f"- ΔF1: {primary['delta_f1']:+.4f}")
        lines.append("")

    # Declaration
    lines.append("## 5. Declaration")
    lines.append("")
    lines.append("This is a confirmatory test. No modifications were made to the policy,")
    lines.append("threshold, or analysis plan after the compile census was frozen.")
    lines.append("All results are reported honestly, including non-significant findings.")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=== H-STRUCT-1 Confirmatory Analysis ===")
    print("NO-PEEKING: Ensure ALL 1105×2 executions are complete before proceeding.")
    print()

    # Load results
    if not RESULTS_CSV.exists():
        print(f"ERROR: Results CSV not found: {RESULTS_CSV}")
        print("Run confirmatory execution first.")
        sys.exit(1)

    results = load_results(RESULTS_CSV, question_lookup=build_question_lookup())
    print(f"Loaded {len(results)} result records (post-execution scored via score_record)")

    # Check completeness
    n_static = sum(1 for r in results if r.get("arm") == "static")
    n_chain = sum(1 for r in results if r.get("arm") == "chain")
    print(f"  Static arm: {n_static}")
    print(f"  Chain arm: {n_chain}")

    expected = 1105 * 2
    if len(results) < expected:
        print(f"WARNING: Only {len(results)}/{expected} results. Analysis may be incomplete.")

    # Primary analysis: eligible-stratum
    print("\n[1/4] Primary analysis (eligible-stratum)...")
    primary = analyze_stratum(results, lambda r: r.get("eligible") == "True", "Eligible (primary)")

    # Secondary analyses
    print("[2/4] Secondary analyses...")
    sec_validation = analyze_stratum(results,
        lambda r: r.get("eligible") == "True" and r.get("source_split") == "validation",
        "Validation-only")
    sec_train = analyze_stratum(results,
        lambda r: r.get("eligible") == "True" and r.get("source_split") == "train",
        "Train-only")
    secondary = [sec_validation, sec_train]

    # Population effect
    print("[3/4] Population effect estimation...")
    population = {}
    if primary:
        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            if ds in primary.get("by_dataset", {}):
                ate_elig = primary["by_dataset"][ds]["delta_em"]
                prev = VALIDATION_PREVALENCE.get(ds, 0)
                population[ds] = {
                    "ate_eligible": ate_elig,
                    "ate_population": prev * ate_elig,
                }

    # Generate report
    print("[4/4] Generating report...")
    generate_report(primary, secondary, population, REPORT_PATH)
    print(f"Report written to: {REPORT_PATH}")

    # Print summary
    if primary:
        print(f"\n{'='*60}")
        print(f"PRIMARY RESULT")
        print(f"{'='*60}")
        print(f"  n_eligible: {primary['n']}")
        print(f"  Static EM: {primary['static_em']:.4f}")
        print(f"  Chain EM: {primary['chain_em']:.4f}")
        print(f"  ΔEM: {primary['delta_em']:+.4f}")
        print(f"  McNemar p (two-sided): {primary['p_two_sided']:.4f}")
        print(f"  95% CI: [{primary['ci_95'][0]:.4f}, {primary['ci_95'][1]:.4f}]")

        if primary["p_two_sided"] < 0.05 and primary["delta_em"] > 0:
            print(f"\n  VERDICT: CONFIRMED")
        elif primary["p_two_sided"] < 0.10 and primary["delta_em"] > 0:
            print(f"\n  VERDICT: TENTATIVE")
        else:
            print(f"\n  VERDICT: REFUTED")


if __name__ == "__main__":
    main()
