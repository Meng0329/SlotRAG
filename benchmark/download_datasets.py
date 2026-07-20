#!/usr/bin/env python3
"""Download benchmark datasets for SlotRAG evaluation."""

import os
import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a command and raise on failure."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(f"stderr: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)


def download_hotpotqa(output_dir: Path) -> None:
    """Download HotpotQA dataset from HuggingFace."""
    print("Downloading HotpotQA...")
    import datasets

    ds = datasets.load_dataset("hotpotqa/hotpot_qa", "distractor")

    # Create subdirectory
    hotpotqa_dir = output_dir / "hotpotqa"
    hotpotqa_dir.mkdir(parents=True, exist_ok=True)

    # Save each split as JSONL
    for split in ["train", "validation"]:
        data = []
        for item in ds[split]:
            # Convert to SlotRAG format
            passages = []
            for title, sentences in zip(item["context"]["title"], item["context"]["sentences"]):
                passages.append({
                    "doc_id": title,
                    "id": f"{title}#0",
                    "text": " ".join(sentences)
                })
            data.append({
                "id": item["id"],
                "question": item["question"],
                "answers": item["answer"],
                "passages": passages,
                "gold_evidence": item["supporting_facts"],
                "type": item["type"]
            })

        output_path = hotpotqa_dir / f"hotpotqa_{split}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for record in data:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  Saved {len(data)} records to {output_path}")


def download_2wikimultihop(output_dir: Path) -> None:
    """Download 2WikiMultiHopQA from GitHub repository."""
    print("Downloading 2WikiMultiHopQA...")
    import httpx

    # Create subdirectory
    wiki_dir = output_dir / "2wikimultihop"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # Download from HuggingFace (voidful version)
    try:
        import datasets
        ds = datasets.load_dataset("voidful/2WikiMultihopQA")
        for split in ["train", "validation", "test"]:
            if split not in ds:
                print(f"  Split {split} not found, skipping")
                continue

            data = []
            for item in ds[split]:
                passages = []
                for ctx in item.get("context", []):
                    if isinstance(ctx, list) and len(ctx) >= 2:
                        title = ctx[0]
                        sentences = ctx[1]
                        if isinstance(sentences, list):
                            passages.append({
                                "doc_id": title,
                                "id": f"{title}#0",
                                "text": " ".join(sentences)
                            })

                record = {
                    "id": item.get("_id", ""),
                    "question": item.get("question", ""),
                    "answers": item.get("answer", []),
                    "passages": passages,
                    "gold_evidence": item.get("supporting_facts", []),
                    "type": item.get("type", ""),
                    "evidences": item.get("evidences", [])
                }
                data.append(record)

            output_path = wiki_dir / f"2wikimultihop_{split}.jsonl"
            with open(output_path, "w", encoding="utf-8") as f:
                for record in data:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  Saved {len(data)} records to {output_path}")
    except Exception as e:
        print(f"  HuggingFace download failed: {e}")
        print("  Falling back to direct download...")
        # Fallback to direct download from HuggingFace URLs
        splits = {
            "train": "https://huggingface.co/datasets/voidful/2WikiMultihopQA/resolve/main/train.json",
            "dev": "https://huggingface.co/datasets/voidful/2WikiMultihopQA/resolve/main/dev.json",
            "test": "https://huggingface.co/datasets/voidful/2WikiMultihopQA/resolve/main/test.json",
        }

        for split_name, url in splits.items():
            print(f"  Fetching {split_name} from {url}...")
            try:
                response = httpx.get(url, timeout=120.0, follow_redirects=True)
                response.raise_for_status()

                # Parse the JSON and convert to JSONL
                raw_data = response.json()
                data = []
                for item in raw_data:
                    passages = []
                    for ctx in item.get("context", []):
                        if isinstance(ctx, list) and len(ctx) >= 2:
                            title = ctx[0]
                            sentences = ctx[1]
                            if isinstance(sentences, list):
                                passages.append({
                                    "doc_id": title,
                                    "id": f"{title}#0",
                                    "text": " ".join(sentences)
                                })

                    record = {
                        "id": item.get("_id", ""),
                        "question": item.get("question", ""),
                        "answers": item.get("answer", []),
                        "passages": passages,
                        "gold_evidence": item.get("supporting_facts", []),
                        "type": item.get("type", ""),
                        "evidences": item.get("evidences", [])
                    }
                    data.append(record)

                output_path = wiki_dir / f"2wikimultihop_{split_name}.jsonl"
                with open(output_path, "w", encoding="utf-8") as f:
                    for record in data:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"  Saved {len(data)} records to {output_path}")

            except Exception as e:
                print(f"  Failed to download {split_name}: {e}")


