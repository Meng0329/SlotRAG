"""Convert embeddings.json -> .npy (float32 array) + index, one-time."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np


def convert(dataset: str):
    index_dir = Path(f"runs/slotrag-global-index-v74-hybrid/qo_v74_development_hybrid/{dataset}")
    emb_path = index_dir / "embeddings.json"
    npy_path = index_dir / "embeddings.npy"
    idx_path = index_dir / "embeddings_index.json"

    print(f"Converting {emb_path}...", flush=True)
    print(f"  Size: {emb_path.stat().st_size / 1e9:.2f} GB", flush=True)

    t0 = time.perf_counter()
    # Stream-read the JSON object one key at a time using raw parsing
    # The file is {"sha256": [float,...], "sha256": [float,...], ...}
    # We'll read it as a full JSON and extract
    # But 8.4GB won't fit parsed, so we do manual streaming

    # Strategy: since we know the JSON is one big object, use iterative parsing
    # Or: read character-by-character looking for keys
    # Simplest: use ijson if available, otherwise do manual streaming

    try:
        import ijson
        has_ijson = True
    except ImportError:
        has_ijson = False

    if has_ijson:
        print("  Using ijson streaming parser...", flush=True)
        all_keys = []
        all_vectors = []
        with open(emb_path, "rb") as f:
            parser = ijson.parse(f)
            for prefix, event, value in parser:
                if event == "map_key":
                    all_keys.append(value)
                elif event == "end_array" and prefix.count(".") >= 1 and ".item" in prefix:
                    # End of a vector array - just track by seeing start_array event
                    pass
                elif event == "start_array":
                    # Start collecting vector values
                    vec = []
                    for sub_prefix, sub_event, sub_val in parser:
                        if sub_event == "end_array":
                            break
                        if sub_event == "number":
                            vec.append(float(sub_val))
                    all_vectors.append(vec)
                    if len(all_vectors) % 50000 == 0:
                        print(f"    Parsed {len(all_vectors)}/{483921} vectors", flush=True)
    else:
        # Fallback: manual state-machine parser
        print("  ijson not found, using manual parser...", flush=True)
        all_keys = []
        all_vectors = []
        with open(emb_path, "rb") as f:
            data = f.read()
        print(f"  Read {len(data)/1e9:.2f} GB into memory, parsing...", flush=True)
        # Simple approach: find all keys between quotes, then find arrays after ":"
        # Actually this is too complex. Let's just orjson.loads if available
        try:
            import orjson
            print("  Using orjson...", flush=True)
            obj = orjson.loads(data)
            for k, v in obj.items():
                all_keys.append(k)
                all_vectors.append([float(x) for x in v])
            del data
            del obj
        except (ImportError, Exception) as e:
            print(f"  orjson failed: {e}, falling back to json.loads", flush=True)
            obj = json.loads(data)
            for k, v in obj.items():
                all_keys.append(k)
                all_vectors.append([float(x) for x in v])
            del data
            del obj

    print(f"  Parsed {len(all_keys)} vectors in {time.perf_counter() - t0:.1f}s", flush=True)

    # Convert to numpy array
    t1 = time.perf_counter()
    arr = np.asarray(all_vectors, dtype=np.float32)
    print(f"  Converted to numpy array shape {arr.shape} in {time.perf_counter() - t1:.1f}s", flush=True)

    # Save .npy (can be mmap'd later)
    t2 = time.perf_counter()
    np.save(npy_path, arr)
    print(f"  Saved {npy_path} ({arr.nbytes / 1e9:.2f} GB) in {time.perf_counter() - t2:.1f}s", flush=True)

    # Save index: sha256 -> row mapping
    # Index is a list of keys, position is row index
    t3 = time.perf_counter()
    idx_path.write_text(json.dumps(all_keys, separators=(",", ":")))
    print(f"  Saved {idx_path} in {time.perf_counter() - t3:.1f}s", flush=True)

    # Verify
    arr2 = np.load(npy_path, mmap_mode="r")
    print(f"  Verification: npy shape={arr2.shape}, dtype={arr2.dtype}, first[-3:]={arr2[0][-3:]}", flush=True)

    total_gb = arr.nbytes / 1e9 + idx_path.stat().st_size / 1e9
    print(f"\n  Done! Combined size: {total_gb:.2f} GB (was {emb_path.stat().st_size / 1e9:.2f} GB)", flush=True)
    print(f"  Memory-mappable: instant load for benchmark runner", flush=True)


if __name__ == "__main__":
    datasets = ["hotpotqa", "2wikimultihop"]
    for ds in datasets:
        print(f"\n=== {ds} ===", flush=True)
        convert(ds)
    print("\n=== ALL DONE ===", flush=True)