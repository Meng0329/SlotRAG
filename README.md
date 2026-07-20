# SlotRAG

SlotRAG is a research prototype for query-specific evidence materialization in
multi-hop retrieval-augmented generation.

## Quick start

Use Python 3.11 and install the package in editable mode:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
set -a; . ./.env; set +a
slotrag doctor --config configs/default.yaml
```

The service credentials are read only from environment variables. The default
endpoints and model names mirror the local API notes in `docs/` and can be
overridden in YAML or with environment variables.

The first experiment slice is QO-Bench join/intersection questions. Run
`slotrag data fetch` after setting a dataset URL and checksum in the config,
then normalize a JSON/JSONL release with:

```bash
slotrag data normalize data/raw/qobench.json --output data/processed/qobench.jsonl
slotrag run --dataset data/processed/qobench.jsonl --output-dir runs/qobench
slotrag run --dataset data/processed/qobench.jsonl --mode baseline --output-dir runs/qobench-baseline
```