def download_musique(output_dir: Path) -> None:
    """Download MuSiQue dataset from HuggingFace."""
    print("Downloading MuSiQue...")
    import datasets

    # Create subdirectory
    musique_dir = output_dir / "musique"
    musique_dir.mkdir(parents=True, exist_ok=True)

    try:
        ds = datasets.load_dataset("dgslibisey/MuSiQue")
    except Exception as e:
        print(f"  HuggingFace download failed: {e}")
        print("  Trying alternative source...")
        download_musique_from_alternative(musique_dir)
        return

    # Save each split as JSONL
    for split in ["train", "validation", "test"]:
        if split not in ds:
            print(f"  Split {split} not found, skipping")
            continue

        data = []
        for item in ds[split]:
            # MuSiQue has a different format
            passages = []
            if "paragraphs" in item:
                for para in item["paragraphs"]:
                    passages.append({
                        "doc_id": para.get("title", ""),
                        "id": para.get("idx", ""),
                        "text": para.get("paragraph_text", "")
                    })

            record = {
                "id": item.get("id", ""),
                "question": item.get("question", ""),
                "answers": item.get("answer", []),
                "passages": passages,
                "gold_evidence": item.get("supporting_facts", []),
                "type": item.get("type", ""),
                "level": item.get("level", "")
            }
            data.append(record)

        output_path = musique_dir / f"musique_{split}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for record in data:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  Saved {len(data)} records to {output_path}")


def download_musique_from_alternative(musique_dir: Path) -> None:
    """Download MuSiQue from alternative sources."""
    import httpx

    # MuSiQue dataset is available from the official repository
    # Try to download from the original source
    urls = {
        "train": "https://github.com/StonyBrookNLP/musique/raw/main/data/musique_ans_v1.0_dev.jsonl",
        "dev": "https://github.com/StonyBrookNLP/musique/raw/main/data/musique_ans_v1.0_dev.jsonl",
    }

    for split, url in urls.items():
        print(f"  Fetching {split} from {url}...")
        try:
            response = httpx.get(url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()

            # Parse JSONL
            data = []
            for line in response.text.strip().split("\n"):
                if line:
                    item = json.loads(line)
                    passages = []
                    for para in item.get("paragraphs", []):
                        passages.append({
                            "doc_id": para.get("title", ""),
                            "id": para.get("idx", ""),
                            "text": para.get("paragraph_text", "")
                        })

                    record = {
                        "id": item.get("id", ""),
                        "question": item.get("question", ""),
                        "answers": item.get("answer", []),
                        "passages": passages,
                        "gold_evidence": item.get("supporting_facts", []),
                        "type": item.get("type", ""),
                        "level": item.get("level", "")
                    }
                    data.append(record)

            output_path = musique_dir / f"musique_{split}.jsonl"
            with open(output_path, "w", encoding="utf-8") as f:
                for record in data:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  Saved {len(data)} records to {output_path}")

        except Exception as e:
            print(f"  Failed to download {split}: {e}")


def download_strategyqa(output_dir: Path) -> None:
    """Download StrategyQA dataset from HuggingFace.

    StrategyQA tests implicit multi-step reasoning with yes/no questions.
    Each question requires decomposing into reasoning steps and gathering
    facts from multiple sources, similar to join/intersection operations.
    """
    print("Downloading StrategyQA...")
    import datasets

    strategyqa_dir = output_dir / "strategyqa"
    strategyqa_dir.mkdir(parents=True, exist_ok=True)

    ds = datasets.load_dataset("ChilleD/StrategyQA")

    for split in ["train", "test"]:
        if split not in ds:
            print(f"  Split {split} not found, skipping")
            continue

        data = []
        for item in ds[split]:
            # StrategyQA has facts as a single string, split into passages
            facts_text = item.get("facts", "")
            passages = []
            if facts_text:
                # Split facts by period and create passages
                sentences = [s.strip() for s in facts_text.split(".") if s.strip()]
                for i, sent in enumerate(sentences):
                    passages.append({
                        "doc_id": f"fact_{i}",
                        "id": f"fact_{i}#0",
                        "text": sent + "."
                    })

            record = {
                "id": item.get("qid", ""),
                "question": item.get("question", ""),
                "answers": [str(item.get("answer", ""))],
                "passages": passages,
                "gold_evidence": [],
                "type": "strategy",
                "term": item.get("term", ""),
                "description": item.get("description", ""),
                "decomposition": item.get("decomposition", [])
            }
            data.append(record)

        output_path = strategyqa_dir / f"strategyqa_{split}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for record in data:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  Saved {len(data)} records to {output_path}")


