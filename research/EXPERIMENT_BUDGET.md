# EXPERIMENT_BUDGET.md — 阶段 1+ 实验预算

> **预算制定时间**: 2026-08-04  
> **预算依据**: Phase 0 审计结果、历史运行数据、硬件配置  
> **预算状态**: 待用户确认

---

## 1. 硬件配置

| 资源 | 配置 |
|------|------|
| CPU | 64 cores |
| RAM | 128 GB (系统可用 62 GB) |
| GPU | 2× NVIDIA RTX A6000 (49 GB VRAM each) |
| 存储 | ext4, 483K+401K passages index |
| 网络 | 内网 10.200.37.71 (LLM/Embedding/Reranker endpoint) |

---

## 2. LLM 调用预算

### 2.1 单次实验成本估算

| 组件 | 每题调用次数 | 每次调用 tokens (估) | 总 tokens/题 |
|------|-------------|---------------------|--------------|
| SlotRAG planning | 1-3 | 2048 | 2048-6144 |
| SlotRAG generation | 1 | 2048 | 2048 |
| Hybrid reranking | 1 | 1024 | 1024 |
| **总计** | 3-5 | - | **5120-9216** |

### 2.2 全量实验成本

| 实验规模 | 样本数 | 预计调用次数 | 预计 tokens | 预计费用 (¥) |
|----------|--------|-------------|-------------|-------------|
| Tier 2 (初步) | 100/dataset × 5 | 1,500-2,500 | 7.7M-23M | 0.77-2.3 |
| Tier 3 (验证) | 500/dataset × 5 | 7,500-12,500 | 38M-115M | 3.8-11.5 |
| Tier 4 (最终) | 1000/dataset × 5 | 15,000-25,000 | 77M-230M | 7.7-23 |
| **总计** | - | 24,000-40,000 | 123M-368M | **12.3-36.8** |

> **注**: 费用基于 qwen3.6-27b internal endpoint (10.200.37.71:8801)，无外部 API 费用。

---

## 3. Wall-Clock 时间预算

### 3.1 单题处理时间

| 组件 | 平均时间/题 |
|------|------------|
| SlotRAG planning | 5-15s |
| SlotRAG retrieval | 2-5s |
| SlotRAG generation | 3-8s |
| Hybrid reranking | 1-2s |
| **总计** | **11-30s** |

### 3.2 全量实验时间

| 实验规模 | 样本数 | 并发数 | 预计时间 |
|----------|--------|--------|----------|
| Tier 2 (初步) | 500 | 4 | 23-63 min |
| Tier 3 (验证) | 2,500 | 4 | 2-5 hours |
| Tier 4 (最终) | 5,000 | 4 | 4-10 hours |
| **总计** | 8,000 | - | **6-16 hours** |

> **注**: 并发数受 LLM endpoint 限制 (agnes_provider_rpm=300, agnes_max_concurrency=16)。

---

## 4. GPU 预算

| 用途 | VRAM 占用 | 时间 |
|------|----------|------|
| Embedding (Qwen3-Embedding-0.6B) | ~2 GB | 全程 |
| Reranker (bge-reranker-v2-m3) | ~2 GB | 全程 |
| **总计** | **~4 GB** | - |

> **注**: SlotRAG 使用 LLM endpoint (CPU inference)，不占用本地 GPU。

---

## 5. 内存预算

| 组件 | 内存占用 |
|------|---------|
| Passage index (hotpotqa 483K) | 4.5 GB (mmap) |
| Passage index (2wiki 401K) | ~4 GB (mmap) |
| 单 worker dense 检索 | +1.8 GB |
| 3 worker 并发 | 瞬态 20-28 GB (gc 后回落 6.4 GB) |
| **系统 RAM** | **128 GB** |

> **注**: 已实现内存感知滑动窗口，3 并发时瞬态峰值 >10GB，但系统 RAM 充足，绝不 OOM。

---

## 6. 超时与自动终止

### 6.1 超时设置

