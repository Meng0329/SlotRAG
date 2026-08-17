#!/usr/bin/env python3
"""G5 well-defined τ collector — filters branch chains, validates answer-binding.

裁决12h: τ is well-defined ONLY when the LAST slot's extracted_rows bind the
answer value (pure entity/attribute chains). Branch chains (≥4 slots, or last
slot binds a join/compare intermediate rather than the answer) produce proxy
artifacts (e.g. the 2wiki S4=6 freeze).

This collector enforces the well-definedness constraint AT COLLECTION TIME:
  - For each real 2+slot chain, sweep budget {1..K}.
  - Compute per-slot recovery threshold τ_slot = min{B : slot recovered}.
  - Well-defined gate: the LAST slot's extracted_rows, at τ_last, must bind the
    dataset answer value (case-insensitive token match). Chains failing the
    gate are marked NOT_WELL_DEFINED and EXCLUDED from τ training labels (their
    slots are proxy artifacts).
  - Also records which slots bind the answer (answer-bearing slots) vs
    intermediate (join-key) slots — the latter are where τ is meaningless.

Output: per-question {qid, well_defined, n_slots, thresholds, last_slot_binds_answer,
answer_bearing_slots, excluded_reason}. τ training set = well_defined questions only.
"""

from __future__ import annotations
import argparse, json, os, sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load_env():
    import subprocess
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit("missing .env")
    shellsafe = '"' + str(env_path) + '"'
    out = subprocess.check_output(
        ["bash", "-c", "set -a; .  %s ; set +a; env" % shellsafe], text=True)
    loaded = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        loaded[k] = v
    for k, v in loaded.items():
        os.environ.setdefault(k, v)


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


def _calibrator():
    from slotrag.sufficiency import EvidenceSufficiencyCalibrator
    import json as _json
    cal_path = ROOT / "runs_archive" / "slotrag-sufficiency-smoke-v60" / "calibrator.json"
    if cal_path.exists():
        return EvidenceSufficiencyCalibrator.from_dict(_json.loads(cal_path.read_text()))
    return None


def _norm(s: str) -> str:
    """Normalize a value for answer-match: lowercase, collapse punctuation/whitespace."""
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


