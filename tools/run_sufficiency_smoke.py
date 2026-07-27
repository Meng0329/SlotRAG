"""Run a deterministic provider-free sufficiency calibration smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slotrag.models import BindingRow, Passage, RetrievalResult
from slotrag.sufficiency import EvidenceContext, SufficiencyExample
from tools.calibrate_evidence_sufficiency import run_calibration


def _example(index: int, sufficient: bool) -> SufficiencyExample:
    if sufficient:
        score = 0.90 - (index % 3) * 0.04
        text = "Ada founded OpenAI in 2015."
        predicate = "Founded"
        rows = [BindingRow(
            slot_id="S1",
            bindings={"company": "OpenAI"},
            source_id=f"p{index}",
            source_span=text,
            confidence=0.90,
        )]
        depth = index % 2
    else:
        score = 0.12 + (index % 3) * 0.03
        text = "A disconnected passage about another organization."
        predicate = "Founded"
        rows = []
        depth = 2 + index % 2
    passage = Passage(id=f"p{index}", doc_id=f"d{index % 4}", text=text)
    return SufficiencyExample(
        example_id=f"smoke-{index:02d}",
        label=int(sufficient),
        context=EvidenceContext(
            retrieval_results=[RetrievalResult(
                passage=passage,
                score=score,
                bm25_score=score,
                dense_score=score,
                rerank_score=score,
            )],
            predicate=predicate,
            requested_variables=["company"],
            extracted_rows=rows,
            remaining_plan_depth=depth,
            retrieval_calls_used=1,
            retrieval_budget=3,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    input_path = args.output_dir / "examples.jsonl"
    examples = [_example(index, index % 2 == 0) for index in range(20)]
    input_path.write_text(
        "".join(json.dumps(example.model_dump(mode="json"), ensure_ascii=False) + "\n" for example in examples),
        encoding="utf-8",
    )
    summary = run_calibration(input_path, args.output_dir, calibration_fraction=0.25, bins=5)
    if summary["provider_calls"] != 0:
        raise RuntimeError("sufficiency smoke unexpectedly called a provider")
    if summary["calibration"]["example_count"] != 5:
        raise RuntimeError(f"unexpected calibration split: {summary}")
    if summary["calibration"]["binary_precision"] < 0.5 or summary["calibration"]["binary_recall"] < 0.5:
        raise RuntimeError(f"calibration smoke failed to separate labels: {summary}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
