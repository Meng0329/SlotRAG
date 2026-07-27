import json

import pytest

from slotrag.models import BindingRow, Passage, RetrievalResult
from slotrag.sufficiency import EvidenceContext, SufficiencyExample
from tools.analyze_sufficiency_feature_ablation import analyze_feature_ablation


def test_feature_ablation_selects_only_on_grouped_fit_questions(tmp_path):
    rows = []
    fit_question_ids = []
    holdout_question_ids = []
    for index in range(30):
        question_id = f"q{index:02d}"
        sufficient = index % 2 == 0
        if index < 24:
            fit_question_ids.append(question_id)
        else:
            holdout_question_ids.append(question_id)
        passage = Passage(
            id=f"p{index}",
            text="Alpha is supported." if sufficient else "Unrelated evidence.",
        )
        row = SufficiencyExample(
            example_id=f"toy:{question_id}:S1:0",
            label=int(sufficient),
            context=EvidenceContext(
                retrieval_backend="bm25",
                retrieval_results=[RetrievalResult(
                    passage=passage,
                    score=0.008,
                    bm25_score=20.0 if sufficient else 2.0,
                )],
                requested_variables=["answer"],
                extracted_rows=([BindingRow(
                    slot_id="S1",
                    bindings={"answer": "Alpha"},
                    source_id=passage.id,
                    source_span=passage.text,
                    confidence=1.0,
                )] if sufficient else []),
            ),
        ).model_dump(mode="json")
        rows.append({
            **row,
            "dataset": "toy",
            "question_id": question_id,
            "slot_id": "S1",
        })
    examples_path = tmp_path / "examples.jsonl"
    examples_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    report_path = tmp_path / "calibration.json"
    report_path.write_text(json.dumps({
        "datasets": {
            "toy": {
                "fit_question_ids": fit_question_ids,
                "holdout_question_ids": holdout_question_ids,
                "fit_example_count": len(fit_question_ids),
                "holdout_example_count": len(holdout_question_ids),
            }
        }
    }), encoding="utf-8")
    output_path = tmp_path / "ablation.json"

    result = analyze_feature_ablation(
        examples_path=examples_path,
        calibration_report_path=report_path,
        output_path=output_path,
        folds=4,
    )

    assert result["provider_calls"] == 0
    assert result["holdout_used_for_selection"] is False
    assert result["selected_feature_group"] in result["candidates"]
    assert len(result["candidates"]) == 24
    assert all(
        candidate["inner_cv"]["example_count"] == len(fit_question_ids)
        for candidate in result["candidates"].values()
    )
    assert output_path.exists()
    with pytest.raises(FileExistsError, match="immutable ablation output"):
        analyze_feature_ablation(
            examples_path=examples_path,
            calibration_report_path=report_path,
            output_path=output_path,
            folds=4,
        )
