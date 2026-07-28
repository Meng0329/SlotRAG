from tools.analyze_dual_access_bundle import analyze_records


def test_dual_access_bundle_preserves_slot_evidence_and_adds_question_evidence():
    materializations = [{
        "materialization_id": "q1:S1:0",
        "dataset": "toy",
        "question_id": "q1",
        "slot_id": "S1",
        "strategies": {
            "slot": {"source_ids": ["gold-a", "shared", "noise-a"]},
            "question_plus_lexical_slot": {
                "source_ids": ["gold-b", "shared", "noise-b"]
            },
        },
    }]
    question_records = [{
        "dataset": "toy",
        "question_id": "q1",
        "strategy": "slot",
        "gold_ids": ["gold-a", "gold-b"],
        "recall": 0.5,
    }]

    materialization_rows, question_rows, report = analyze_records(
        materializations,
        question_records,
        per_path_top_k=3,
    )

    assert materialization_rows[0]["union_source_ids"] == [
        "gold-a", "shared", "noise-a", "gold-b", "noise-b"
    ]
    assert materialization_rows[0]["candidate_overlap_size"] == 1
    assert question_rows[0]["bundle_recall"] == 1.0
    assert report["overall"]["gain_tie_loss"] == {"gain": 1, "tie": 0, "loss": 0}
    assert report["physical_sparse_batches_per_materialization"] == 1
