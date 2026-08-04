.PHONY: help audit test budget state hypotheses experiments failures decisions sota related

help:  ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

audit:  ## 运行 Phase 0 审计
	PYTHONPATH=src:. python3 research/build_exposed_registry.py
	@echo "✅ EXPOSED_SAMPLE_REGISTRY.csv 已更新"

test:  ## 运行测试套件
	PYTHONPATH=src:. python3 -m pytest tests/ -x -q

budget:  ## 显示实验预算
	@cat research/EXPERIMENT_BUDGET.md

state:  ## 显示当前状态
	@cat research/STATE.md

hypotheses:  ## 显示假设池
	@cat research/HYPOTHESES.md

experiments:  ## 显示实验账本
	@column -t -s',' research/EXPERIMENT_LEDGER.csv

failures:  ## 显示失败账本
	@column -t -s',' research/FAILURE_LEDGER.csv

decisions:  ## 显示决策日志
	@cat research/DECISIONS.md

sota:  ## 显示 SOTA 账本
	@cat research/SOTA_LEDGER.md

related:  ## 显示相关工作矩阵
	@column -t -s',' research/RELATED_WORK_MATRIX.csv

clean:  ## 清理临时文件
	@echo "⚠️  不删除历史 runs 或 artifact"

.PHONY: phase1 phase2 phase3 phase4 phase5

phase1:  ## Phase 1: 研究基础设施
	@echo "Phase 1 状态:"
	@ls -la .claude/agents/*.md | wc -l
	@echo "agents 已创建"
	@ls -la research/*.md research/*.csv | wc -l
	@echo "账本文件已创建"

phase2:  ## Phase 2: SOTA 账本 (待启动)
	@echo "⚠️  Phase 2 待启动"

phase3:  ## Phase 3: 假设循环 (待启动)
	@echo "⚠️  Phase 3 待启动"

phase4:  ## Phase 4: 冻结验证 (待启动)
	@echo "⚠️  Phase 4 待启动"

phase5:  ## Phase 5: 论文 + Artifact (待启动)
	@echo "⚠️  Phase 5 待启动"
