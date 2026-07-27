"""Fit and evaluate the development-only evidence sufficiency calibrator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from slotrag.sufficiency import EvidenceSufficiencyCalibrator, SufficiencyExample


def load_examples(path: Path) -> list[SufficiencyExample]:
    examples: list[SufficiencyExample] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                examples.append(SufficiencyExample.model_validate(payload))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid sufficiency example at {path}:{line_number}: {exc}") from exc
    if not examples:
        raise ValueError(f"no sufficiency examples found in {path}")
    return examples


def _split_examples(examples: list[SufficiencyExample], calibration_fraction: float) -> tuple[list[SufficiencyExample], list[SufficiencyExample]]:
    if not 0 < calibration_fraction < 1:
        raise ValueError("calibration_fraction must be between 0 and 1")
    ordered = sorted(examples, key=lambda example: example.example_id)
    calibration_count = max(1, min(len(ordered) - 1, round(len(ordered) * calibration_fraction)))
    return ordered[:-calibration_count], ordered[-calibration_count:]


def run_calibration(
    input_path: Path,
    output_dir: Path,
    *,
    calibration_fraction: float = 0.25,
    bins: int = 10,
) -> dict[str, Any]:
    examples = load_examples(input_path)
    train_examples, calibration_examples = _split_examples(examples, calibration_fraction)
    calibrator = EvidenceSufficiencyCalibrator.fit(train_examples)
    train_report = calibrator.evaluate(train_examples, bins=bins)
    calibration_report = calibrator.evaluate(calibration_examples, bins=bins)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "calibrator.json").write_text(
        json.dumps(calibrator.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for name, report in (("train_report.json", train_report), ("calibration_report.json", calibration_report)):
        (output_dir / name).write_text(
            report.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    with (output_dir / "reliability.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(train_report.reliability_bins[0].model_dump()))
        writer.writeheader()
        writer.writerows(bin_.model_dump() for bin_ in calibration_report.reliability_bins)
    predictions_path = output_dir / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as handle:
        for split, split_examples in (("train", train_examples), ("calibration", calibration_examples)):
            for example in split_examples:
                prediction = calibrator.predict(example.context)
                handle.write(json.dumps({
                    "split": split,
                    "example_id": example.example_id,
                    "label": example.label,
                    "status": prediction.status,
                    "probability": prediction.probability,
                    "raw_logit": prediction.raw_logit,
                    "features": prediction.features.model_dump(mode="json"),
                }, ensure_ascii=False) + "\n")
    status_counts = {
        split: dict(Counter(
            calibrator.predict(example.context).status
            for example in split_examples
        ))
        for split, split_examples in (("train", train_examples), ("calibration", calibration_examples))
    }
    manifest = {
        "input_path": str(input_path),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "example_count": len(examples),
        "train_count": len(train_examples),
        "calibration_count": len(calibration_examples),
        "feature_names": list(calibrator.feature_names),
        "gold_not_used_by_feature_extractor": True,
        "calibration_fraction": calibration_fraction,
        "bins": bins,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "provider_calls": 0,
        "manifest": manifest,
        "train": train_report.model_dump(mode="json"),
        "calibration": calibration_report.model_dump(mode="json"),
        "thresholds": {
            "sufficient": calibrator.sufficient_threshold,
            "partial": calibrator.partial_threshold,
        },
        "status_counts": status_counts,
        "predictions": str(predictions_path),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--calibration-fraction", type=float, default=0.25)
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args()
    summary = run_calibration(
        args.input_jsonl,
        args.output_dir,
        calibration_fraction=args.calibration_fraction,
        bins=args.bins,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
