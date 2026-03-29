"""Local RAG (Retrieval-Augmented Generation) engine for Project Memory MCP.

Uses TF-IDF with cosine similarity for semantic document retrieval.
The index is persisted to ``{root}/_rag_index.json`` and tracks each file's
modification time so that externally-modified files can be detected and
re-indexed automatically.

No external ML dependencies — pure Python stdlib only.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_FILE = "_rag_index.json"

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "it", "its",
        "this", "that", "these", "those", "i", "me", "my", "we", "our",
        "you", "your", "he", "him", "his", "she", "her", "they", "them",
        "their", "what", "which", "who", "not", "no", "so", "as", "if",
        "than", "too", "very", "just", "also", "more", "most", "then",
        "about", "up", "out", "over", "after", "before", "since",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

# Tolerance for floating-point mtime comparison (seconds)
_MTIME_TOLERANCE = 0.001

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Return lowercase tokens from *text*, stripping stopwords and short tokens."""
    return [
        t
        for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 2 and t not in _STOPWORDS
    ]


def term_frequency(tokens: list[str]) -> dict[str, float]:
    """Compute normalised term frequency (count / total tokens)."""
    if not tokens:
        return {}
    counts: Counter[str] = Counter(tokens)
    total = len(tokens)
    return {term: count / total for term, count in counts.items()}


def cosine_similarity(
    vec_a: dict[str, float], vec_b: dict[str, float]
) -> float:
    """Cosine similarity between two sparse float vectors represented as dicts."""
    dot = sum(vec_a.get(t, 0.0) * v for t, v in vec_b.items())
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# RAGEngine
# ---------------------------------------------------------------------------


