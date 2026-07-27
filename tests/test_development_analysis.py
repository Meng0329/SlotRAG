import json

from slotrag.benchmarking.development import analyze_development_run, calibrate_development_report


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_development_analysis_builds_strong_examples_and_topk_oracle(tmp_path):
    run_dir = tmp_path / "run"
    stage = "dev"
    sample = {
        "id": "q1",
        "question": "Who founded Alpha?",
        "answers": ["Ada"],
        "passages": [
            {"id": "noise#0", "doc_id": "noise", "text": "Unrelated."},
            {"id": "Alpha#0", "doc_id": "Alpha", "text": "Ada founded Alpha."},
        ],
        "gold_evidence": ["Alpha#0"],
        "metadata": {"dataset": "hotpotqa", "split": "train", "stratum": "bridge"},
    }
    _write_jsonl(run_dir / "samples" / stage / "hotpotqa.jsonl", [sample])
    _write_json(run_dir / "manifest.json", {"schema_version": 1})
    item = {
        "stage": stage,
        "dataset": "hotpotqa",
        "method": "slotrag",
        "question_id": "q1",
        "retrieval_protocol": "local_context",
        "retrieval_backend": "bm25",
        "budget": {"max_retrieval_calls": 4},
        "answers": ["Ada"],
        "result": {
            "status": "empty",
            "answer": None,
            "rows": [],
            "evidence": [],
            "metrics": {},
            "plan": {
                "slots": [{"id": "S1", "predicate": "Founded", "arguments": ["Alpha", "?founder"]}],
                "joins": [],
                "operators": [],
                "outputs": ["?founder"],
            },
            "slot_traces": [{
                "step": 0,
                "slot_id": "S1",
                "predicate": "Founded",
                "binding_contexts": [{}],
                "materializations": [{
                    "slot_id": "S1",
                    "predicate": "Founded",
                    "binding_context": {},
                    "retrieval_calls": 1,
                    "searches": [{
                        "query": "Founded Alpha ?founder",
                        "query_variant": "slot",
                        "candidates": [
                            {"rank": 1, "source_id": "noise#0", "doc_id": "noise", "score": 2.0, "bm25_score": 2.0},
                            {"rank": 2, "source_id": "Alpha#0", "doc_id": "Alpha", "score": 1.0, "bm25_score": 1.0},
                        ],
                    }],
                    "selected_source_ids": ["noise#0"],
                    "extracted_rows": [],
                }],
                "extracted_row_count": 0,
                "rows_after_join": 0,
            }],
        },
        "scores": {"primary_score": 0.0},
    }
    _write_json(
        run_dir / "items" / stage / "hotpotqa" / "slotrag" / "q1.json",
        item,
    )

    report = analyze_development_run(run_dir, stage=stage)

    assert report["record_count"] == 1
    assert report["example_count"] == 1
    example = report["examples"][0]
    assert example["supervision"] == "strong_gold_evidence"
    assert example["label"] == 0
    assert example["context"]["retrieval_results"][0]["passage"]["id"] == "noise#0"
    assert report["oracle_headroom"]["expand_topk_recoverable"] == 1
    assert report["oracle_headroom"]["evidence_selected_extraction_failed"] == 0


