#!/usr/bin/env python3
"""G9 heterogeneous evidence smoke — text + table cells through the SlotRAG architecture.

证明: 至少 text+table/structured evidence 真实端到端执行，无需重写核心 architecture。

Design:
  - A small frozen corpus of Wikipedia-style text passages AND table-row passages,
    built to match a FEVEROUS SUPPORTS claim about "Aramais Yepiskoposyan played
    for FC Ararat Yerevan during 1986 to 1991."
  - Table rows are formatted as "Page | Section | Header1: value1 | Header2: value2"
    (text representation of structured evidence).
  - Evidence metadata carries table structure (headers, row index) so the extractor
    can bind slot variables to specific cells.
  - The adapter converts FEVEROUS evidence references (cell_R_C, sentence_N) into
    Passage objects — the materializer sees plain text, the architecture unchanged.

Honest boundary: this is a transfer proof, not a Wikipedia-scale retrieval benchmark.
The corpus is hand-built (like G3/G8 smoke); the claim is that heterogeneous evidence
runs through the same evidence program without architecture changes.
"""

from __future__ import annotations
import argparse, json, os, sys, time
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
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k, v)


# ---------------------------------------------------------------------------
# Frozen corpus: hand-built text + table-row passages.
#
# Claim (from FEVEROUS id 13969):
#   "Aramais Yepiskoposyan played for FC Ararat Yerevan, an Armenian football
#    club based in Yerevan during 1986 to 1991."  — label: SUPPORTS
#
# Evidence types represented:
#   1. Text passages (sentence_N): ordinary Wikipedia text
#   2. Table-row passages (cell_R_C): structured evidence formatted with headers
#   3. Mixed: a text passage alongside a table row about the same entity
# ---------------------------------------------------------------------------

CORPUS = [
    # --- text passages (equivalent to sentence_N references) ---
    {
        "id": "arar-ay-0",
        "text": "Aramais Yepiskoposyan is an Armenian football player born in 1960.",
        "doc_id": "Aramais Yepiskoposyan",
        "metadata": {"type": "text", "source": "sentence"},
    },
    # --- table-row passages (equivalent to cell_R_C references) ---
    # Table: "Career statistics" on the Aramais Yepiskoposyan Wikipedia page.
    # row=1: played for FC Ararat Yerevan, 1986-1991, Armenia.
    {
        "id": "arar-ay-cell-0-6-1",
        "text": (
            "Career statistics | "
            "Club: FC Ararat Yerevan | "
            "Country: Armenia | "
            "Years: 1986-1991 | "
            "Apps: 142 | "
            "Goals: 18"
        ),
        "doc_id": "Aramais Yepiskoposyan",
        "metadata": {
            "type": "table_row",
            "page": "Aramais Yepiskoposyan",
            "section": "Career statistics",
            "row_index": 1,
            "headers": ["Club", "Country", "Years", "Apps", "Goals"],
        },
    },
    # --- text passage about the club ---
    {
        "id": "arar-fc-0",
        "text": (
            "FC Ararat Yerevan is an Armenian football club based in Yerevan. "
            "It competes in the Armenian Premier League and was founded in 1935."
        ),
        "doc_id": "FC Ararat Yerevan",
        "metadata": {"type": "text", "source": "sentence"},
    },
    # --- additional table row: club's other players for diversity ---
    {
        "id": "arar-fc-cell-2-1",
        "text": (
            "Honours | "
            "Competition: Armenian Premier League | "
            "Title: Champions | "
            "Years: 1993, 1994, 1995, 1996"
        ),
        "doc_id": "FC Ararat Yerevan",
        "metadata": {
            "type": "table_row",
            "page": "FC Ararat Yerevan",
            "section": "Honours",
            "row_index": 1,
            "headers": ["Competition", "Title", "Years"],
        },
    },
    # --- distractor: unrelated text passage ---
    {
        "id": "distractor-1",
        "text": (
            "Yerevan is the capital and largest city of Armenia, with a population "
            "of approximately 1.07 million people."
        ),
        "doc_id": "Yerevan",
        "metadata": {"type": "text", "source": "distractor"},
    },
]

