# ORACLE_HEADROOM.md — 四级 Oracle Headroom 分析（最终版）

> **数据**: H-007 DEVELOPMENT_SET (seed=2027, 完整 300 样本)  
> **方法**: 首失败点 → 嵌套 oracle 上限回收  
> **分析脚本**: `research/oracle_headroom.py`  
> **状态**: ✅ 完整（3 数据集 × 100）

---

## 1. 四级 Oracle 定义

| Oracle | 修复阶段 | 含义 |
|--------|----------|------|
| Source | S0 | 完美检索：gold source 全进候选池 |
| Span | S0-S3 | 完美证据捆绑：gold source 选入 evidence bundle |
| Candidate | S0-S5 | 完美绑定：gold 答案出现在绑定中 |
| Path | S0-S8 | 完美选择+生成：EM 精确输出 |

> ⚠️ 这是**结构上界**。真实 oracle 实现可能不完美（如完美检索可能仍产生坏 span）。

---

## 2. 各级 Oracle 可回收 EM（完整结果）

| Dataset | n | 当前 EM | Source+EM | Span+EM | Cand+EM | Path+EM |
|---------|---|---------|-----------|---------|---------|---------|
| hotpotqa | 100 | 52/100 (52.0%) | 52 (52.0%) | **82 (82.0%)** | 95 (95.0%) | 100 |
| 2wikimultihop | 100 | 68/100 (68.0%) | 72 (72.0%) | **87 (87.0%)** | 97 (97.0%) | 100 |
| musique | 100 | 36/100 (36.0%) | 36 (36.0%) | 51 (51.0%) | **94 (94.0%)** | 100 |

### 各级 headroom（相对当前 EM 的增量）

| Dataset | Source | Span | Candidate | Path |
|---------|--------|------|-----------|------|
| hotpotqa | +0 | **+30** | +13 | +5 |
| 2wikimultihop | +4 | **+19** | +10 | +3 |
| musique | +0 | +15 | **+58** | +6 |

---

## 3. 瓶颈层级（跨数据集一致结论）

1. **Candidate Oracle（绑定）在 musique 上最大（+58）** — musique 的 43 个 S5 绑定丢失主导
2. **Span Oracle（捆绑）在 hotpotqa/2wiki 上最大（+30/+19）** — evidence bundle 丢失 gold source
3. **Source Oracle（检索）几乎无空间（0/+4/0）** — gold source 基本都进候选池
4. **Path Oracle（生成）在所有数据集上最小（+3~6）** — 反驳"生成是瓶颈"

---

## 4. 关键结论

### 4.1 推翻旧 STOP_REPORT
- ❌ "生成是瓶颈"（H-004）: Path 层仅 +3~6%，**不成立**
- ❌ "方向 C（答案消歧）最优": 答案消歧解决 Path 层，headroom 最小
- ❌ "检索不是瓶颈"（正确但原因错）: 检索确实不是瓶颈，但**不是因为生成好**，而是因为 gold source 都进候选池了——真正丢失在**捆绑和绑定**

### 4.2 真正的瓶颈
- **hotpotqa/2wiki**: evidence bundle 构建（Span 层）— gold source 检索到、选入，但第 2 个 gold source 被束丢弃
- **musique**: 绑定提取（Candidate 层）— 多跳下绑定选错实体

### 4.3 对方向选择的启示
- **方向 C（答案消歧）** 直接解决 S6/S8（Path 层），但 headroom 最小 → **不是最优**
- **方向 A（改进生成推理）** 部分覆盖 S8，也非最优
- **未考虑的层**: Span（bundle 构建）和 Candidate（绑定）才是最大空间

---

*分析完成: 2026-08-05*  
*数据完整性: ✅ 3×100 全部完成，无 failed*