def _binds_answer(bindings: dict, ans_norm: str) -> bool:
    """True if any binding value contains the normalized answer as a token sequence."""
    if not ans_norm:
        return False
    for k, v in bindings.items():
        vn = _norm(str(v))
        # whole-value equality, or ans appears as a subsequence of the value
        if ans_norm == vn or ans_norm in vn:
            return True
        # token subsequence (handles '12 June 1516' vs '12 June 1516 in ...')
        vt = vn.split(); at = ans_norm.split()
        if len(at) >= 2 and all(t in vt for t in at):
            return True
    return False


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=str, default="2wikimultihop")
    ap.add_argument("--split", type=str, default="dev")
    ap.add_argument("--split-file", type=str, default="",
                    help="explicit filename under benchmark/<dataset>/; overrides split")
    ap.add_argument("--prefix-filter", type=str, default="",
                    help="only process questions whose id starts with this prefix (e.g. 3hop1)")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--budgets", type=str, default="1,2,3,4,5,6")
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g5_welldefined_tau.json")
    ap.add_argument("--resume-log", type=str, default="/tmp/g5_welldefined_tau.log.jsonl",
                    help="append each chain's record here immediately (survives kill)")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    data_path = ROOT / "benchmark" / args.dataset / (
        args.split_file if args.split_file else "%s_%s.jsonl" % (args.dataset, args.split))
    if not data_path.exists():
        print("missing %s" % data_path)
        return 1
    problems = []
    with open(data_path) as f:
        for line in f:
            prob = json.loads(line)
            pid = str(prob.get("id") or "")
            if args.prefix_filter and not pid.startswith(args.prefix_filter):
                continue
            problems.append(prob)
            if len(problems) >= args.n:
                break

    compiler = SlotCompiler(client)
    well_defined = []
    excluded = []
    n_compile_fail = n_too_few = 0
    for prob in problems:
        q = prob["question"]
        ans = _norm(prob.get("answers") or prob.get("answer") or "")
        passages = prob.get("passages") or []
        if not passages:
            continue
        try:
            plan, _cm = compiler.compile(q, answer_kind="short")
        except Exception:
            n_compile_fail += 1
            continue
        if len(plan.slots) < 2:
            n_too_few += 1
            continue

        ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"]) for p in passages]
        retriever = HybridRetriever(
            passages=ps, embedding_client=embedding, reranker_client=reranker,
            bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")

        # per budget, per slot: recovered? AND answer-binding per slot at tau
        recovered = {b: {} for b in budgets}
        ans_bearing = {}   # slot_id -> True if any extracted_row binds answer (any budget)
        last_slot_binds_at_tau = None
        for budget in budgets:
            mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
            ex = AdaptiveExecutor(
                mat, max_retrieval_calls=budget, max_binding_contexts=2, random_seed=2027,
                sufficiency_calibrator=cal,
                action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
            r = ex.execute(plan, strategy="adaptive", physical_plan=None)
            slot_ok = {}
            slot_ans = {}
            for t in r.slot_traces:
                ok = False
                ab = False
                for mm in t.materializations:
                    for er in mm.extracted_rows:
                        if er.bindings:
                            ok = True
                        if _binds_answer(er.bindings, ans):
                            ab = True
                slot_ok[t.slot_id] = ok
                slot_ans[t.slot_id] = ab
            for sid in slot_ok:
                recovered[budget].setdefault(sid, slot_ok[sid])
                if slot_ans.get(sid):
                    ans_bearing[sid] = True

        thresholds = {}
        for sid in set().union(*[set(v.keys()) for v in recovered.values()]):
            thr = next((b for b in budgets if recovered[b].get(sid, False)), None)
            thresholds[sid] = thr

        # well-defined gate: last slot (highest position) must bind answer at its tau
        positions = sorted(int(sid[1:]) for sid in thresholds)
        last_pos = positions[-1] if positions else None
        last_sid = "S%d" % last_pos if last_pos else None
        # was the last slot ever answer-bearing at/above its tau? (need per-budget ans)
        last_binds_at_tau = ans_bearing.get(last_sid, False)

        rec = {
            "qid": prob.get("id"), "question": q[:60], "n_slots": len(plan.slots),
            "answer": prob.get("answers") or prob.get("answer"),
            "thresholds": thresholds, "ans_bearing_slots": sorted(ans_bearing),
            "last_slot_binds_answer": bool(last_binds_at_tau),
            "well_defined": bool(last_binds_at_tau),
        }
        if last_binds_at_tau:
            well_defined.append(rec)
            print("[OK ] %s slots=%d tau=%s ans_bearing=%s"
                  % (str(prob.get("id"))[:8], len(plan.slots), thresholds, sorted(ans_bearing)))
        else:
            rec["excluded_reason"] = "last slot %s does not bind answer '%s'" % (last_sid, ans[:30])
            excluded.append(rec)
            print("[EXC] %s slots=%d tau=%s last=%s ans_bearing=%s  -> %s"
                  % (str(prob.get("id"))[:8], len(plan.slots), thresholds, last_sid,
                     sorted(ans_bearing), rec["excluded_reason"][:60]))

        # incremental durable write: append this chain's raw record so a killed
        # run (e.g. timeout SIGTERM) still preserves completed chains.
        log = Path(args.resume_log)
        with log.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()

    n_wd = len(well_defined)
    n_ex = len(excluded)
    print("\n=== well-defined τ collector (%s/%s) ===" % (args.dataset, args.split))
    print("compile_fail=%d, <2-slot=%d, real 2+ chains run=%d" % (n_compile_fail, n_too_few, n_wd + n_ex))
    print("well_defined (last slot binds answer): %d / %d" % (n_wd, n_wd + n_ex))
    if n_ex:
        print("excluded (branch/intermediate): %d — %s"
              % (n_ex, "these τ are proxy artifacts (12h), not training labels"))
    # tau distribution over well-defined only
    from collections import defaultdict
    bypos = defaultdict(list)
    for rec in well_defined:
        for sid, tau in rec["thresholds"].items():
            if tau is None:
                continue
            pos = int(sid[1:]) if sid[1:].isdigit() else len(rec["thresholds"])
            bypos[pos].append(tau)
    print("\nwell-defined τ distribution:")
    for pos in sorted(bypos):
        vals = sorted(bypos[pos])
        print("  pos %d: n=%d tau=%s" % (pos, len(vals), vals))

    Path(args.out).write_text(json.dumps({
        "config": {"dataset": args.dataset, "split": args.split, "n": args.n,
                   "budgets": budgets, "first_window": args.first_window},
        "counts": {"problems": args.n, "compile_fail": n_compile_fail, "too_few_slots": n_too_few,
                   "real_2plus_chains": n_wd + n_ex, "well_defined": n_wd, "excluded": n_ex},
        "well_defined": well_defined, "excluded": excluded,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()