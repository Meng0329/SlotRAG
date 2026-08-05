# H-009 最终报告 — score-guided 提取（2026-08-05 完成）

## 实验配置
- **控制**: `slotrag-per-path-extraction`（PerPath，无 score 引导）
- **处理**: `slotrag-score-guided-extraction`（PerPath + 提取提示加检索 score）
- **单一变量**: 仅 `score_guided_extraction`
- **数据**: DEVELOPMENT_SET, seed=2027, hotpotqa/2wikimultihop, n=100/数据集
- **配对**: 同题双方法对比；有效配对 n=188（hotpotqa 93, 2wiki 95）

## 干预实现
- `evidence_bundle.py`: `passage_payload` 加 `score` 字段（检索相关性）
- 系统提示加引导："Higher 'score' means more relevant; prefer extracting from higher-score passages"
- `MethodSpec.score_guided_extraction` flag + 新方法 `slotrag-score-guided-extraction`

## 结果（n=188 配对）

| 数据集 | control EM | treat EM | ΔEM | ΔF1 | wins/losses | wilcoxon p | 95% CI |
|--------|-----------|---------|-----|-----|-------------|-----------|--------|
| hotpotqa | 0.634 | 0.602 | **-3.2pt** | -1.4pt | 1/4 | 0.18 | [-8.6, +1.1] |
| 2wikimultihop | 0.526 | 0.579 | **+5.3pt** | +6.9pt | 6/1 | 0.059 | [+0.0, +11.6] |

## 门禁判定：**REJECTED（不一致）**

预注册门禁（hotpotqa EM ≥3pt 且 S5 减少 → 支持）：hotpotqa 是 -3.2pt → 明确拒绝。

**核心矛盾**：
- 2wiki 支持（+5.3pt, 6/1 改进）——score 引导帮助选对实体（Borrowed Plumage←The Sunset Derby）
- hotpotqa 拒绝（-3.2pt, 4/1 回归）——score 引导引入错误（German→American, Crystal Dynamics→Core Design）

## 根因解读

score-guided 效果**取决于检索 score 质量**：
- 2wiki: BM25/rerank score 可靠，高 score passage 含正确绑定值 → 引导有效
- hotpotqa: score 有误导，高 score passage 的值反而错 → 引导引入错误

**score-guided 不是稳健改进**——它把提取结果绑定到检索排序质量上，而检索排序本身不可靠（正是 S5 的根因之一）。

## 对比 H-005（答案契约）

与 H-005 模式相似：某干预在一个数据集有效、另一个无效。两者都 REJECTED。

## 副作用
- 提取提示更长（+1 行 score 说明），token 略增
- LLM 调用数不变（无新增调用）
- 无 PerPath 的 14x 延迟问题

## 产物
- `runs/slotrag-phase3r-h009-dev/`（400 items）
- `research/H009_PRE_REGISTRATION.md`
- `research/HYPOTHESES.md` H-009 → rejected
- `EXPERIMENT_LEDGER.csv` E9
