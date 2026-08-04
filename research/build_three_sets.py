#!/usr/bin/env python3
"""阶段 2：构造三集合 (DEVELOPMENT, DISJOINT_VALIDATION, SEALED_FINAL)

从干净评估样本中采样，确保：
1. 三集合互不重叠
2. 与所有历史样本去重
3. 记录采样元数据（seed, checksum, script version）
"""
import csv, json, hashlib, os, random
from collections import defaultdict

# === 配置 ===
RANDOM_SEED = 2027  # 与 execution_config.random_seed 一致
DEV_RATIO = 0.3      # 30% 开发集
VAL_RATIO = 0.3      # 30% 验证集
TEST_RATIO = 0.4     # 40% 最终测试集

EXPOSED_REGISTRY = 'research/EXPOSED_SAMPLE_REGISTRY.csv'
OUTPUT_DIR = 'research/eval_sets'
MANIFEST_PATH = 'runs/vldb2027-submission-qwen36-v3-rescored-v2-final/manifest.json'

def load_exposed_samples():
    """加载所有已暴露样本 ID"""
    exposed = set()
    with open(EXPOSED_REGISTRY) as f:
        for row in csv.DictReader(f):
            if row['split'] == 'evaluation':
                exposed.add((row['dataset'], row['sample_id']))
    return exposed

def load_all_eval_samples():
    """从 benchmark 目录加载所有评估样本"""
    eval_samples = {}  # dataset -> list of sample_ids
    manifest = json.load(open(MANIFEST_PATH))
    
    for audit in manifest.get('dataset_audit', []):
        if audit['split'] == 'evaluation':
            ds = audit['dataset']
            path = audit['path']
            samples = []
            with open(path) as f:
                for line in f:
                    rec = json.loads(line)
                    qid = rec.get('id') or rec.get('question_id')
                    if qid:
                        samples.append(qid)
            eval_samples[ds] = samples
            print(f"  {ds}: {len(samples)} eval samples loaded")
    return eval_samples

def build_three_sets(eval_samples, exposed):
    """构造三集合"""
    rng = random.Random(RANDOM_SEED)
    
    dev_set = defaultdict(list)
    val_set = defaultdict(list)
    test_set = defaultdict(list)
    
    stats = {
        'total_eval': 0,
        'exposed': 0,
        'clean': 0,
        'dev': 0,
        'val': 0,
        'test': 0,
    }
    
    for ds, samples in eval_samples.items():
        # 去重
        unique_samples = list(set(samples))
        stats['total_eval'] += len(unique_samples)
        
        # 分离已暴露和干净样本
        clean = [s for s in unique_samples if (ds, s) not in exposed]
        exposed_count = len(unique_samples) - len(clean)
        stats['exposed'] += exposed_count
        stats['clean'] += len(clean)
        
        # 打乱并分割
        rng.shuffle(clean)
        n = len(clean)
        n_dev = int(n * DEV_RATIO)
        n_val = int(n * VAL_RATIO)
        
        dev_set[ds] = clean[:n_dev]
        val_set[ds] = clean[n_dev:n_dev + n_val]
        test_set[ds] = clean[n_dev + n_val:]
        
        stats['dev'] += len(dev_set[ds])
        stats['val'] += len(val_set[ds])
        stats['test'] += len(test_set[ds])
        
        print(f"\n{ds}:")
        print(f"  已暴露: {exposed_count}")
        print(f"  干净: {len(clean)}")
        print(f"  DEV: {len(dev_set[ds])} ({len(dev_set[ds])/len(clean)*100:.1f}%)")
        print(f"  VAL: {len(val_set[ds])} ({len(val_set[ds])/len(clean)*100:.1f}%)")
        print(f"  TEST: {len(test_set[ds])} ({len(test_set[ds])/len(clean)*100:.1f}%)")
    
    return dev_set, val_set, test_set, stats

def compute_checksum(data):
    """计算数据的 SHA256 校验和"""
    return hashlib.sha256(json.dumps(sorted(data), sort_keys=True).encode()).hexdigest()

def save_sets(dev_set, val_set, test_set, stats):
    """保存三集合"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 保存样本 ID
    for name, dataset_sets in [('development', dev_set), ('validation', val_set), ('test', test_set)]:
        path = os.path.join(OUTPUT_DIR, f'{name}_set.json')
        with open(path, 'w') as f:
            json.dump(dict(dataset_sets), f, indent=2)
        
        # 计算校验和
        all_ids = []
        for ds, ids in dataset_sets.items():
            all_ids.extend([(ds, id_) for id_ in ids])
        checksum = compute_checksum(all_ids)
        
        # 保存校验和
        checksum_path = os.path.join(OUTPUT_DIR, f'{name}_set.sha256')
        with open(checksum_path, 'w') as f:
            f.write(checksum)
        
        print(f"\n{name.upper()} SET:")
        print(f"  Path: {path}")
        print(f"  Checksum: {checksum[:16]}...")
    
    # 保存元数据
    metadata = {
        'created_at': '2026-08-04T21:30:00Z',
        'random_seed': RANDOM_SEED,
        'dev_ratio': DEV_RATIO,
        'val_ratio': VAL_RATIO,
        'test_ratio': TEST_RATIO,
        'stats': stats,
        'script_version': '1.0.0',
        'exposed_registry': EXPOSED_REGISTRY,
        'manifes_path': MANIFEST_PATH,
    }
    
    metadata_path = os.path.join(OUTPUT_DIR, 'metadata.json')
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\nMetadata: {metadata_path}")

def verify_disjoint(dev_set, val_set, test_set):
    """验证三集合互不重叠"""
    all_ids = defaultdict(set)
    
    for ds, ids in dev_set.items():
        for id_ in ids:
            all_ids[(ds, id_)].add('dev')
    
    for ds, ids in val_set.items():
        for id_ in ids:
            all_ids[(ds, id_)].add('val')
    
    for ds, ids in test_set.items():
        for id_ in ids:
            all_ids[(ds, id_)].add('test')
    
    # 检查重叠
    overlaps = {k: v for k, v in all_ids.items() if len(v) > 1}
    
    if overlaps:
        print(f"\n❌ 发现 {len(overlaps)} 个重叠样本!")
        for (ds, id_), sets in list(overlaps.items())[:5]:
            print(f"  {ds}/{id_}: {sets}")
        return False
    else:
        print(f"\n✅ 三集合互不重叠，共 {len(all_ids)} 个唯一样本")
        return True

def main():
    print("=== 阶段 2：构造三集合 ===\n")
    
    print("1. 加载已暴露样本...")
    exposed = load_exposed_samples()
    print(f"   已暴露样本: {len(exposed)}")
    
    print("\n2. 加载所有评估样本...")
    eval_samples = load_all_eval_samples()
    
    print("\n3. 构造三集合...")
    dev_set, val_set, test_set, stats = build_three_sets(eval_samples, exposed)
    
    print("\n4. 验证互斥性...")
    verify_disjoint(dev_set, val_set, test_set)
    
    print("\n5. 保存三集合...")
    save_sets(dev_set, val_set, test_set, stats)
    
    print("\n=== 完成 ===")

if __name__ == '__main__':
    main()
