# H-027 Pre-Registration: Sampled Majority-Vote Answer Aggregation（固定 evidence 上多次采样 + 多数票）

**假设编号**: H-027
**状态**: proposed（Phase 3X, 2026-08-07）
**日期**: 2026-08-07

## 背景（H-022 决定性证据 + H-026 方向收束）

**H-022 聚类（2wiki n=100, 54 exact / 18 partial / 28 zero）**:
- **选型失败 20**：gold 连续在 evidence 但生成器选错候选（比较二选一选反、粒度二选一选错、错误地理位置）。**27/28 F1=0 全 status='ok'** → 架构链已跑通，失败纯在生成/选型
- **粒度错配 14**：evidence 里 gold 和 pred 两种粒度都连续 → 生成器选了 evidence 里"更精细的下层实体标签"
- **后处理不可行**：naive 前缀收窄 9 恢复但 32 回归；循证收窄 0 改进——判别条件无区分力

**H-026 收束（用户决定）**: typed relational 方向暂停（算子激活缺口）。算子执行不是瓶颈，瓶颈在**生成层的选型决策**——模型在 evidence 呈现多个合法候选时选错。

**决定性架构事实（本次确认）**:
- `generate_answer_response`（generation.py:169）用 **`temperature=0.0`**（贪心单次 decode）→ 每次只做**一个确定性选型**，无多样性可聚合
- H-020 的 `_extract_then_select_answer` 已枚举 grounded candidates 再选，但也 temperature=0
- `complete()`（providers.py:190）接受 `temperature` 但只返回 `choices[0]` → 多样本 = N 次独立调用

## 假设

**在固定 evidence 上多次采样生成最终答案（temperature>0, N=5）并多数票聚合，能纠正 qwen3.6-27b 在 evidence 呈现多个合法候选时的选型错误**，从而回收 H-022 的 20 个选型失败样本——且不换模型、不训练。

**机制**: 当模型在候选 A/B 间犹豫（两个都在 evidence），贪心 decode 固定选错的一方；采样 N 次后多数票落在正确的一侧。Self-consistency 的经典文献结论（Wang et al. 2022; 2025 的 power-law scaling / Best-of-∞ 均验证）。

**价值**: 这是 H-022 之后唯一未被尝试、且直接攻击"选型天花板"的杠杆——H-005~H-020 全是提示/契约（温度 0），从未采样聚合。

## 干预设计

### 1. 新 flag: `sample_majority_vote: bool = False`（MethodSpec + generate_answer_response）

当 True：
- 对固定 evidence 生成 **N=5 个候选答案**（temperature>0）
- 规范化每个答案（lowercase/去标点/去冠词）
- **多数票**：取出现最多的答案；平票时取第一个出现的（稳定）
- 返回多数票答案

### 2. 生成路径（generation.py `generate_answer_response`）

在现有贪心路径旁加一个采样分支：
```python
if sample_majority_vote:
    candidates = []
    for _ in range(N):
        # 复用现有 messages（固定 evidence）
        response = client.complete(messages, temperature=0.7, ...)
        candidates.append(_tool_answer(...) or response.content.strip())
    answer = _majority_vote(candidates)   # 规范化 + Counter
    return answer, combined_response
```
- `N=5`：预算内（每次生成 ~2 tool-calls，5 次 ≈ 10，远低于 max_llm_calls=96）
- 结构化输出/thinking/fidelity 的现有分支全部保留，只在外层加采样循环
- **fallback**：若 N 次全部空 → 走现有 empty-retry（不丢失）

### 3. MethodSpec + 新方法（methods.py）

`slotrag-grounded-frontier-perpath-guard` + `sample_majority_vote=True`：
`slotrag-grounded-frontier-perpath-guard-samplevote`

### 4. 配置（configs/experiments/slotrag-phase3x-h027.yaml）

Tier 1: 2wiki+drop, n=20, seed=2027。guard（贪心）vs samplevote（采样多数票）。

## 验证方法

- **Tier 1** (n=20, 2wiki+drop): guard vs samplevote，配对可比（同 batch）
- **门禁**:
  - **选型失败回收**: 2wiki 中 H-022 式"gold 在 evidence 但贪心选错"样本，多数票后 F1 上升（重点盯比较二选一）
  - **无回归**: 全量 F1 不降（Δ ≥ -2pt），尤其 already-correct 样本不被多数票改错
  - **代价透明**: llm_calls 增加 ≤ N 倍，报告真实调用数
  - **drop**: 若 drop 算术题也被多数票改善则加分（但 drop 是 number 题，主要看是否无回归）

