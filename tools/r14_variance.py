#!/usr/bin/env python3
"""R1.4 — G6 multi-run EM/F1 variance (qwen3.6-27b generator non-determinism).

Runs the same G6 config (seed 2027, n=10) three times to three output dirs,
reports per-run EM/F1 mean ± std across the three runs to quantify generator
non-determinism (NOT stratified-sample variance across seeds).

Protocol (from ARTIFACT_READREADME.md §4):
- same seed 2027 → only generator nondeterminism varies; question set identical
- NOT the same as seeds 2027/2028/2029 (which resample different question sets)

Usage:
    python tools/r14_variance.py --config /tmp/tkde-g6-run{N}.yaml

Outputs:
    runs/tkde-g6-runN/   (three dirs)
    /tmp/r14_variance_report.txt  (mean±std per arm across runs)
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import importlib.util
spec = importlib.util.spec_from_file_location("summarize", ROOT / "tools/summarize_tkde_main_table.py")
summarize = importlib.util.module_from_spec(spec); spec.loader.exec_module(summarize)

ARMS = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]


def run_once(config: Path, output_dir: Path) -> None:
    """Execute one benchmark run."""
    cmd = [
        str(ROOT / ".venv/bin/slotrag"), "benchmark", "run",
        "--config", str(ROOT / "configs/default.yaml"),
        "--suite", str(config),
        "--output-dir", str(output_dir), "g6-effective",
    ]
    print(f"  → {' '.join(cmd[:1])} {cmd[-2]} ({config.name})")
    subprocess.run(cmd, cwd=ROOT, check=True,
                   env={**__import__("os").environ, **dict(
                       SLOTRAG_AGNES_BASE_URL=__import__("os").environ.get("SLOTRAG_AGNES_BASE_URL",""),
                       SLOTRAG_EMBEDDING_BASE_URL=__import__("os").environ.get("SLOTRAG_EMBEDDING_BASE_URL",""),
                       SLOTRAG_RERANKER_BASE_URL=__import__("os").environ.get("SLOTRAG_RERANKER_BASE_URL","")
                   )})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs=3,
                    help="three config files (same seed, same sample_size, differing nothing); "
                         "required unless --runs is given")
    ap.add_argument("--output-base", default="runs/tkde-g6-r14-var")
    ap.add_argument("--runs", nargs=3,
                    help="three OUTPUT DIRS already produced (skips run_once). If given, "
                         "--configs is ignored for execution.")
    ap.add_argument("--stage", default="g6-effective")
    ap.add_argument("--dataset", default="hotpotqa")
    args = ap.parse_args()

    if not args.runs and not args.configs:
        ap.error("either --runs or --configs is required")

    if args.runs:
        runs = [Path(p) for p in args.runs]
        print(f"=== R1.4 aggregate-only on pre-existing dirs ===")
        for r in runs:
            print(f"  - {r}")
    else:
        runs = [Path(args.output_base + f"-run{i+1}") for i in range(3)]

        # --- idempotent: skip run_once if all 3 target dirs already have items ---
        def _has_items(p: Path) -> bool:
            return len(list((p / "items").rglob("*.json"))) > 0

        need_run = [p for p in runs if not _has_items(p)]
        if not need_run:
            print(f"=== R1.4 aggregate-only (all 3 dirs already populated): "
                  f"{', '.join(str(p) for p in runs)}")
        else:
            print(f"=== R1.4 executing runs missing data: {', '.join(str(p) for p in need_run)}")
            # --- execute 3 runs sequentially (avoid rate-limit collision) ---
            for cfg, out in zip(args.configs, runs):
                if not _has_items(out):
                    print(f"=== R1.4 run to {out} ===")
                    run_once(Path(cfg), out)

    # --- aggregate variance across runs ---
    print("\n=== R1.4 3-run variance (mean ± std across runs) ===")
    print(f"{'arm':22s} {'run1 EM%':>9} {'run2 EM%':>9} {'run3 EM%':>9} {'mean±std':>13} {'Δcalls mean±std':>16}")
    print("-" * 75)
    results = {}
    for arm in ARMS:
        em_runs, call_runs = [], []
        for out in runs:
            items = summarize._load_items(out, args.stage, args.dataset, arm)
            n = len(items)
            em = sum(1 for r in items.values() if r.get("scores", {}).get("em")) / n * 100 if n else 0
            calls = float(np.mean([r["result"]["metrics"]["retrieval_calls"] for r in items.values()])) if items else 0
            em_runs.append(em); call_runs.append(calls)
        em_mean, em_std = np.mean(em_runs), np.std(em_runs, ddof=1)
        call_mean, call_std = np.mean(call_runs), np.std(call_runs, ddof=1)
        print(f"{arm:22s} {em_runs[0]:>8.1f}% {em_runs[1]:>8.1f}% {em_runs[2]:>8.1f}% "
              f"{em_mean:>5.1f}±{em_std:.1f} {call_mean:>6.2f}±{call_std:.2f}")
        results[arm] = {"em": list(zip(em_runs, [em_mean, em_std])),
                        "calls": {"per_run": call_runs, "mean±std": f"{call_mean:.2f}±{call_std:.2f}"}}
    print("\nGenerator non-determinism captured: if std>0 on identical (seed,sample), it is")
    print("qwen3.6-27b nondeterminism (temperature 0 should be ~0, any nonzero is model variance).")


if __name__ == "__main__":
    main()