class RAGEngine:
    """Local TF-IDF RAG index for the project memory filesystem.

    The index is stored at ``{root}/_rag_index.json`` and tracks per-file:

    * Term frequencies (``tf``)
    * File modification time at index time (``mtime``) — used to detect
      external modifications between server sessions.
    * ISO-8601 timestamp of when the file was last indexed (``indexed_at``).

    IDF weights are recomputed from the full corpus after every change.

    Usage::

        rag = RAGEngine(root)
        rag.rebuild()                          # index everything
        results = rag.search("authentication design")
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / INDEX_FILE
        # _docs: rel_path -> {"tf": {term: float}, "mtime": float, "indexed_at": str}
        self._docs: dict[str, dict[str, Any]] = {}
        self._idf: dict[str, float] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_file(self, path: Path) -> str:
        """Index (or re-index) a single *path*.

        Returns ``"indexed"`` when the file was (re-)indexed, or ``"skipped"``
        when it was unchanged or inaccessible.
        """
        if not path.is_file():
            return "skipped"
        try:
            mtime = path.stat().st_mtime
            rel = str(path.relative_to(self.root))
        except (OSError, ValueError):
            return "skipped"

        existing = self._docs.get(rel)
        if existing and abs(existing.get("mtime", 0.0) - mtime) < _MTIME_TOLERANCE:
            return "skipped"

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return "skipped"

        tokens = tokenize(text)
        self._docs[rel] = {
            "tf": term_frequency(tokens),
            "mtime": mtime,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._recompute_idf()
        self._save()
        return "indexed"

    def remove_file(self, path: Path) -> None:
        """Remove *path* from the index (e.g. after soft-delete)."""
        try:
            rel = str(path.relative_to(self.root))
        except ValueError:
            return
        if rel in self._docs:
            del self._docs[rel]
            self._recompute_idf()
            self._save()

    def rebuild(
        self,
        project_slug: Optional[str] = None,
        force: bool = False,
    ) -> dict[str, int]:
        """Index all ``.md`` files, skipping unchanged ones unless *force* is True.

        Scoped to a single project when *project_slug* is provided.

        Returns a counts dict with keys ``"indexed"``, ``"skipped"``, and ``"stale"``
        (stale = file has been modified externally since last indexing).

        Entries for deleted files are removed from the index automatically.
        """
        if project_slug:
            search_root = self.root / "projects" / project_slug
        else:
            search_root = self.root

        counts: dict[str, int] = {"indexed": 0, "skipped": 0, "stale": 0}
        trash_dir = self.root / "_trash"
        paths_seen: set[str] = set()

        for p in sorted(search_root.rglob("*.md")):
            if p.name.startswith("_"):
                continue
            if p.is_relative_to(trash_dir):
                continue
            try:
                rel = str(p.relative_to(self.root))
                mtime = p.stat().st_mtime
            except (OSError, ValueError):
                continue

            paths_seen.add(rel)
            existing = self._docs.get(rel)

            if existing and not force:
                if abs(existing.get("mtime", 0.0) - mtime) < _MTIME_TOLERANCE:
                    counts["skipped"] += 1
                    continue
                # File was externally modified
                counts["stale"] += 1
            else:
                counts["indexed"] += 1

            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            tokens = tokenize(text)
            self._docs[rel] = {
                "tf": term_frequency(tokens),
                "mtime": mtime,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

        # Remove stale entries for files that no longer exist
        for rel in list(self._docs.keys()):
            if rel not in paths_seen:
                full = self.root / rel
                if not full.exists():
                    del self._docs[rel]

        self._recompute_idf()
        self._save()
        return counts

    def search(
        self,
        query: str,
        project_slug: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Return up to *top_k* documents most relevant to *query*.

        Documents are ranked by TF-IDF cosine similarity.  Optionally scoped
        to a project slug.  Each result dict contains ``path``, ``score``, and
        ``indexed_at``.
        """
        if not self._docs:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        query_tf = term_frequency(query_tokens)
        query_tfidf = {
            term: tf_val * self._idf.get(term, 0.0)
            for term, tf_val in query_tf.items()
        }

        prefix: Optional[str] = None
        if project_slug:
            prefix = f"projects/{project_slug}/"

        results: list[dict[str, Any]] = []
        for rel, doc in self._docs.items():
            if prefix and not rel.startswith(prefix):
                continue
            doc_tfidf = {
                term: tf_val * self._idf.get(term, 0.0)
                for term, tf_val in doc["tf"].items()
            }
            score = cosine_similarity(query_tfidf, doc_tfidf)
            if score > 0.0:
                results.append(
                    {
                        "path": rel,
                        "score": round(score, 4),
                        "indexed_at": doc.get("indexed_at", ""),
                    }
                )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_stale_files(self) -> list[dict[str, Any]]:
        """Return indexed files whose on-disk mtime differs from the stored mtime.

        These are files that have been modified externally (outside the MCP
        server) since they were last indexed.
        """
        stale: list[dict[str, Any]] = []
        for rel, doc in self._docs.items():
            p = self.root / rel
            if not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if abs(mtime - doc.get("mtime", 0.0)) > _MTIME_TOLERANCE:
                stale.append(
                    {
                        "path": rel,
                        "indexed_at": doc.get("indexed_at", ""),
                        "last_modified": datetime.fromtimestamp(
                            mtime, tz=timezone.utc
                        ).isoformat(),
                    }
                )
        return stale

    def indexed_count(self) -> int:
        """Return the number of documents currently in the index."""
        return len(self._docs)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _recompute_idf(self) -> None:
        """Recompute IDF weights from the current document corpus.

        Uses smoothed IDF: ``log((N+1)/(df+1)) + 1`` to avoid zero division
        and to give some weight to rare terms.
        """
        n = len(self._docs)
        if n == 0:
            self._idf = {}
            return
        df: Counter[str] = Counter()
        for doc in self._docs.values():
            for term in doc["tf"]:
                df[term] += 1
        self._idf = {
            term: math.log((n + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }

    def _save(self) -> None:
        """Atomically persist the index to ``_rag_index.json``."""
        data: dict[str, Any] = {
            "version": 1,
            "docs": self._docs,
            "idf": self._idf,
        }
        tmp = self.index_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(data, separators=(",", ":")), encoding="utf-8"
            )
            tmp.replace(self.index_path)
        except OSError:
            pass

    def _load(self) -> None:
        """Load the index from disk.  No-op if the file does not exist yet."""
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._docs = data.get("docs", {})
            self._idf = data.get("idf", {})
        except (OSError, json.JSONDecodeError):
            self._docs = {}
            self._idf = {}
