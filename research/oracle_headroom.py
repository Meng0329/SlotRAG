#!/usr/bin/env python3
"""Four-level Oracle Headroom analysis for SlotRAG H-007.

Nested oracle model (each oracle subsumes the ones before it):
  Source Oracle   — perfect retrieval: all gold sources reach the candidate pool.
                    Fixes S0. Any sample whose FIRST failure is S0 is recoverable.
  Span Oracle     — perfect span extraction: gold spans from retrieved sources
                    always make it into the evidence bundle. Fixes S0–S3.
                    Recovers S1, S2, S3.
  Candidate Oracle— perfect binding generation: gold answers always appear among
                    extracted bindings. Fixes S0–S5. Recovers S4, S5.
  Path Oracle     — perfect selection + generation: the correct bound entity is
                    always chosen and emitted with exact EM. Fixes S0–S8.
                    Recovers S6, S7, S8.

Therefore the "first-loss stage" classification from ANSWER_PIPELINE_AUDIT maps
directly to oracle headroom:
  stage <= Oracle level  =>  recoverable by that oracle.
For each oracle level, the recoverable EM = (# samples with first-loss stage
at or before that level) / total.

Note: this is a UPPER BOUND. An oracle may be imperfectly realized in practice
(e.g. perfect retrieval may still yield wrong spans). The value here is the
structural headroom: how much EM is theoretically on the table per failure class.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

# oracle level → recoverable stages
ORACLE_STAGES = {
    "source":   {"S0"},
    "span":     {"S0", "S1", "S2", "S3"},
    "candidate": {"S0", "S1", "S2", "S3", "S4", "S5"},
    "path":     {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"},
}

# stage → oracle level that would fix it (for the summary table)
STAGE_ORACLE = {
    "S0": "source",
    "S1": "span",
    "S2": "span",
    "S3": "span",
    "S4": "candidate",
    "S5": "candidate",
    "S6": "path",
    "S7": "path",
    "S8": "path",
    "S9": None,  # unresolvable → no oracle fixes
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default="research/ANSWER_PIPELINE_AUDIT.csv")
    ap.add_argument("--datasets", nargs="*", default=["hotpotqa", "2wikimultihop", "musique"])
    ap.add_argument("--out-md", default="research/ORACLE_HEADROOM.md")
    ap.add_argument("--out-csv", default="research/ORACLE_HEADROOM.csv")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.audit)))
    per_ds = defaultdict(list)
    for r in rows:
        if r["dataset"] in args.datasets:
            per_ds[r["dataset"]].append(r)

    summary_rows = []
    md_lines = [
        "# ORACLE_HEADROOM.md — 四级 Oracle Headroom 分析",
        "",
        "> **数据**: H-007 DEVELOPMENT_SET (seed=2027) 阶段分类",
        "> **方法**: 首失败点 → 嵌套 oracle 上限回收",
        f"> **生成时间**: (见 git log)",
        "",
        "## 1. 四级 Oracle 定义",
        "",
        "| Oracle | 修复阶段 | 含义 |",
        "|--------|----------|------|",
        "| Source | S0 | 完美检索：gold source 全进候选 |",
        "| Span | S0-S3 | 完美 span：gold span 进 evidence bundle |",
        "| Candidate | S0-S5 | 完美绑定：gold 答案出现在绑定中 |",
        "| Path | S0-S8 | 完美选择+生成：EM 精确输出 |",
        "",
        "> ⚠️ 这是**结构上界**，非实际可回收值。真实 oracle 实现可能不完美。",
        "",
        "## 2. 各级 Oracle 可回收 EM（当前部分数据）",
        "",
        "| Dataset | n | 当前 EM | Source+EM | Span+EM | Cand+EM | Path+EM |",
        "|---------|---|---------|-----------|---------|---------|---------|",
    ]

    for ds in args.datasets:
        d_rows = per_ds.get(ds, [])
        if not d_rows:
            continue
        n = len(d_rows)
        cur_em = sum(1 for r in d_rows if float(r["em"]) >= 1.0)
        stages = Counter(r["stage"] for r in d_rows)

        def oracle_em(level_stages):
            # level_stages are prefixes like "S0"; the actual stage names are
            # like "S0_GOLD_SOURCE_NOT_RETRIEVED". Match on the S- prefix.
            return cur_em + sum(
                count for stage, count in stages.items()
                if any(stage.startswith(prefix) for prefix in level_stages)
            )

        source_em = oracle_em(ORACLE_STAGES["source"])
        span_em = oracle_em(ORACLE_STAGES["span"])
        cand_em = oracle_em(ORACLE_STAGES["candidate"])
        path_em = oracle_em(ORACLE_STAGES["path"])

        md_lines.append(
            f"| {ds} | {n} | {cur_em}/{n} ({100*cur_em/n:.1f}%) "
            f"| {source_em} ({100*source_em/n:.1f}%) "
            f"| {span_em} ({100*span_em/n:.1f}%) "
            f"| {cand_em} ({100*cand_em/n:.1f}%) "
            f"| {path_em} ({100*path_em/n:.1f}%) |"
        )

        summary_rows.append({
            "dataset": ds,
            "n": n,
            "current_em": cur_em,
            "current_em_pct": round(100*cur_em/n, 1),
            "source_oracle_em": source_em,
            "source_oracle_em_pct": round(100*source_em/n, 1),
            "span_oracle_em": span_em,
            "span_oracle_em_pct": round(100*span_em/n, 1),
            "candidate_oracle_em": cand_em,
            "candidate_oracle_em_pct": round(100*cand_em/n, 1),
            "path_oracle_em": path_em,
            "path_oracle_em_pct": round(100*path_em/n, 1),
        })

    md_lines.extend([
        "",
        "## 3. 首失败点 → 对应 Oracle 回收（每样本）",
        "",
        "| 首失败阶段 | 可修复的 Oracle | 说明 |",
        "|------------|----------------|------|",
        "| S0 | Source | 检索漏掉 gold source |",
        "| S1/S2/S3 | Span | 检索对但 span/束丢失 |",
        "| S4/S5 | Candidate | 绑定提取错/不完整 |",
        "| S6/S7/S8 | Path | 选择/生成措辞错 |",
        "| S9 | 无 | 无法归因 |",
        "",
        "## 4. 关键读法",
        "",
        "- **Source Oracle 与 Span Oracle 的差距** = 检索对但证据束丢失的损失（Span 特有的回收）",
        "- **Span 与 Candidate 的差距** = 绑定提取损失的答案",
        "- **Candidate 与 Path 的差距** = 最终选择/措辞损失的答案",
        "- **Path Oracle 与 100% 的差距** = S9 无法归因 + 数据本身错误",
        "",
    ])

    Path(args.out_md).write_text("\n".join(md_lines))

    with open(args.out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    print(f"Wrote {args.out_md} and {args.out_csv}")
    for r in summary_rows:
        print(
            f"{r['dataset']:12s} n={r['n']:3d} cur={r['current_em_pct']:5.1f}% "
            f"source={r['source_oracle_em_pct']:5.1f}% span={r['span_oracle_em_pct']:5.1f}% "
            f"cand={r['candidate_oracle_em_pct']:5.1f}% path={r['path_oracle_em_pct']:5.1f}%"
        )


if __name__ == "__main__":
    main()
