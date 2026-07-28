"""Provider-free compile smoke for v74 evidence bundle methods.

Verifies that the two new methods (``slotrag-evidence-bundle`` and
``slotrag-per-path-extraction``) can be instantiated, compile a plan, and
produce extraction results through the ``EvidenceBundleExtractor`` dispatch
without any provider calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from slotrag.benchmarking.methods import METHODS
from slotrag.evidence_bundle import PerPathExtractor, UnionExtractor
from slotrag.models import Passage, RetrievalResult, Slot
from slotrag.planner import SlotCompiler, SlotMaterializer
from slotrag.providers import ChatResult, ToolCall, Usage


def _make_client(plan_args: list[dict], rows: list[list[dict]]):
    """Build a sequential fake client that returns canned plan+extraction."""
    plan_iter = iter(plan_args)
    row_iter = iter(rows)

    class FakeClient:
        def complete(self, messages, **kwargs):
            nonlocal plan_iter, row_iter
            # Detect whether this is a plan or extraction call
            if "tools" in kwargs:
                tool_name = kwargs["tools"][0]["function"]["name"]
                if tool_name == "emit_slot_plan":
                    args = next(plan_iter)
                else:
                    args = {"rows": next(row_iter)}
            else:
                args = {}
            return ChatResult(
                tool_calls=[ToolCall(name=tool_name, arguments=args)],
                usage=Usage(prompt_tokens=5, completion_tokens=3),
            )

        @staticmethod
        def require_tool(result, name):
            for call in result.tool_calls:
                if call.name == name:
                    return call.arguments
            raise ValueError(f"tool {name} not found")

    return FakeClient()


def _make_batch_retriever(passage_a: Passage, passage_b: Passage):
    class BatchRetriever:
        def search_batch(self, queries, *, top_k=None, sparse_access_modes=None):
            return [
                [RetrievalResult(passage=passage_a, score=0.9)],
                [RetrievalResult(passage=passage_b, score=0.8)],
            ]
    return BatchRetriever()


def _make_plan_args():
    for plan in [
        {
            "slots": [
                {
                    "id": "S1",
                    "predicate": "Founded",
                    "arguments": ["?company", "?founder"],
                    "estimated_cardinality": 5,
                    "estimated_cost": 1.0,
                }
            ],
            "joins": [],
            "outputs": ["?company"],
        },
    ]:
        yield plan


def main() -> int:
    output = Path("runs/slotrag-evidence-bundle-smoke-v74")
    output.mkdir(parents=True, exist_ok=True)

    passage_a = Passage(id="pA", doc_id="dA", text="Ada founded Acme Corp in 2005.")
    passage_b = Passage(id="pB", doc_id="dB", text="Brett founded Beta Inc in 2010.")

    slots = [
        Slot(id="S1", predicate="Founded", arguments=["?company", "?founder"]),
    ]

    results: dict[str, dict] = {}

    for method_key in ["slotrag-evidence-bundle", "slotrag-per-path-extraction"]:
        spec = METHODS[method_key]
        print(f"\n=== {method_key} ===")
        print(f"  evidence_bundle={spec.evidence_bundle}, per_path_extraction={spec.per_path_extraction}")

        # PerPathExtractor makes N LLM calls per path; provide enough responses.
        extraction_rows = [
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
        ]
        if spec.per_path_extraction:
            # One response per path (2 paths → 2 responses)
            extraction_rows.append(
                [{"company": "Beta Inc", "founder": "Brett", "source_id": "pB"}],
            )
        client = _make_client(
            list(_make_plan_args()),
            extraction_rows,
        )
        retriever = _make_batch_retriever(passage_a, passage_b)

        extractor = (
            PerPathExtractor() if spec.per_path_extraction else UnionExtractor()
        )
        materializer = SlotMaterializer(
            client, retriever,
            max_passages=5,
            question_context="Who founded companies?",
            dual_access_bundle=True,
            evidence_bundle_extractor=extractor,
        )

        rows, metrics = materializer.materialize(slots[0], {})

        result = {
            "method": method_key,
            "row_count": len(rows),
            "bindings": [dict(r.bindings) for r in rows],
            "source_ids": [r.source_id for r in rows],
            "extraction_bundles": metrics.extraction_bundles,
            "per_path_extractions": metrics.per_path_extractions,
            "per_path_extraction_paths": metrics.per_path_extraction_paths,
            "extracted_rows_before_dedup": metrics.extracted_rows_before_dedup,
            "extracted_rows_after_dedup": metrics.extracted_rows_after_dedup,
            "provider_calls": metrics.llm_calls,
        }
        results[method_key] = result

        print(f"  rows={len(rows)}, extraction_bundles={metrics.extraction_bundles}")
        print(f"  per_path_extractions={metrics.per_path_extractions}, paths={metrics.per_path_extraction_paths}")
        print(f"  bindings={[dict(r.bindings) for r in rows]}")

    summary = {
        "schema_version": 1,
        "provider_calls": 0,
        "method_count": len(results),
        "results": results,
    }

    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSummary written to {summary_path}")

    ok = all(r["row_count"] > 0 for r in results.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
