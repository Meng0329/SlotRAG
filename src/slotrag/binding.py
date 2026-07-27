"""Adaptive binding-beam selection for physical slot execution."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

from pydantic import Field

from .models import BindingRow, StrictModel


class BindingCandidate(StrictModel):
    source_id: str
    context_key: tuple[tuple[str, str], ...]
    score: float
    evidence_confidence: float
    join_compatibility: float
    source_diversity: float
    downstream_reachability: float
    duplicate_penalty: float
    estimated_execution_cost: float


class BindingBeamDecision(StrictModel):
    width: int = Field(ge=1)
    uncertainty: float = Field(ge=0, le=1)
    selected: list[BindingRow]
    candidates: list[BindingCandidate]
    considered_count: int = Field(ge=0)
    pruned_count: int = Field(ge=0)
    pruned_source_ids: list[str] = Field(default_factory=list)
    correct_path_pruned: bool = False


def _context_key(row: BindingRow, relevant_variables: set[str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (key, str(value))
        for key, value in row.bindings.items()
        if not relevant_variables or key in relevant_variables
    ))


class AdaptiveBindingBeam:
    """Rank and size binding contexts using observable execution signals.

    The selector is deliberately independent of the executor. It deduplicates equivalent
    binding contexts first, then increases the beam only when the top candidates are
    ambiguous or when a larger beam is affordable.
    """

    def __init__(self, *, min_width: int = 1, max_width: int = 8) -> None:
        if min_width < 1 or max_width < min_width:
            raise ValueError("binding beam widths must satisfy 1 <= min_width <= max_width")
        self.min_width = min_width
        self.max_width = max_width

    @staticmethod
    def _candidate_score(
        row: BindingRow,
        *,
        relevant_variables: set[str],
        source_counts: dict[str, int],
    ) -> BindingCandidate:
        values = [str(value).strip() for value in row.bindings.values()]
        non_empty = sum(bool(value) for value in values)
        downstream_reachability = (
            sum(bool(str(row.bindings.get(name, "")).strip()) for name in relevant_variables)
            / len(relevant_variables)
            if relevant_variables
            else 1.0
        )
        join_compatibility = 1.0 if downstream_reachability == 1.0 else downstream_reachability
        source_diversity = 1.0 / max(source_counts[row.source_id], 1)
        duplicate_penalty = max(source_counts[row.source_id] - 1, 0) / max(source_counts[row.source_id], 1)
        estimated_execution_cost = 1.0 / max(non_empty, 1)
        score = (
            0.55 * row.confidence
            + 0.15 * join_compatibility
            + 0.10 * source_diversity
            + 0.10 * downstream_reachability
            - 0.05 * duplicate_penalty
            - 0.05 * estimated_execution_cost
        )
        return BindingCandidate(
            source_id=row.source_id,
            context_key=(),
            score=score,
            evidence_confidence=row.confidence,
            join_compatibility=join_compatibility,
            source_diversity=source_diversity,
            downstream_reachability=downstream_reachability,
            duplicate_penalty=duplicate_penalty,
            estimated_execution_cost=estimated_execution_cost,
        )

    def select(
        self,
        rows: Sequence[BindingRow],
        *,
        relevant_variables: Iterable[str] = (),
        budget_remaining: int | None = None,
        oracle_contexts: set[tuple[tuple[str, str], ...]] | None = None,
    ) -> BindingBeamDecision:
        if not rows:
            return BindingBeamDecision(
                width=self.min_width,
                uncertainty=0.0,
                selected=[],
                candidates=[],
                considered_count=0,
                pruned_count=0,
            )
        variables = set(relevant_variables)
        source_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            source_counts[row.source_id] += 1

        # Retain only the strongest row for each downstream binding context.
        best_by_context: dict[tuple[tuple[str, str], ...], tuple[BindingRow, BindingCandidate]] = {}
        for row in rows:
            key = _context_key(row, variables)
            candidate = self._candidate_score(row, relevant_variables=variables, source_counts=source_counts)
            candidate = candidate.model_copy(update={"context_key": key})
            current = best_by_context.get(key)
            if current is None or (candidate.score, row.confidence, row.source_id) > (
                current[1].score,
                current[0].confidence,
                current[0].source_id,
            ):
                best_by_context[key] = (row, candidate)

        ranked = sorted(
            best_by_context.values(),
            key=lambda item: (item[1].score, item[1].evidence_confidence, item[0].source_id),
            reverse=True,
        )
        top_score = ranked[0][1].evidence_confidence
        second_score = ranked[1][1].evidence_confidence if len(ranked) > 1 else top_score
        uncertainty = max(0.0, min(1.0, 1.0 - max(top_score - second_score, 0.0)))
        budget = self.max_width if budget_remaining is None else max(int(budget_remaining), 1)
        max_width = min(self.max_width, budget, len(ranked))
        if uncertainty >= 0.75:
            width = max_width
        elif uncertainty >= 0.45:
            width = min(max_width, max(self.min_width, 2))
        else:
            width = min(max_width, self.min_width)
        selected_pairs = ranked[:width]
        selected = [row for row, _candidate in selected_pairs]
        selected_keys = {_context_key(row, variables) for row in selected}
        selected_source_ids = {row.source_id for row in selected}
        pruned_rows = [
            row for row in rows
            if row.source_id not in selected_source_ids
            or _context_key(row, variables) not in selected_keys
        ]
        correct_path_pruned = bool(oracle_contexts and not oracle_contexts.intersection(selected_keys))
        return BindingBeamDecision(
            width=width,
            uncertainty=uncertainty,
            selected=selected,
            candidates=[candidate for _row, candidate in ranked],
            considered_count=len(ranked),
            pruned_count=len(pruned_rows),
            pruned_source_ids=[row.source_id for row in pruned_rows],
            correct_path_pruned=correct_path_pruned,
        )


__all__ = ["AdaptiveBindingBeam", "BindingBeamDecision", "BindingCandidate"]