def download_drop(output_dir: Path) -> None:
    """Download DROP dataset from HuggingFace.

    DROP tests discrete reasoning over paragraphs including:
    - Counting
    - Sorting
    - Listing
    - Numerical comparison
    - Filtering and counting
    """
    print("Downloading DROP...")
    import datasets
    import re

    drop_dir = output_dir / "drop"
    drop_dir.mkdir(parents=True, exist_ok=True)

    ds = datasets.load_dataset("RaagulQB/drop_dataset_thinned")

    for split in ["train", "validation"]:
        if split not in ds:
            print(f"  Split {split} not found, skipping")
            continue

        data = []
        for idx, item in enumerate(ds[split]):
            instruction = item.get("instruction", "")
            response = item.get("response", "").strip()

            # Parse paragraph and question from instruction
            passage_text = ""
            question = ""

            # Extract paragraph
            para_match = re.search(r"Paragraph:\s*(.*?)(?:\nQuestion:|\n\nQuestion:)", instruction, re.DOTALL)
            if para_match:
                passage_text = para_match.group(1).strip()

            # Extract question
            q_match = re.search(r"Question:\s*(.*?)$", instruction, re.DOTALL)
            if q_match:
                question = q_match.group(1).strip()

            if not question:
                question = instruction

            passages = []
            if passage_text:
                passages.append({
                    "doc_id": f"drop_{idx}",
                    "id": f"drop_{idx}#0",
                    "text": passage_text
                })

            record = {
                "id": f"drop_{split}_{idx}",
                "question": question,
                "answers": [response] if response else [],
                "passages": passages,
                "gold_evidence": [],
                "type": "drop",
                "operation_type": classify_drop_operation(question)
            }
            data.append(record)

        output_path = drop_dir / f"drop_{split}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for record in data:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  Saved {len(data)} records to {output_path}")


def classify_drop_operation(question: str) -> str:
    """Classify the DROP question into operation type."""
    q_lower = question.lower()
    if any(w in q_lower for w in ["how many", "how much", "number of", "count"]):
        return "counting"
    elif any(w in q_lower for w in ["first", "last", "earliest", "latest", "before", "after"]):
        return "sorting"
    elif any(w in q_lower for w in ["list", "name all", "what are all"]):
        return "listing"
    elif any(w in q_lower for w in ["more", "less", "greater", "longer", "farther"]):
        return "comparison"
    else:
        return "other"


def main():
    benchmark_dir = Path(__file__).parent
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading datasets to {benchmark_dir}...")
    print("=" * 60)

    # Check for huggingface_hub
    try:
        import datasets
    except ImportError:
        print("Installing huggingface_hub and datasets...")
        subprocess.run([sys.executable, "-m", "pip", "install", "datasets", "httpx"], check=True)
        import datasets

    download_hotpotqa(benchmark_dir)
    download_2wikimultihop(benchmark_dir)
    download_musique(benchmark_dir)
    download_strategyqa(benchmark_dir)
    download_drop(benchmark_dir)

    print("=" * 60)
    print("All downloads complete!")
    print(f"\nDirectory structure in {benchmark_dir}:")
    for dirpath, dirnames, filenames in sorted(os.walk(benchmark_dir)):
        dirnames.sort()
        level = dirpath.replace(str(benchmark_dir), '').count(os.sep)
        indent = ' ' * 2 * level
        print(f'{indent}{os.path.basename(dirpath)}/')
        subindent = ' ' * 2 * (level + 1)
        for file in sorted(filenames):
            filepath = os.path.join(dirpath, file)
            size = os.path.getsize(filepath) / (1024 * 1024)
            print(f'{subindent}{file} ({size:.2f} MB)')


if __name__ == "__main__":
    main()
