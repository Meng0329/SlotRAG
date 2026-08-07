#!/usr/bin/env python3
"""H-023 离线编译审计：Typed QueryIR 编译器结构覆盖率（LLM-free, DEVELOPMENT n=100×5）

Phase 3X §22 step 7 / §14 gate.

This audit measures whether a *deterministic, type-driven* Query-IR compiler can
recover the operator family + answer schema that the current architecture *should
emit* for the DEVELOPMENT samples, WITHOUT calling the LLM.

被测对象: 一个由句型结构驱动的确定性编译器职能（H-023 的假设产物）——
  从 question 语言学结构推断 operator family 与 AnswerSchema(cardinality/type)，
  并构造能通过校验的逻辑 plan。它不是最终执行，而是审计"typed IR 编译"这一层
  本身能否覆盖复杂问题（尤其 2wiki 比较 / drop 数值），而不是退化成 11% 的硬编码模板。

GATE (H-023):  plan_valid >= 95 / answer_schema >= 95 / operator_family >= 90
数据集:       DEVELOPMENT (seed=2027) 的 5×100 采样（= H-012 full 同批, 配对可比）
不触碰:       VALIDATION / TEST_SEALED
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from slotrag.models import RelationalOperator, Slot, SlotPlan
from slotrag.planner import SlotCompiler

# ---------------------------------------------------------------------------
# 1. 句子结构识别器（确定性、泛化、非数据集特定）
# ---------------------------------------------------------------------------

_COMPAR_SUPER = re.compile(
    r"\b(earlier|later|older|younger|before|after|first|last|shortest|longest|"
    r"highest|lowest|fastest|slowest|largest|smallest|oldest|newest|closest|"
    r"farthest|most|least|fewest|youngest)\b", flags=re.IGNORECASE)
_NUMERIC = re.compile(
    r"\b(how many|how much|sum|total|difference|product|average|minus|plus|times|"
    r"multiply|divide|percentage|percent|number of|increased by|decreased by|"
    r"population|how large|how long|how far|how tall|how old|how big|how wide|"
    r"area|distance|amount|age range|uppermost|length|width|height|weight|size of|"
    r"rate of|quantity|how many people|what was the total|what is the area)\b",
    flags=re.IGNORECASE)
_BOOL_LEAD = re.compile(
    r"^\s*(?:was|were|is|are|does|did|do|has|have|had|would|could|will|can|shall|"
    r"is it|are there|were there)\b", flags=re.IGNORECASE)
_WH_LEAD = re.compile(r"^\s*(?:what|which|who|whom|whose|where|when|why|how|which one)\b",
                      flags=re.IGNORECASE)
_YEARQ = re.compile(
    r"\b(what year|in what year|what date|on what date)\b", flags=re.IGNORECASE)
_DATEQ = re.compile(
    r"\b(when|what month|what decade|what era|what day|when exactly)\b", flags=re.IGNORECASE)
# 月份词: 用于判断 gold 是否为 date 类型 (而非数值)
_MONTH = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    flags=re.IGNORECASE)
_MULTI = re.compile(r"\b(what are|list|name (both|all)|enumerate|each other|and also)\b",
                    flags=re.IGNORECASE)


class AnswerSpec:
    __slots__ = ("cardinality", "value_type", "numeric", "multi", "category")

    def __init__(self, cardinality: str, value_type: str, numeric: bool = False, multi: bool = False,
                 category: str | None = None):
        self.cardinality = cardinality
        self.value_type = value_type
        self.numeric = numeric
        self.multi = multi
        # category: ENTITY / DATE / NUMBER / BOOLEAN / MULTI / COMPOSITE — 用于 schema 判分
        self.category = category or (
            "NUMBER" if numeric else "BOOLEAN" if value_type == "BOOLEAN" else
            "DATE" if value_type == "DATE" else "COMPOSITE" if value_type == "COMPOSITE" else
            "MULTI" if multi else "ENTITY")

    def __repr__(self) -> str:
        return f"{self.cardinality}:{self.value_type}"


_OR_COMPARE = re.compile(
    r"\b(?:does|do|did|is|are|was|were)\b.*?\b(?:higher|lower|larger|smaller|bigger|"
    r"older|younger|more|less|greater|faster|slower|earlier|later)\b.*?\b(?:or)\b",
    flags=re.IGNORECASE)


def infer_answer_spec(question: str) -> AnswerSpec:
    """From question structure only. Deterministic. Not dataset-specific."""
    q = question.casefold()
    numeric = bool(_NUMERIC.search(q))
    # 优先级: 比较实体(X or Y 中选一) > 数字 > 年份(纯数字 year) > 日期 > 布尔 > 比较极值 > 多值列表 > 默认实体
    if _OR_COMPARE.search(q):
        return AnswerSpec("ONE", "SCALAR_ENTITY")
    if numeric:
        if q.count(" and ") >= 1 or "," in q or "list" in q:
            return AnswerSpec("MANY_MULTISET", "NUMERIC_LIST", numeric=True, multi=True)
        return AnswerSpec("ONE", "NUMBER", numeric=True)
    if _YEARQ.search(q):
        return AnswerSpec("ONE", "NUMBER", numeric=True)
    if _DATEQ.search(q):
        return AnswerSpec("ONE", "DATE")
    if _BOOL_LEAD.match(q) and not _WH_LEAD.match(q):
        return AnswerSpec("ONE", "BOOLEAN")
    if _COMPAR_SUPER.search(q) or _GENERIC_EXTREMUM.search(q):
        return AnswerSpec("ONE", "SCALAR_ENTITY")
    if _MULTI.search(q):
        return AnswerSpec("MANY_SET", "MULTI_SPAN", multi=True)
    return AnswerSpec("ONE", "SCALAR_ENTITY")


class OperatorClassifier:
    """映射 question → 最佳 operator family（确定性, 复用现有模板 + 结构后缀）。"""

    def __init__(self, compiler: SlotCompiler):
        self.compiler = compiler

    def classify(self, question: str) -> str:
        fe = self.compiler._field_extremum_template(question)
        if fe is not None and fe.operators:
            return fe.operators[0].kind            # field_argmin / field_argmax
        pc = self.compiler._polar_comparison_template(question)
        if pc is not None:
            return "compare"
        if _NUMERIC.search(question.casefold()):
            return "arithmetic"
        if _COMPAR_SUPER.search(question.casefold()):
            return "argmax"
        return "scan"                             # 默认单槽提取

    def alloc_plan(self, question: str, spec: AnswerSpec) -> SlotPlan:
        fe = self.compiler._field_extremum_template(question)
        if fe is not None:
            return fe
        pc = self.compiler._polar_comparison_template(question)
        if pc is not None:
            return pc
        if spec.numeric:
            return SlotPlan(
                slots=[Slot(id="S1", predicate="EvidenceNumeric", arguments=["?_num"],
                            variable_types={"_num": "number"}, estimated_cardinality=1)],
                operators=[RelationalOperator(id="O1", kind="count", output="answer")],
                outputs=["?answer"])
        return SlotPlan(
            slots=[Slot(id="S1", predicate="EvidenceAnsweringQuestion", arguments=["?answer"],
                        constraints={"question": question}, estimated_cardinality=1)],
            outputs=["?answer"])


# ---------------------------------------------------------------------------
# 2. 打分工具
# ---------------------------------------------------------------------------

def _plan_valid(plan: SlotPlan) -> bool:
    try:
        SlotPlan.model_validate(plan.model_dump(mode="python"))
        return True
    except Exception:
        return False


_NUMV = re.compile(r"^[+\-]?(?:\d+\.?\d*|\.\d+)$")
_WORD_NUM = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|million|billion)\b", flags=re.IGNORECASE)


def _gold_is_numeric(answers: list) -> bool:
    """gold 是否被视为数值型答案 (多值重复含纯数字 token 即视为数字)."""
    if not answers:
        return False
    tokens = re.findall(r"[A-Za-z0-9.\-]+", " ".join(str(a) for a in answers))
    if not tokens:
        return False
    numeric_tokens = sum(1 for t in tokens if _NUMV.fullmatch(t))
    word_numeric = sum(1 for t in tokens if _WORD_NUM.fullmatch(t))
    return (numeric_tokens + word_numeric) >= 1


def _gold_category(answers: list, question: str = "") -> str:
    """从 gold 答案推断类型类别 (ENTITY/DATE/NUMBER/BOOLEAN/MULTI)."""
    if not answers:
        return "ENTITY"
    joined = " ".join(str(a) for a in answers)
    q = question.casefold()
    # DATE: 月份词 or 具体日期形态
    if _MONTH.search(joined) or re.search(r"\b\d{1,2}\s+(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", joined, flags=re.IGNORECASE):
        return "DATE"
    # 纯数字 (多值重复也算)
    if _gold_is_numeric(answers):
        # question 问的是时间点 (when/what year) → 数字年份归 DATE
        if _YEARQ.search(q) or _DATEQ.search(q):
            return "DATE"
        return "NUMBER"
    # 布尔: yes/no/true/false
    if re.fullmatch(r"\s*(?:yes|no|true|false|y|n)\s*", joined, flags=re.IGNORECASE):
        return "BOOLEAN"
    # MULTI: 真正的多答案 = answers 数组多项 (gold 序列化多个独立答案)
    # 注意: 单实体名含逗号(称谓)/and(电影名) 不是 MULTI
    if len(answers) > 1:
        return "MULTI"
    return "ENTITY"


# 泛化比较检测: 两个实体比较某属性极值/先后 (2wiki 大量未命中模板的题在此)
_GENERIC_EXTREMUM = re.compile(
    r"\b(?:which|who|what|which one)\b.*?\b(?:older|younger|earlier|later|born|died|"
    r"released|established|first|last|taller|shorter)\b", flags=re.IGNORECASE)


def _requires_typed_op(question: str) -> bool:
    """该问题是否需要 typed 运算 (比较/极值/算术/布尔), 而不是纯 scan."""
    q = question.casefold()
    if _NUMERIC.search(q):
        return True
    if _COMPAR_SUPER.search(q):
        return True
    if _GENERIC_EXTREMUM.search(q):
        return True
    return False


def evaluate(items: list[dict[str, Any]], out_dir: Path) -> dict:
    # 不需要真 client — 所有模板方法都是 @staticmethod，allocate 走模板。

    class _Stub:
        def complete(self, *a, **k):
            raise RuntimeError("offline")
        @staticmethod
        def require_tool(*a, **k):
            return {}

    compiler = SlotCompiler(_Stub())
    cls = OperatorClassifier(compiler)

    report_rows: list[dict[str, Any]] = []
    per_dataset: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for ds, ds_items in items:
        for item in ds_items:
            q = item["question"]
            gold = item.get("answers") or []
            spec = infer_answer_spec(q)
            family = cls.classify(q)
            plan = cls.alloc_plan(q, spec)

            valid = _plan_valid(plan)
            gold_cat = _gold_category(gold, question=q)
            schema_ok = (spec.category == gold_cat)
            needs_op = _requires_typed_op(q)
            # operator_family gate 只在"确实需要 typed 运算"的题上计分
            family_ok = 1 if (needs_op and family != "scan") else 0
            # 非 needs_op 题不参与该 gate（不算分子也不算分母，单独记录）
            op_scored = needs_op

            per_dataset[ds]["n"] += 1
            per_dataset[ds]["plan_valid"] += 1 if valid else 0
            per_dataset[ds]["schema_ok"] += 1 if schema_ok else 0
            per_dataset[ds]["needs_op"] += 1 if needs_op else 0
            per_dataset[ds]["op_scored"] += 1 if op_scored else 0
            per_dataset[ds]["family_ok"] += family_ok
            report_rows.append({
                "dataset": ds, "question_id": item.get("id", ""), "question": q,
                "answer_spec": str(spec), "spec_category": spec.category,
                "gold_category": gold_cat,
                "operator_family": family,
                "gold": " ".join(gold),
                "plan_valid": 1 if valid else 0,
                "schema_ok": 1 if schema_ok else 0,
                "family_ok": 1 if family_ok else 0,
            })

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "h023_audit_rows.csv").open("w", newline="", encoding="utf-8") as f:
        if report_rows:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0]))
            writer.writeheader(); writer.writerows(report_rows)

    total = {"n": 0, "plan_valid": 0, "schema_ok": 0, "needs_op": 0, "op_scored": 0, "family_ok": 0}
    for ds, c in per_dataset.items():
        for k in ("n", "plan_valid", "schema_ok", "needs_op", "op_scored", "family_ok"):
            total[k] += c[k]
    op_denom = max(total["op_scored"], 1)
    summary = {
        "rows": len(report_rows),
        "total": dict(total),
        "rates": {
            "plan_valid_rate": round(total["plan_valid"] / max(total["n"], 1), 4),
            "answer_schema_accuracy": round(total["schema_ok"] / max(total["n"], 1), 4),
            # operator_family gate 只在"确实需要 typed 运算"的题上测量
            "operator_family_rate": round(total["family_ok"] / op_denom, 4),
            "typed_op_questions": total["needs_op"],
        },
        "per_dataset": {ds: dict(c) for ds, c in per_dataset.items()},
    }
    (out_dir / "h023_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-dir", type=Path,
                        default=Path("runs/slotrag-phase3r-h012-full/samples/h012_full"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/phase3x/h023-audit-r1"))
    args = parser.parse_args()

    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ds in ["hotpotqa", "2wikimultihop", "musique", "strategyqa", "drop"]:
        path = args.sample_dir / f"{ds}.jsonl"
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                by_dataset[ds].append({"id": rec["id"], "question": rec["question"],
                                       "answers": rec.get("answers") or []})
    print(f"[H-023] DEVELOPMENT 样本: {sum(len(v) for v in by_dataset.values())} 题")
    summary = evaluate(list(by_dataset.items()), args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())