| 类型 | 超时时间 |
|------|---------|
| 单题 LLM 调用 | 60s |
| 单题总处理 | 300s |
| 单阶段总运行 | 24 hours |
| 全实验总运行 | 72 hours |

### 6.2 自动终止条件

1. **内存超限**: RSS > 120 GB → 强制终止
2. **LLM 连续失败**: 连续 10 次调用失败 → 暂停并报告
3. **时间超限**: 单阶段 > 24h → 自动终止
4. **用户中断**: SIGTERM → 保存 checkpoint 并退出

---

## 7. 并发控制

| 参数 | 值 |
|------|-----|
| max_concurrency (SlotRAG) | 4 |
| agnes_max_concurrency (LLM) | 16 |
| embedding_max_concurrency | 16 |
| reranker_max_concurrency | 16 |
| WINDOW_MAX_WORKERS (memory-aware) | 3 |

> **注**: 实际并发受内存限制，3 workers 时 RSS 稳定 ~6.4GB。

---

## 8. 失败处理

### 8.1 失败分类

| 类型 | 处理方式 |
|------|---------|
| LLM timeout | 重试 2 次，失败标记为 timeout |
| LLM rate limit | 指数退避，最多重试 3 次 |
| 检索失败 | 标记为 retrieval_failed，继续处理 |
| 规划失败 (no join path) | 标记为 planning_failed，继续处理 |
| 内存不足 | 暂停新任务，等待内存释放 |

### 8.2 失败样本处理

- **不排除失败样本**: 保留在结果中，报告 status='failed'
- **统计分析**: 使用 valid_n (非 failed) 进行 EM/F1 计算
- **主表报告**: 必须报告 valid_n / total_n

---

## 9. 预算审批流程

### 9.1 需要用户审批的节点

1. **Tier 2 启动前**: 确认初步实验预算
2. **Tier 3 启动前**: 确认验证实验预算
3. **Tier 4 启动前**: 确认最终实验预算
4. **费用超限**: 任何阶段费用超预算 20% → 暂停并报告

### 9.2 预算监控

- 每 100 题报告: 已用时间、已用 tokens、预计总费用
- 每阶段结束报告: 实际 vs 预算对比

---

## 10. 实验目录结构

```
runs/
├── slotrag-v75-sealed-eval-hotpotqa/    # Tier 2 hotpotqa
├── slotrag-v75-sealed-eval-2wiki/       # Tier 2 2wiki
├── slotrag-v75-sealed-eval-musique/     # Tier 2 musique
├── slotrag-v75-sealed-eval-strategyqa/  # Tier 2 strategyqa
├── slotrag-v75-sealed-eval-drop/        # Tier 2 drop
├── slotrag-v75-validation-hotpotqa/     # Tier 3 hotpotqa
├── slotrag-v75-validation-2wiki/        # Tier 3 2wiki
├── ...                                  # Tier 3 其他数据集
├── slotrag-v75-final-hotpotqa/          # Tier 4 hotpotqa
├── slotrag-v75-final-2wiki/             # Tier 4 2wiki
├── ...                                  # Tier 4 其他数据集
└── baseline-v75-sealed-eval/            # baseline SEALED_FINAL_SET 结果
```

---

## 11. 预算总结

| 项目 | 预算 | 备注 |
|------|------|------|
| LLM tokens | 368M | 上限 |
| LLM 费用 | ¥36.8 | 上限 (internal endpoint) |
| Wall-clock | 72 hours | 全实验上限 |
| GPU VRAM | 4 GB | 全程 |
| 内存 | 128 GB | 系统上限 |
| 失败率 | <10% | 目标 |

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM endpoint 不可用 | 实验暂停 | 备用 endpoint (如有) |
| 内存 OOM | 进程被杀 | 滑动窗口 + 自动终止 |
| 时间超限 | 实验未完成 | 分阶段运行，保存 checkpoint |
| 失败率过高 | 统计功效不足 | 增加样本量，报告 CI |

---

*预算制定完成时间: 2026-08-04*  
*预算依据: Phase 0 审计、历史运行数据、硬件配置*  
*待用户确认后生效*
