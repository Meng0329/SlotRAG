#!/usr/bin/env python3
"""阶段 0 审计：构建 EXPOSED_SAMPLE_REGISTRY.csv

扫描所有历史 run 的 samples/ 目录和 per_question 结果，记录每个样本的暴露情况。
只读操作，不修改任何核心代码。输出到 research/EXPOSED_SAMPLE_REGISTRY.csv
"""
import csv, json, os, glob, sys
from collections import defaultdict

DATASETS = ('hotpotqa', '2wikimultihop', 'musique', 'strategyqa', 'drop')

def extract_dataset(path):
    for p in path.split('/'):
        base = p.split('.')[0]  # 去掉 .jsonl 后缀
        if base in DATASETS:
            return base
    return None

def main():
    registry = {}  # (dataset, sample_id) -> dict

    def add_entry(dataset, sample_id, run, split='unknown', methods=None,
                  result_exposed=False, per_question_exposed=False):
        methods = methods or []
        key = (dataset, sample_id)
        if key not in registry:
            registry[key] = {
                'dataset': dataset, 'split': split, 'sample_id': sample_id,
                'first_seen_run': run, 'methods_seen': set(),
                'result_exposed': False, 'per_question_exposed': False,
            }
        e = registry[key]
        # 若此前 split=unknown 而现在知道真实 split，更新
        if e['split'] == 'unknown' and split != 'unknown':
            e['split'] = split
        e['methods_seen'].update(methods)
        if result_exposed:
            e['result_exposed'] = True
        if per_question_exposed:
            e['per_question_exposed'] = True

    # 0. 预读所有 run 的 manifest stage->split 映射
    stage_split = {}  # (run, stage) -> split
    for mf in glob.glob('runs/*/manifest.json'):
        run = mf.split('/')[1]
        try:
            m = json.load(open(mf))
            stages = m.get('suite', {}).get('stages', {})
            if isinstance(stages, dict):
                for sn, sc in stages.items():
                    stage_split[(run, sn)] = sc.get('split', 'unknown')
        except Exception:
            pass

    # 1. samples/ 目录（采样暴露，split 从 manifest 推断）
    for jf in glob.glob('runs/*/samples/*/*.jsonl'):
        ds = extract_dataset(jf)
        if not ds:
            continue
        parts = jf.split('/')
        run = parts[1]
        stage = parts[3] if len(parts) > 3 else 'unknown'
        split = stage_split.get((run, stage), 'unknown')
        try:
            with open(jf) as f:
                for line in f:
                    rec = json.loads(line)
                    qid = rec.get('id') or rec.get('question_id')
                    if qid:
                        add_entry(ds, qid, run, split=split)
        except Exception:
            pass

    # 2. baseline per_question.csv（已出结果，eval split）
    bpq = 'runs/vldb2027-submission-qwen36-v3-rescored-v2-final/summaries/main_comparison/per_question.csv'
    if os.path.exists(bpq):
        with open(bpq) as f:
            for row in csv.DictReader(f):
                ds = row.get('dataset')
                qid = row.get('question_id')
                method = row.get('method')
                if ds and qid:
                    add_entry(ds, qid, 'vldb2027-baseline', split='evaluation',
                              methods=[method], result_exposed=True,
                              per_question_exposed=True)

    # 3. V6c training_2k（train split 结果）
    prog = 'runs/slotrag-v74-qwen-hybrid-reranker-v6/training_2k_progress.jsonl'
    if os.path.exists(prog):
        with open(prog) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    qid = rec.get('id')
                    ds = rec.get('dataset')
                    if qid and ds:
                        add_entry(ds, qid, 'v6c-training-2k', split='train',
                                  result_exposed=True, per_question_exposed=True)
                except Exception:
                    pass

    # 4. 判定污染状态
    by_split = defaultdict(int)
    by_contam = defaultdict(int)
    by_dataset = defaultdict(lambda: {'total': 0, 'contam': 0})
    for key, e in registry.items():
        ds = e['dataset']
        by_split[e['split']] += 1
        by_dataset[ds]['total'] += 1
        if e['split'] in ('evaluation', 'eval', 'dev'):
            if e['per_question_exposed'] or e['result_exposed']:
                e['contamination_status'] = 'CONTAMINATED'
                by_contam['CONTAMINATED'] += 1
                by_dataset[ds]['contam'] += 1
            else:
                e['contamination_status'] = 'EXPOSED_NOT_SCORED'
                by_contam['EXPOSED_NOT_SCORED'] += 1
        elif e['split'] == 'train':
            e['contamination_status'] = 'TRAIN_EXPOSED'
            by_contam['TRAIN_EXPOSED'] += 1
        else:
            e['contamination_status'] = 'UNKNOWN'
            by_contam['UNKNOWN'] += 1

    # 5. 写 CSV
    os.makedirs('research', exist_ok=True)
    csv_path = 'research/EXPOSED_SAMPLE_REGISTRY.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['dataset', 'split', 'sample_id', 'first_seen_run',
                         'methods_seen', 'result_exposed', 'per_question_exposed',
                         'used_for_tuning', 'contamination_status'])
        for key, e in sorted(registry.items()):
            writer.writerow([e['dataset'], e['split'], e['sample_id'],
                             e['first_seen_run'],
                             '|'.join(sorted(e['methods_seen'])),
                             e['result_exposed'], e['per_question_exposed'],
                             False, e['contamination_status']])

    print(f"总 unique 样本: {len(registry)}")
    print(f"按 split: {dict(sorted(by_split.items(), key=lambda x: -x[1]))}")
    print(f"按污染: {dict(sorted(by_contam.items(), key=lambda x: -x[1]))}")
    print(f"按数据集: ", end='')
    for ds, info in sorted(by_dataset.items(), key=lambda x: -x[1]['total']):
        print(f"{ds}({info['total']}/contam={info['contam']}) ", end='')
    print(f"\nCSV 写入: {csv_path}")

if __name__ == '__main__':
    main()
