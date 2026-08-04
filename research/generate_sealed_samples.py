#!/usr/bin/env python3
"""生成受三集合约束的 benchmark 样本文件

问题：load_sample 用 SHA256 哈希排序采样（seed=2027），与三集合的
random.Random(2027).shuffle 机制不一致，导致：
1. 采样混入已暴露样本
2. 采样同时落在 dev/val/test 三集合，无法隔离

修复：直接从 eval 数据集文件 + 三集合样本 ID 生成样本文件。
_loader_or_create_sample 发现 samples/{stage}/{dataset}.jsonl 存在时会直接复用，
从而绕过 load_sample 的 SHA256 采样。

用法：
  python3 research/generate_sealed_samples.py \
    --stage tier1_dev --set development --size 20 \
    --datasets hotpotqa 2wikimultihop musique strategyqa drop \
    --output-dir runs/slotrag-phase3-dev

生成的样本文件：{output_dir}/samples/{stage}/{dataset}.jsonl
"""
import argparse, json, random
from pathlib import Path

DATASETS = ('hotpotqa', '2wikimultihop', 'musique', 'strategyqa', 'drop')
SPLIT_FILES = {
    'hotpotqa': 'benchmark/hotpotqa/hotpotqa_validation.jsonl',
    '2wikimultihop': 'benchmark/2wikimultihop/2wikimultihop_dev.jsonl',
    'musique': 'benchmark/musique/musique_validation.jsonl',
    'strategyqa': 'benchmark/strategyqa/strategyqa_test.jsonl',
    'drop': 'benchmark/drop/drop_validation.jsonl',
}

def load_dataset(path):
    """加载数据集，返回 {record_id: record}"""
    records = {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            rid = rec.get('id')
            if rid:
                records[rid] = rec
    return records

def load_set(set_name):
    """加载三集合，返回 {dataset: set(ids)}"""
    path = Path(f'research/eval_sets/{set_name}_set.json')
    return {ds: set(ids) for ds, ids in json.load(open(path)).items()}

def load_exposed():
    """加载已暴露样本，返回 {dataset: set(ids)}"""
    import csv
    exposed = {}
    with open('research/EXPOSED_SAMPLE_REGISTRY.csv') as f:
        for row in csv.DictReader(f):
            if row['split'] != 'evaluation':
                continue
            exposed.setdefault(row['dataset'], set()).add(row['sample_id'])
    return exposed

def generate(stage, set_name, size, datasets, output_dir, seed=2027):
    output_dir = Path(output_dir)
    set_ids = load_set(set_name)
    exposed = load_exposed()
    rng = random.Random(seed)

    total_created = {}
    for ds in datasets:
        records = load_dataset(SPLIT_FILES[ds])
        allowed = set_ids.get(ds, set())
        excluded = exposed.get(ds, set())
        # 只保留：在三集合内 + 未暴露
        candidates = [
            rid for rid, rec in records.items()
            if rid in allowed and rid not in excluded
        ]
        # 确定性采样（先排序保证可复现）
        rng.shuffle(candidates)
        selected = candidates[:size]

        # 生成样本文件
        sample_dir = output_dir / 'samples' / stage
        sample_dir.mkdir(parents=True, exist_ok=True)
        sample_path = sample_dir / f'{ds}.jsonl'
        with open(sample_path, 'w') as f:
            for rid in sorted(selected):
                rec = records[rid]
                # 适配 QuestionRecord 需要的字段
                out = {
                    'id': rid,
                    'question': rec.get('question', ''),
                    'passages': rec.get('passages', []),
                    'answers': rec.get('answers', []),
                    'gold_evidence': rec.get('gold_evidence', []),
                    'metadata': rec.get('metadata', {}),
                }
                f.write(json.dumps(out, ensure_ascii=False) + '\n')
        total_created[ds] = len(selected)
        print(f"  {ds:<16} selected={len(selected)}/{len(candidates)} available")

    # 打印集合统计
    print(f"\n生成完成: {output_dir}/samples/{stage}/")
    print(f"集合: {set_name} (seed={seed})")
    for ds, n in total_created.items():
        print(f"  {ds}: {n} samples")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True, help='stage 名称 (如 tier1_dev)')
    parser.add_argument('--set', required=True, choices=['development', 'validation', 'test'],
                        help='三集合名称')
    parser.add_argument('--size', type=int, required=True, help='每个数据集的样本数')
    parser.add_argument('--datasets', nargs='+', default=list(DATASETS))
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--seed', type=int, default=2027)
    args = parser.parse_args()
    generate(args.stage, args.set, args.size, args.datasets, args.output_dir, args.seed)

if __name__ == '__main__':
    main()