## 预期效果与风险

- **预期**: 2wiki 选型失败样本部分回收（多数票纠正犹豫性选错）；aggregate F1 +2~5pt
- **风险 1**: 多数票可能把 already-correct 的贪心答案改错（模型多数时候选错）→ 回归。缓解: 平票取第一个 + 只对非空采样聚合
- **风险 2**: temperature>0 引入格式噪声（结构化输出可能失败）→ 用 `_extract_then_select_answer` 的结构化路径保持候选 grounded
- **风险 3**: 成本（N×）超预算 → N=5 保守，max_llm_calls=96 充足
- **风险 4**: 若 qwen3.6-27b 在候选上"稳定地错"（多数票也错）→ 诚实否定，选型是真天花板

## 后续方向

- 通过 → 采样聚合是唯一不换模型可回收选型失败的杠杆 → 支撑 Tier 2 (n=100) 判断 Coverage
- 拒绝 → 选型失败是模型级硬天花板，Coverage 顶 40%，除非模型升级

## 不变量（约束）

- 只跑 DEVELOPMENT_SET（seed=2027, eval split, n=100×5），不 touch VALIDATION/TEST_SEALED
- 不换模型（qwen3.6-27b 不变）
- 无 dataset 名特判；type/question 驱动
- 诚实报告负结果（含多数票回归）

## Tier 1 结果（2026-08-07, n=20, 2wiki+drop, seed=2027, runs/slotrag-phase3x-h027-dev2）

**方法**: guard（贪心 temp=0）vs samplevote（guard + N=5 temp=0.7 采样多数票）。

| 维度 | 2wiki | drop | 门禁 |
|---|---|---|---|
| 全量 ΔF1 | **-6.07pt**（0.6869→0.6262） | 0.00pt（0.6194→0.6194） | ❌（Δ < -2pt 红线） |
| wins/losses/ties | 2/2/16 | 0/0/20 | n.s.（p=0.46） |
| 选型回收 | **1 真回收** + 1 部分 | 0 | ⚠️ 极弱 |
| once-correct 翻转 | **2**（f02e0a34 1.0→0, fa3e9b64 1.0→None） | 0 | ❌ |
| 成本 generation_llm_calls | 5.45×（treat 60 guard 11） | 5.00×（25 vs 5） | ⚠️ 如实 |

**判定: rejected。**

### 证据细节（2wiki, 20 配对中 16 一字不差）

- `89a3abec`（gold `Bello of Carcassonne`）: guard 选 `Oliba I of Carcassonne`（F1 0.571）→ vote 选 `Bello of Carcassonne`（**exact 1.0**）。**唯一真选型回收**——gold 在 evidence，贪心选错，多数票矫正。**证明机制可行。**
- `4c77c5a2`: list 3 项（F1 0.5）→ 单 `Australian National Film Board`（F1 0.857）部分改善。
- `f02e0a34` (gold `Domangart Réti`) guard 1.0 → **vote 翻转到 `Fergus Mór`（0.0）**。多数票里模型多数选了错候选 → 翻转已正确答。
- `fa3e9b64` (gold `Las Vegas, Nevada`) guard 1.0 → vote 路径 `budget_exceeded` → `None`（0.0）。

### 判决理由

1. **机制方向真实但极弱**: 20 样本仅 1 例 H-022 式选型回收（89a16279），且以破坏 2 个 already-correct 为代价（f02 翻转、fa 预算）。aggregate **-6.07pt**，远超 -2pt 门禁。
2. **多数票不比贪心稳定**: 迁移两个已有部分改善，被 f02 稳定错翻转抵消——qwen3.6-27b 在 multiple-candidate evidence 上"稳定地错"给多数票看的正是错候选。H-022 选型天花板未被打破，只把错误在候选间 shuffle。
3. **成本 5×** 未换来净收获（2wiki 5.45×, drop 5.00×）。
4. **drop 完全不变**: 算术题 majority vote = 单次（20/20 一字不差）→ 采样聚合对 drop 无作用（gold 是计算值，无候选可选）。

**架构结论**: 采样+多数票加剧已有模式（self-consistency 在模型"稳定地错"时反而危害）。**H-022 选型是模型级硬天花板，多数票不构成回收杠杆。Coverage 维持 4/10（40%），除非模型级升级或运行时编译器新方向。**
