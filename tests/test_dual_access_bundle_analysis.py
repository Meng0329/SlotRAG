import hashlib
import json

from tools.analyze_dual_access_bundle import analyze_records, verify_source_provenance


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
    assert materialization_rows[0]["sparse_access_modes"] == ["body", "configured"]
    assert question_rows[0]["bundle_recall"] == 1.0
    assert report["overall"]["gain_tie_loss"] == {"gain": 1, "tie": 0, "loss": 0}
    assert report["physical_sparse_batches_per_materialization"] == 1
    assert report["access_path_policy"] == "heterogeneous_dual_bundle"


def test_dual_access_provenance_verifies_body_trace_and_bm25f_index(tmp_path):
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    source_manifest = {
        "suite": {"stages": {"dev": {"retrieval_backend": "bm25"}}},
        "stage_execution_profiles": {
            "dev": {"provider_config": {"retrieval": {"bm25_k": 50}}}
        },
    }
    source_manifest_path = source_run / "manifest.json"
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")
    source_sha = hashlib.sha256(source_manifest_path.read_bytes()).hexdigest()

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    index_manifest = {
        "index_id": "index-id",
        "passage_artifact_sha256": "a" * 64,
        "sparse_index_sha256": "b" * 64,
        "sparse_index_mode": "bm25f",
        "sparse_title_weight": 2.0,
    }
    (index_dir / "manifest.json").write_text(
        json.dumps(index_manifest), encoding="utf-8"
    )
    headroom_manifest = {
        "source_stage": "dev",
        "source_runs": ["source-run"],
        "source_manifest_sha256": {"source-run": source_sha},
        "index_provenance": {
            "toy": {"index_dir": "index", **{
                field: index_manifest[field]
                for field in (
                    "index_id",
                    "passage_artifact_sha256",
                    "sparse_index_sha256",
                )
            }}
        },
    }

    provenance = verify_source_provenance(headroom_manifest, project_root=tmp_path)

    assert provenance["verified"] is True
    assert provenance["slot_access_sources"][0]["sparse_index_mode"] == "body"
    assert provenance["configured_access_indexes"]["toy"]["sparse_index_mode"] == "bm25f"
