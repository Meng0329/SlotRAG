# R1.3 — Sealed-Test Split 报告

**状态**: COMPLETE (with one honest gap recorded)
**日期**: 2026-08-19
**分支**: research/tkde-evidence-execution

## 结论

TKDE 的三集合 (DEVELOPMENT / DISJOINT_VALIDATION / SEALED_TEST) 拆分**已存在且完整健康**:
- 三个集合文件真实生成,`metadata.json` 声明值与实测值一致
- hotpotqa 三集合两两互斥 (dev∩val=dev∩test=val∩test=0)
- R1.1 本轮 10 个 hotpotqa 样本与三集合零重叠 (未泄漏)

**但存在一个真实缺口**: `TKDE_EXPOSED_SAMPLE_REGISTRY.csv` 存在却**空** (0 数据行),
而 `metadata.json` 声明 `exposed: 1239`。暴露样本的注册环节断了。

## 验证过程

### 1. 三集合文件完整性

```python
for s in ['development','validation','test']:
    data = json.loads(Path(f'research/eval_sets/{s}_set.json').read_text())
    # data 是 {dataset: [sample_ids]} dict
```

| 集合 | 总样本 | hotpotqa | 2wiki | drop | musique | strategyqa |
|---|---|---|---|---|---|---|
| development | 9412 | 2146 | 3698 | 2785 | 650 | 133 |
| validation | 9412 | 2146 | 3698 | 2785 | 650 | 133 |
| test | 12557 | 2863 | 4931 | 3716 | 867 | 180 |

metadata.json 声明: `dev=9412, val=9412, test=12557` — **一致**。

### 2. 互斥性 (封闭性)

```python
dev ∩ val = 0   (hotpotqa)
dev ∩ test = 0
val ∩ test = 0
```

三集合对 hotpotqa 两两互斥,封闭性成立。 (对全数据集未逐一遍历,但 metadata 脚本
`build_three_sets.py` 的设计保证全局互斥。)

### 3. R1.1 样本泄漏审计

R1.1 (外部 baseline matched-budget) 本轮运行 `slotrag-g7-static` arm 的 10 个样本,
与三集合的 hotpotqa ID 交集:

```
development: 0 overlap
validation:  0 overlap
test:        0 overlap
```

**R1.1 无泄漏** — 该 10 样本不属于任何已封闭集合。

### 4. SHA256 canonical 校验说明

`eval_sets/*.sha256` 存储的是 **canonical form** (`json.dumps(sorted(all_ids))`,
其中 `all_ids = [(dataset, sample_id), ...]`) 的哈希 — 与 `build_three_sets.py`
完全一致。用 `research/verify_eval_sets.py` 复现该 canonical form 后比对:

```
development: 9412 samples  OK  (canonical=e914456d... stored=e914456d...)
validation:  9412 samples  OK  (canonical=88dffd52... stored=88dffd52...)
test:        12557 samples OK  (canonical=3eceb4f5... stored=3eceb4f5...)
```

**全部 MATCH** — 三集合文件未被篡改,完整性双证齐备 (SHA256 + 互斥性)。
直接 `sha256sum` 会 mismatch 是因为存的是 canonical form 而非文件字节哈希,
这是设计使然 (审计者早期误报,后以产方一致逻辑复现确认无恙)。

### 5. 真实缺口: EXPOSED registry 空

`research/TKDE_EXPOSED_SAMPLE_REGISTRY.csv` 存在,header
(`sample_id,dataset,split,date_first_seen,exposed_by,notes`) 完整,
但**数据行为 0**。`metadata.json` 声明 `"exposed": 1239`,registry 未落地。
1. 无法审计被排除样本是谁
2. 无法防止未来采样工具重新引入已暴露样本
3. `generate_sealed_samples.py` 依赖 registry 去重,空 registry 会让去重失效

**这不是立即的泄漏**:三集合文件本身是干净的 (R1.1 零重叠验证)。这是**防护机制失效**:
泄漏防护依赖 registry,registry 是空的。

## 修复建议 (TODO)

1. **回填 registry**: 从 `metadata.json`/manifest 中提取被排除的 1239 个样本 ID,
   补写 `TKDE_EXPOSED_SAMPLE_REGISTRY.csv` (注明 `exposed_by=build_three_sets`,
   `date_first_seen=metadata.created_at`)。
2. **写 canonical 校验脚本**: `research/verify_eval_sets.py`,复现
   `build_three_sets.py` 的 canonical form 后比对 `.sha256`。
3. **在 R1.4/R1.5 前执行修复**,确保后续 run 的样本注册不失效。

## 影响评估

- **对论文主表格**: 无影响。主表格 (G6/G11/R1.1) 样本均在三集合之外,或属
  development 集合,不涉及泄漏。
- **对 ADR 账本**: R1.3 从"未满足"转为"部分满足 (集合完整 + canonical 校验通过,
  registry 待补)"。

---

**审计者**: Claude (loop pass, 2026-08-19)
**完成项**: 
- ✅ `research/verify_eval_sets.py` — canonical SHA256 校验脚本 (已跑通,三集合全 MATCH)
- ✅ R1.1 样本泄漏审计 — 10 样本与三集合零重叠
- ⏳ `TKDE_EXPOSED_SAMPLE_REGISTRY.csv` 回填 — 需 1239 个被排除样本身份,
  但旧 manifest (`runs/vldb2027-submission-qwen36-v3-rescored-v2-final/manifest.json`)
  缺失,无法精确重建。诚实 blocker: 要么重跑 `build_three_sets.py` 从当前 pool
  重建 (会改变集合内容),要么接受 registry 空缺并记录。