def test_development_analysis_resolves_workspace_relative_external_corpus(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "run"
    stage = "dev"
    _write_jsonl(run_dir / "samples" / stage / "hotpotqa.jsonl", [{
        "id": "q1",
        "question": "Who founded Alpha?",
        "answers": ["Ada"],
        "passages": [],
        "gold_evidence": ["Alpha#0"],
        "metadata": {"dataset": "hotpotqa", "split": "train", "stratum": "bridge"},
    }])
    _write_json(tmp_path / "shared" / "corpus" / "manifest.json", {
        "passage_artifact": "passages.jsonl",
    })
    _write_jsonl(tmp_path / "shared" / "corpus" / "passages.jsonl", [{
        "id": "Alpha#0",
        "doc_id": "Alpha",
        "text": "Ada founded Alpha.",
    }])
    _write_json(run_dir / "items" / stage / "hotpotqa" / "slotrag" / "q1.json", {
        "stage": stage,
        "dataset": "hotpotqa",
        "method": "slotrag",
        "question_id": "q1",
        "retrieval_protocol": "global_corpus",
        "retrieval_backend": "bm25",
        "corpus_manifest": "shared/corpus/manifest.json",
        "budget": {"max_retrieval_calls": 4},
        "result": {
            "status": "ok",
            "answer": "Ada",
            "rows": [{"founder": "Ada"}],
            "evidence": [{"source_id": "Alpha#0", "source_span": "Ada founded Alpha."}],
            "plan": {
                "slots": [{"id": "S1", "predicate": "Founded", "arguments": ["Alpha", "?founder"]}],
                "joins": [], "operators": [], "outputs": ["?founder"],
            },
            "slot_traces": [{
                "step": 0, "slot_id": "S1", "predicate": "Founded",
                "materializations": [{
                    "slot_id": "S1", "predicate": "Founded", "binding_context": {},
                    "retrieval_calls": 1, "selected_source_ids": ["Alpha#0"],
                    "searches": [{
                        "query": "Founded Alpha ?founder",
                        "query_variant": "slot",
                        "candidates": [{
                            "rank": 1, "source_id": "Alpha#0", "doc_id": "Alpha",
                            "score": 1.0, "bm25_score": 1.0,
                        }],
                    }],
                    "extracted_rows": [{
                        "source_id": "Alpha#0", "bindings": {"founder": "Ada"},
                        "confidence": 1.0, "retrieval_score": 1.0,
                    }],
                }],
            }],
        },
        "scores": {"prediction_scored": "Ada", "primary_score": 1.0},
    })

    report = analyze_development_run(run_dir, stage=stage)

    assert report["missing_source_count"] == 0
    assert report["example_count"] == 1
    assert report["examples"][0]["label"] == 1
    assert report["examples"][0]["context"]["retrieval_results"][0]["passage"]["text"] == "Ada founded Alpha."


def test_development_analysis_reconstructs_local_chunks_from_frozen_profile(tmp_path):
    run_dir = tmp_path / "run"
    stage = "dev"
    _write_jsonl(run_dir / "samples" / stage / "hotpotqa.jsonl", [{
        "id": "q1",
        "question": "Who founded Alpha?",
        "answers": ["Ada"],
        "passages": [{
            "id": "Alpha#0",
            "doc_id": "Alpha",
            "text": "Noise words Ada founded Alpha today.",
        }],
        "gold_evidence": ["Alpha#0"],
        "metadata": {"dataset": "hotpotqa", "split": "train", "stratum": "bridge"},
    }])
    _write_json(run_dir / "manifest.json", {
        "schema_version": 2,
        "stage_execution_profiles": {
            stage: {
                "provider_config": {
                    "retrieval": {"chunk_tokens": 3, "chunk_overlap": 1},
                },
            },
        },
    })
    _write_json(run_dir / "items" / stage / "hotpotqa" / "slotrag" / "q1.json", {
        "stage": stage,
        "dataset": "hotpotqa",
        "method": "slotrag",
        "question_id": "q1",
        "retrieval_protocol": "local_context",
        "retrieval_backend": "bm25",
        "budget": {"max_retrieval_calls": 4},
        "result": {
            "status": "ok",
            "answer": "Ada",
            "rows": [{"founder": "Ada"}],
            "evidence": [{
                "source_id": "Alpha#0#chunk-1",
                "source_span": "Ada founded Alpha",
            }],
            "plan": {
                "slots": [{"id": "S1", "predicate": "Founded", "arguments": ["Alpha", "?founder"]}],
                "joins": [], "operators": [], "outputs": ["?founder"],
            },
            "slot_traces": [{
                "step": 0, "slot_id": "S1", "predicate": "Founded",
                "materializations": [{
                    "slot_id": "S1", "predicate": "Founded", "binding_context": {},
                    "retrieval_calls": 1, "selected_source_ids": ["Alpha#0#chunk-1"],
                    "searches": [{
                        "query": "Founded Alpha ?founder",
                        "query_variant": "slot",
                        "candidates": [{
                            "rank": 1, "source_id": "Alpha#0#chunk-1", "doc_id": "Alpha",
                            "score": 1.0, "bm25_score": 1.0,
                        }],
                    }],
                    "extracted_rows": [{
                        "source_id": "Alpha#0#chunk-1", "bindings": {"founder": "Ada"},
                        "confidence": 1.0, "retrieval_score": 1.0,
                    }],
                }],
            }],
        },
        "scores": {"prediction_scored": "Ada", "primary_score": 1.0},
    })

    report = analyze_development_run(run_dir, stage=stage)

    assert report["missing_source_count"] == 0
    assert report["example_count"] == 1
    assert report["examples"][0]["label"] == 1
    assert report["examples"][0]["context"]["retrieval_results"][0]["passage"]["text"] == "Ada founded Alpha"


def test_development_analysis_keeps_weak_supervision_out_of_strong_inventory(tmp_path):
    run_dir = tmp_path / "run"
    stage = "dev"
    _write_jsonl(run_dir / "samples" / stage / "drop.jsonl", [{
        "id": "q1",
        "question": "Who won?",
        "answers": ["Alpha"],
        "passages": [{"id": "p1", "doc_id": "d1", "text": "Alpha won."}],
        "gold_evidence": [],
        "metadata": {"dataset": "drop", "split": "train", "stratum": "other"},
    }])
    _write_json(run_dir / "manifest.json", {"schema_version": 1})
    _write_json(run_dir / "items" / stage / "drop" / "slotrag" / "q1.json", {
        "stage": stage,
        "dataset": "drop",
        "method": "slotrag",
        "question_id": "q1",
        "retrieval_protocol": "local_context",
        "retrieval_backend": "bm25",
        "budget": {"max_retrieval_calls": 4},
        "result": {
            "status": "ok",
            "answer": "Alpha",
            "rows": [{"answer": "Alpha"}],
            "evidence": [{"source_id": "p1", "source_span": "Alpha won."}],
            "plan": {
                "slots": [{"id": "S1", "predicate": "Winner", "arguments": ["?answer"]}],
                "joins": [], "operators": [], "outputs": ["?answer"],
            },
            "slot_traces": [{
                "step": 0, "slot_id": "S1", "predicate": "Winner",
                "materializations": [{
                    "slot_id": "S1", "predicate": "Winner", "binding_context": {},
                    "retrieval_calls": 1, "selected_source_ids": ["p1"],
                    "searches": [{"query": "Winner ?answer", "query_variant": "slot", "candidates": [
                        {"rank": 1, "source_id": "p1", "doc_id": "d1", "score": 1.0}
                    ]}],
                    "extracted_rows": [{
                        "source_id": "p1", "bindings": {"answer": "Alpha"},
                        "confidence": 1.0, "retrieval_score": 1.0,
                    }],
                }],
            }],
        },
        "scores": {"prediction_scored": "Alpha", "primary_score": 1.0},
    })

    report = analyze_development_run(run_dir, stage=stage)

    assert report["supervision_counts"] == {"weak_answer_surface": 1}
    assert report["examples"][0]["label"] == 1


def test_calibration_uses_question_disjoint_fit_and_holdout():
    examples = []
    for index in range(20):
        positive = index % 2 == 0
        examples.append({
            "example_id": f"hotpotqa:q{index}:S1:0",
            "dataset": "hotpotqa",
            "question_id": f"q{index}",
            "slot_id": "S1",
            "supervision": "strong_gold_evidence",
            "label": int(positive),
            "retrieval_protocol": "global_corpus",
            "retrieval_backend": "bm25",
            "context": {
                "retrieval_results": [{
                    "passage": {"id": f"p{index}", "doc_id": f"d{index}", "text": "Ada founded Alpha." if positive else "Unrelated."},
                    "score": 2.0 if positive else 0.1,
                    "bm25_score": 2.0 if positive else 0.1,
                    "dense_score": None,
                    "rerank_score": None,
                }],
                "predicate": "Founded",
                "requested_variables": ["founder"],
                "bound_variables": {},
                "join_variables": [],
                "extracted_rows": ([{
                    "slot_id": "S1", "bindings": {"founder": "Ada"},
                    "source_id": f"p{index}", "source_span": "Ada founded Alpha.",
                    "confidence": 1.0, "retrieval_score": 2.0,
                }] if positive else []),
                "remaining_plan_depth": 0,
                "retrieval_calls_used": 1,
                "retrieval_budget": 4,
            },
        })
    report = {
        "schema_version": 1,
        "run_dir": "/tmp/run",
        "stage": "dev",
        "examples": examples,
    }

    artifact, calibration = calibrate_development_report(
        report,
        training_manifest_sha256="b" * 64,
        created_at="2026-07-27T00:00:00+00:00",
        holdout_fraction=0.25,
        minimum_examples=8,
    )

    dataset_report = calibration["datasets"]["hotpotqa"]
    assert calibration["schema_version"] == 2
    assert calibration["feature_schema_version"] == 2
    assert "backend_top1_score" in calibration["feature_names"]
    assert set(dataset_report["fit_question_ids"]).isdisjoint(dataset_report["holdout_question_ids"])
    assert dataset_report["fit_example_count"] + dataset_report["holdout_example_count"] == 20
    assert dataset_report["holdout"]["example_count"] == dataset_report["holdout_example_count"]
    assert len(dataset_report["fit_predictions"]) == dataset_report["fit_example_count"]
    assert len(dataset_report["holdout_predictions"]) == dataset_report["holdout_example_count"]
    assert {
        row["question_id"] for row in dataset_report["holdout_predictions"]
    } == set(dataset_report["holdout_question_ids"])
    assert all(
        row["features"]["score_source_bm25"] == 1.0
        for row in dataset_report["holdout_predictions"]
    )
    assert artifact.source_split == "train"
    assert artifact.schema_version == 2
    assert artifact.feature_schema_version == 2
    assert artifact.retrieval_protocol == "global_corpus"
    assert artifact.retrieval_backend == "bm25"
    assert artifact.example_counts == {"hotpotqa": dataset_report["fit_example_count"]}
