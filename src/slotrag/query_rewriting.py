"""Query rewriting for multi-hop retrieval — LLM-driven slot query enrichment.

Rewrites slot queries to be more search-effective by expanding entity
references, adding contextual clues, and incorporating temporal constraints.
Designed to improve BM25/dense recall for complex multi-hop questions where
the raw slot query lacks discriminative terms.
"""

from __future__ import annotations

import json
from typing import Any

from .providers import AgnesClient


# Lean system prompt — optimized for throughput (single-turn, no chain-of-thought)
_REWRITE_PROMPT = (
    "You are a search query specialist. Rewrite the given slot query to maximize "
    "retrieval recall in a Wikipedia document corpus. Return ONLY the rewritten "
    "search query — no explanation, no prefix, no quotes."
    "\n\n"
    "Guidelines:\n"
    "- Expand pronouns and entity references with concrete names from context\n"
    "- Include temporal clues (years, decades) when present in the question\n"
    "- Add synonyms and alternative phrasings for key terms\n"
    "- Omit plan variables (?x, ?y) — use natural language instead\n"
    "- Keep the query concise (8-20 words)\n"
    "- If the slot query is already well-formed, return it unchanged"
)


class QueryRewriter:
    """Rewrites slot queries to improve retrieval recall for multi-hop questions.

    Uses a single lightweight LLM call per slot. The rewriter is stateless and
    thread-safe (it wraps a shared AgnesClient under a lock).

    Example:
        slot_query = "?x is father of Cecil Michaelis"
        question = "Where was the father of Cecil Michaelis born?"
        bindings = {}
        → "Cecil Michaelis father Cecil Michaelis parent biography"
    """

    def __init__(self, client: AgnesClient) -> None:
        self.client = client

    def rewrite(
        self,
        slot_query: str,
        question_context: str,
        bindings: dict[str, str],
    ) -> str:
        """Produce a search-optimized query string.

        Args:
            slot_query: Raw slot query from the plan (may contain ?variables).
            question_context: The original user question.
            bindings: Already-resolved bindings for this slot.

        Returns:
            Rewritten query string, or the original slot_query if rewriting
            produces an empty or near-identical result.
        """
        # Skip rewriting for trivial slot queries (single entity lookups)
        cleaned = slot_query.replace("?", "").strip()
        if len(cleaned) < 8 and not any(c.isdigit() for c in cleaned):
            return slot_query

        # Build user message
        user_content = (
            f"Original question: {question_context}\n"
            f"Slot query: {slot_query}"
        )
        if bindings:
            user_content += f"\nKnown entities: {json.dumps(bindings, ensure_ascii=False)}"
        user_content += "\n\nRewritten search query:"

        messages = [
            {"role": "system", "content": _REWRITE_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = self.client.complete(
            messages,
            temperature=0.0,
            max_tokens=96,
            enable_thinking=False,  # Disable thinking for speed — we want a concise query only
        )
        rewritten = (response.content or "").strip().strip("\"'")

        # Guard: don't return an empty or trivial rewrite
        if not rewritten or rewritten.lower() == cleaned.lower():
            return slot_query

        # Guard: strip thinking artifacts
        if rewritten.startswith("Here's") or "thinking" in rewritten[:30].lower():
            # Extract just the rewritten query from within the thinking output
            lines = rewritten.split("\n")
            for line in reversed(lines):
                line = line.strip().strip("\"'")
                if line and not line.startswith("Here") and "thinking" not in line.lower()[:20]:
                    rewritten = line
                    break

        if not rewritten:
            return slot_query

        return rewritten