CLAIMS = [
    {
        "id": "g9-feverous-13969",
        "claim": (
            "Aramais Yepiskoposyan played for FC Ararat Yerevan, "
            "an Armenian football club based in Yerevan during 1986 to 1991."
        ),
        "gold_bool": "True",  # SUPPORTS
        "label": "SUPPORTS",
    },
    {
        "id": "g9-feverous-refutes",
        "claim": (
            "Aramais Yepiskoposyan played for FC Ararat Yerevan, "
            "an Armenian football club based in Yerevan during 1995 to 2001."
        ),
        "gold_bool": "False",  # REFUTES (table row says 1986-1991, not 1995-2001)
        "label": "REFUTES",
    },
]
CORPUS_DOC = (
    "The same frozen corpus serves both claims. The SUPPORTS claim matches the "
    "table row (FC Ararat Yerevan, 1986-1991). The REFUTES claim states 1995-2001, "
    "which the table row contradicts — the model must reject it using the same "
    "table evidence."
)


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser(description="G9 FEVEROUS heterogeneous evidence smoke")
    ap.add_argument("--budget", type=int, default=6,
                    help="Matched retrieval budget (same as G7/G8)")
    ap.add_argument("--out", type=str, default="/tmp/g9_feverous_smoke_result.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    from slotrag.models import Passage, QuestionRecord
    from slotrag.retrieval import HybridRetriever
    from slotrag.benchmarking.methods import METHODS, compile_slotrag_plan, run_method

    cfg = load_config(ROOT / "configs" / "default.yaml")
    agnes, embedding, reranker = provider_clients(cfg)

    # Build passages from frozen corpus
    ps = [
        Passage(id=p["id"], text=p["text"], doc_id=p["doc_id"], metadata=p["metadata"])
        for p in CORPUS
    ]

    ARMS = ["slotrag-hover"]
    assert all(m in METHODS for m in ARMS)

    results = {}
    for claim_spec in CLAIMS:
        cid = claim_spec["id"]
        claim = claim_spec["claim"]
        gold_bool = claim_spec["gold_bool"]
        label = claim_spec["label"]

        q = QuestionRecord(
            id=cid,
            question=claim,
            answers=[gold_bool],
            passages=ps,
            metadata={"feverous_label": label, "num_hops": 2,
                       "evidence_types": ["text", "table_row"],
                       "corpus_size": len(ps)},
        )

        retriever = HybridRetriever(
            passages=ps, embedding_client=embedding, reranker_client=reranker,
            bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body",
        )

        plan, cm = compile_slotrag_plan(METHODS["slotrag-hover"], "hover", q, agnes)
        n_slots = len(plan.slots)
        print("\n=== %s (%s) ===" % (cid, label), flush=True)
        print("  claim: %s" % claim[:100], flush=True)
        print("  gold:  %s" % gold_bool, flush=True)
        print("  corpus: %d passages (text=%d, table_row=%d)" % (
            len(ps),
            sum(1 for p in ps if p.metadata.get("type") == "text"),
            sum(1 for p in ps if p.metadata.get("type") == "table_row"),
        ), flush=True)
        print("  plan: %d slots = %s" % (n_slots, [s.id for s in plan.slots]), flush=True)

        per_claim = {}
        for m in ARMS:
            t0 = time.perf_counter()
            try:
                r = run_method(
                    m, dataset="hover", question=q, retriever=retriever,
                    client=agnes, config=cfg, seed=2027,
                    max_steps=4, max_retrieval_calls=args.budget,
                    frozen_plan=plan,
                )
            except Exception as exc:
                per_claim[m] = {"error": str(exc)[:200]}
                print("  %s: ERROR %s" % (m, str(exc)[:100]))
                continue
            elapsed = time.perf_counter() - t0
            ans = r.answer
            em = int(str(ans).strip().lower() == gold_bool.lower())
            calls = r.metrics.retrieval_calls if r.metrics else 0
            per_claim[m] = {
                "answer": ans, "em": em, "calls": calls,
                "n_rows": len(r.rows), "status": r.status,
                "elapsed_s": round(elapsed, 1),
                "evidence_ids": sorted(e.source_id for e in r.evidence) if r.evidence else [],
            }
            print("  %-22s calls=%d em=%d ans=%-6s rows=%d elapsed=%.1fs" % (
                m, calls, em, ans, len(r.rows), elapsed), flush=True)
            print("  evidence: %s" % sorted(e.source_id for e in r.evidence), flush=True)
            print("  rows: %s" % [row for row in r.rows[:3]], flush=True)
        results[cid] = per_claim

    Path(args.out).write_text(json.dumps({
        "n_corpus": len(ps),
        "corpus_types": {
            "text": sum(1 for p in ps if p.metadata.get("type") == "text"),
            "table_row": sum(1 for p in ps if p.metadata.get("type") == "table_row"),
        },
        "claims": results,
    }, ensure_ascii=False, indent=2, default=str))
    print("\nWrote %s" % args.out, flush=True)


if __name__ == "__main__":
    main()
