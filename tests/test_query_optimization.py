from slotrag.query_optimization import (
    canonical_evidence_id,
    formulate_query,
    reciprocal_rank_fusion,
    select_development_strategy,
    summarize_strategy_records,
)


def test_query_formulation_is_generic_and_removes_plan_syntax():
    slot_query = "born_in Ada_Lovelace ?place"

    assert formulate_query("Where was Ada born?", slot_query, "slot") == slot_query
    assert formulate_query("Where was Ada born?", slot_query, "question") == "Where was Ada born?"
    assert formulate_query("Where was Ada born?", slot_query, "lexical_slot") == "born in Ada Lovelace"
    assert formulate_query(
        "Where was Ada born?", slot_query, "question_plus_lexical_slot"
    ) == "Where was Ada born? born in Ada Lovelace"


def test_canonical_evidence_id_removes_dataset_and_chunk_namespace():
    assert canonical_evidence_id("hotpotqa:Ada Lovelace:Ada Lovelace#0") == "Ada Lovelace#0"
    assert canonical_evidence_id(
        "hotpotqa:Star Wars: Episode IV:Star Wars: Episode IV#0"
    ) == "Star Wars: Episode IV#0"
    assert canonical_evidence_id("2wikimultihop:A:B#0#chunk-2") == "B#0"
    assert canonical_evidence_id("Ada Lovelace#0") == "Ada Lovelace#0"


def test_rrf_fusion_rewards_agreement_and_is_deterministic():
    fused = reciprocal_rank_fusion(
        [["a", "b", "c"], ["b", "d", "a"]],
        top_k=3,
        rrf_k=60,
    )

    assert fused == ["b", "a", "d"]


def test_summary_and_selection_use_development_only_lexicographic_gate():
    records = [
        {
            "dataset": "hotpotqa",
            "question_id": "q1",
            "strategy": "slot",
            "gold_count": 2,
            "hit_count": 1,
            "recall": 0.5,
            "full_support": False,
            "any_support": True,
            "extra_calls": 0,
        },
        {
            "dataset": "hotpotqa",
            "question_id": "q1",
            "strategy": "slot_plus_question",
            "gold_count": 2,
            "hit_count": 2,
            "recall": 1.0,
            "full_support": True,
            "any_support": True,
            "extra_calls": 2,
        },
        {
            "dataset": "2wikimultihop",
            "question_id": "q2",
            "strategy": "slot",
            "gold_count": 1,
            "hit_count": 0,
            "recall": 0.0,
            "full_support": False,
            "any_support": False,
            "extra_calls": 0,
        },
        {
            "dataset": "2wikimultihop",
            "question_id": "q2",
            "strategy": "slot_plus_question",
            "gold_count": 1,
            "hit_count": 0,
            "recall": 0.0,
            "full_support": False,
            "any_support": False,
            "extra_calls": 1,
        },
    ]

    report = summarize_strategy_records(records, baseline_strategy="slot")
    selected, ranking = select_development_strategy(report, baseline_strategy="slot")

    assert report["slot_plus_question"]["gain_tie_loss"] == {
        "gain": 1,
        "tie": 1,
        "loss": 0,
    }
    assert report["slot_plus_question"]["mean_recall"] == 0.5
    assert report["slot_plus_question"]["full_support_rate"] == 0.5
    assert selected == "slot_plus_question"
    assert ranking[0] == "slot_plus_question"
