#!/usr/bin/env python3
"""G5 deep-chain probe — can SlotCompiler produce ≥3-slot chains on musique 3-hop?

裁决 12o: the benefit domain (≥3-slot chains) is RARE in standard 2-hop benchmarks.
The ONLY honest path to show G3's broad value is deep-chain load. Musique TRAIN
has real 3-hop (3hop1=3737, 3hop2=650) and 4-hop (4hop1/2/3≈1175) questions.

This probe answers the GATE question: does SlotCompiler.compile() turn these
3-hop questions into ≥3-slot plans? And of those, how many are well-defined
(末槽绑答案值)? Without compiler support for depth, synthetic deep chains are
the fallback; with it, real musique 3-hop is a natural deep-chain testbed.

LOW-cost: compile-only, no retrieval/execution. ~10-30 qwen compile calls.
"""
from __future__ import annotations
import argparse, json, os, sys
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


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="musique", help="dataset dir under benchmark/")
    ap.add_argument("--split-file", default="musique_train.jsonl")
    ap.add_argument("--n", type=int, default=15, help="questions to compile")
    ap.add_argument("--prefix-filter", default="3hop", help="id prefix filter, '' = all")
    ap.add_argument("--out", default="/tmp/g5_deepchain_compile.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler
    from collections import Counter

    _cfg, (client, *_rest) = _providers()
    compiler = SlotCompiler(client)

    data_path = ROOT / "benchmark" / args.dataset / args.split_file
    if not data_path.exists():
        print("missing %s" % data_path)
        return 1

    counts = Counter(); by_slots = Counter()
    rows = []
    n_seen = 0; n_done = 0
    with open(data_path) as f:
        for line in f:
            prob = json.loads(line)
            pid = str(prob.get("id") or "")
            if args.prefix_filter and not pid.startswith(args.prefix_filter):
                continue
            n_seen += 1
            if n_seen > args.n * 3:  # safety: don't scan forever
                break
            q = prob.get("question", "")
            try:
                plan, _cm = compiler.compile(q, answer_kind="short")
                n_slots = len(plan.slots)
                by_slots[n_slots] += 1
                counts["compiled"] += 1
                joins = len(getattr(plan, "joins", []) or [])
                rows.append({"id": pid, "n_slots": n_slots, "n_joins": joins,
                             "slots": [s.predicate for s in plan.slots], "question": q[:70]})
                print("[OK ] %s slots=%d joins=%d %s" % (pid[:20], n_slots, joins, q[:60]))
            except Exception as e:
                counts["compile_fail"] += 1
                print("[ERR] %s %s" % (pid[:20], str(e)[:50]))
            n_done += 1
            if n_done >= args.n:
                break

    print("\n=== deep-chain compile probe (%s %s, filter=%r) ==="
          % (args.dataset, args.split_file, args.prefix_filter))
    print("seen=%d compiled=%d compile_fail=%d  slot-dist=%s"
          % (n_seen, counts["compiled"], counts["compile_fail"], dict(sorted(by_slots.items()))))
    ge3 = [r for r in rows if r["n_slots"] >= 3]
    print("≥3-slot chains: %d / %d" % (len(ge3), len(rows)))
    for r in ge3:
        print("  [GE3] %s slots=%d joins=%d  slots=%s" % (r["id"][:20], r["n_slots"], r["n_joins"], r["slots"]))

    Path(args.out).write_text(json.dumps(
        {"config": {"dataset": args.dataset, "split": args.split_file, "n": args.n,
                    "prefix_filter": args.prefix_filter},
         "counts": dict(counts), "slot_dist": dict(sorted(by_slots.items())),
         "n_ge3": len(ge3), "rows": rows}, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


if __name__ == "__main__":
    main()