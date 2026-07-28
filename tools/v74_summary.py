"""Print compact comparison table for v74 smoke results."""
import json

d = json.load(open("runs/slotrag-evidence-bundle-smoke-v74/summaries/qo_evidence_bundle_global_dev_v74_smoke/summary.json"))
print("%-8s %-28s %7s %7s %7s %6s %7s %8s %5s" % ("Dataset", "Method", "Primary", "EM", "R@5", "Calls", "Tokens", "Wall ms", "OK%"))
print("-" * 85)
for s in d["summary"]:
    if not s["count"]:
        continue
    toks = s["prompt_tokens"] + s["completion_tokens"]
    print("%-8s %-28s %7.4f %7.4f %7.4f %6.1f %7.0f %8.1f %5.0f%%" % (
        s["dataset"][:8], s["method"][:28],
        s["primary_score"], s["em"], s["evidence_recall_at_5"],
        s["llm_calls"], toks, s["wall_latency_ms"], s["success_rate"] * 100,
    ))

# Per-path extraction telemetry
print("\n--- Bundle telemetry (per-path-extraction) ---")
for s in d["summary"]:
    if "per-path" in s["method"]:
        print("%-8s %-28s bundles=%d per_path=%d paths=%d before_dedup=%d after_dedup=%d" % (
            s["dataset"][:8], s["method"][:28],
            s.get("extraction_bundles", 0),
            s.get("per_path_extractions", 0),
            s.get("per_path_extraction_paths", 0),
            s.get("extracted_rows_before_dedup", 0),
            s.get("extracted_rows_after_dedup", 0),
        ))
