"""Minimal in-memory BM25 index for lexical retrieval.

No external dependencies — good enough for the fake/test path and small
corpora.  Production replaces this with the lexical side of Azure AI
Search or Elasticsearch.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class _DocEntry:
    clause_id: str
    text: str
    tf: Counter[str]
    length: int


@dataclass
class BM25Index:
    """BM25 (Okapi) index over ingested chunks."""

    k1: float = 1.5
    b: float = 0.75
    _docs: dict[str, _DocEntry] = field(default_factory=dict)
    _df: Counter[str] = field(default_factory=Counter)
    _avg_dl: float = 0.0

    def add(self, clause_id: str, text: str) -> None:
        """Index a chunk."""
        tokens = _tokenise(text)
        tf = Counter(tokens)
        entry = _DocEntry(clause_id=clause_id, text=text, tf=tf, length=len(tokens))
        if clause_id in self._docs:
            old = self._docs[clause_id]
            for t in old.tf:
                self._df[t] -= 1
                if self._df[t] <= 0:
                    del self._df[t]
        self._docs[clause_id] = entry
        for t in tf:
            self._df[t] += 1
        self._recompute_avg()

    def search(self, query: str, *, top_k: int = 10) -> list[tuple[str, float]]:
        """Return ``(clause_id, score)`` pairs sorted descending by BM25 score."""
        tokens = _tokenise(query)
        if not tokens or not self._docs:
            return []

        n = len(self._docs)
        scores: list[tuple[str, float]] = []

        for doc in self._docs.values():
            score = 0.0
            for t in tokens:
                if t not in doc.tf:
                    continue
                df = self._df.get(t, 0)
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                tf_val = doc.tf[t]
                numerator = tf_val * (self.k1 + 1)
                denominator = tf_val + self.k1 * (1 - self.b + self.b * doc.length / self._avg_dl)
                score += idf * numerator / denominator
            if score > 0:
                scores.append((doc.clause_id, score))

        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:top_k]

    @property
    def doc_count(self) -> int:
        return len(self._docs)

    def _recompute_avg(self) -> None:
        if self._docs:
            self._avg_dl = sum(d.length for d in self._docs.values()) / len(self._docs)
        else:
            self._avg_dl = 0.0


_TOKEN_RE = re.compile(r"[a-z0-9§]+(?:\.[0-9]+)*")


def _tokenise(text: str) -> list[str]:
    """Lower-case tokenise, keeping clause-ID-shaped tokens like ``§1.2``."""
    return _TOKEN_RE.findall(text.lower())
