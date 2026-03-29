"""Local RAG (Retrieval-Augmented Generation) engine for Project Memory MCP.

Supports two backends, selected at server start-up via the ``backend``
parameter of :class:`RAGEngine`:

* ``"tfidf"`` (default) — Pure-Python TF-IDF, **no extra dependencies**.
* ``"embeddings"`` — Sentence-Transformers + numpy vector store.  Requires
  ``sentence-transformers`` to be installed::

      pip install sentence-transformers

  The first time an embedding model is used it will be downloaded from
  HuggingFace Hub (typically a few hundred MB).  Subsequent runs use the
  locally-cached model.

Both backends share the same public interface and store their index next to
the memory root:

* TF-IDF:   ``{root}/_rag_index.json``
* Embeddings: ``{root}/_rag_embeddings.json``

Both detect externally-modified files by comparing the stored ``mtime``
against the current on-disk modification time.
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
# Public constants
# ---------------------------------------------------------------------------

RAG_BACKEND_TFIDF = "tfidf"
RAG_BACKEND_EMBEDDINGS = "embeddings"

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Private constants
# ---------------------------------------------------------------------------

_TFIDF_INDEX_FILE = "_rag_index.json"
_EMBEDDINGS_INDEX_FILE = "_rag_embeddings.json"

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
# Public helper functions (used by TF-IDF backend; also importable for tests)
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
# Shared helpers
# ---------------------------------------------------------------------------


def _iter_indexable_files(search_root: Path, root: Path):
    """Yield (path, rel, mtime) tuples for indexable .md files under *search_root*."""
    trash_dir = root / "_trash"
    for p in sorted(search_root.rglob("*.md")):
        if p.name.startswith("_"):
            continue
        if p.is_relative_to(trash_dir):
            continue
        try:
            rel = p.relative_to(root).as_posix()
            mtime = p.stat().st_mtime
        except (OSError, ValueError):
            continue
        yield p, rel, mtime


# ---------------------------------------------------------------------------
# TF-IDF backend
# ---------------------------------------------------------------------------


class _TFIDFBackend:
    """Pure-Python TF-IDF retrieval backend.

    Stores term frequencies and IDF weights in ``{root}/_rag_index.json``.
    No external dependencies required.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / _TFIDF_INDEX_FILE
        # rel_path -> {"tf": {term: float}, "mtime": float, "indexed_at": str}
        self._docs: dict[str, dict[str, Any]] = {}
        self._idf: dict[str, float] = {}
        self._load()

    # -- public API ----------------------------------------------------------

    def index_file(self, path: Path) -> str:
        if not path.is_file():
            return "skipped"
        try:
            mtime = path.stat().st_mtime
            rel = path.relative_to(self.root).as_posix()
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
        try:
            rel = path.relative_to(self.root).as_posix()
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
        search_root = (
            self.root / "projects" / project_slug if project_slug else self.root
        )
        counts: dict[str, int] = {"indexed": 0, "skipped": 0, "stale": 0}
        paths_seen: set[str] = set()

        for p, rel, mtime in _iter_indexable_files(search_root, self.root):
            paths_seen.add(rel)
            existing = self._docs.get(rel)

            if existing and not force:
                if abs(existing.get("mtime", 0.0) - mtime) < _MTIME_TOLERANCE:
                    counts["skipped"] += 1
                    continue
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

        for rel in list(self._docs.keys()):
            if rel not in paths_seen and not (self.root / rel).exists():
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

        prefix = f"projects/{project_slug}/" if project_slug else None
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
        return len(self._docs)

    # -- private helpers -----------------------------------------------------

    def _recompute_idf(self) -> None:
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
        data: dict[str, Any] = {
            "version": 1,
            "docs": self._docs,
            "idf": self._idf,
        }
        _atomic_write(self.index_path, data)

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._docs = data.get("docs", {})
            self._idf = data.get("idf", {})
        except (OSError, json.JSONDecodeError):
            self._docs = {}
            self._idf = {}


# ---------------------------------------------------------------------------
# Embeddings backend
# ---------------------------------------------------------------------------


class _EmbeddingsBackend:
    """Sentence-Transformers + numpy vector store backend.

    Encodes each document as a dense embedding vector using a local
    sentence-transformer model and computes cosine similarity at query time.

    Requires ``sentence-transformers``::

        pip install sentence-transformers

    The model is loaded lazily on first use and cached in memory.  If the
    configured *model_name* differs from the one stored in the index, the
    index is discarded and rebuilt from scratch on the next
    :meth:`rebuild` call.

    Embeddings are persisted to ``{root}/_rag_embeddings.json`` as lists of
    floats (one per document).
    """

    def __init__(self, root: Path, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.root = root
        self.model_name = model_name
        self.index_path = root / _EMBEDDINGS_INDEX_FILE
        # rel_path -> {"embedding": [float, ...], "mtime": float, "indexed_at": str}
        self._docs: dict[str, dict[str, Any]] = {}
        self._model = None  # loaded lazily
        self._load()

    # -- public API ----------------------------------------------------------

    def index_file(self, path: Path) -> str:
        if not path.is_file():
            return "skipped"
        try:
            mtime = path.stat().st_mtime
            rel = path.relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return "skipped"

        existing = self._docs.get(rel)
        if existing and abs(existing.get("mtime", 0.0) - mtime) < _MTIME_TOLERANCE:
            return "skipped"

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return "skipped"

        embedding = self._encode(text)
        self._docs[rel] = {
            "embedding": embedding,
            "mtime": mtime,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        return "indexed"

    def remove_file(self, path: Path) -> None:
        try:
            rel = path.relative_to(self.root).as_posix()
        except ValueError:
            return
        if rel in self._docs:
            del self._docs[rel]
            self._save()

    def rebuild(
        self,
        project_slug: Optional[str] = None,
        force: bool = False,
    ) -> dict[str, int]:
        search_root = (
            self.root / "projects" / project_slug if project_slug else self.root
        )
        counts: dict[str, int] = {"indexed": 0, "skipped": 0, "stale": 0}
        paths_seen: set[str] = set()

        for p, rel, mtime in _iter_indexable_files(search_root, self.root):
            paths_seen.add(rel)
            existing = self._docs.get(rel)

            if existing and not force:
                if abs(existing.get("mtime", 0.0) - mtime) < _MTIME_TOLERANCE:
                    counts["skipped"] += 1
                    continue
                counts["stale"] += 1
            else:
                counts["indexed"] += 1

            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            embedding = self._encode(text)
            self._docs[rel] = {
                "embedding": embedding,
                "mtime": mtime,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

        for rel in list(self._docs.keys()):
            if rel not in paths_seen and not (self.root / rel).exists():
                del self._docs[rel]

        self._save()
        return counts

    def search(
        self,
        query: str,
        project_slug: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not self._docs:
            return []

        import numpy as np  # guaranteed present when sentence-transformers is installed

        query_emb = np.array(self._encode(query), dtype=float)
        query_norm = float(np.linalg.norm(query_emb))
        if query_norm == 0.0:
            return []
        query_emb_normalized = query_emb / query_norm

        prefix = f"projects/{project_slug}/" if project_slug else None
        results: list[dict[str, Any]] = []
        for rel, doc in self._docs.items():
            if prefix and not rel.startswith(prefix):
                continue
            doc_emb = np.array(doc["embedding"], dtype=float)
            doc_norm = float(np.linalg.norm(doc_emb))
            if doc_norm == 0.0:
                continue
            score = float(np.dot(query_emb_normalized, doc_emb / doc_norm))
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
        return len(self._docs)

    # -- private helpers -----------------------------------------------------

    def _get_model(self):
        """Lazily load and cache the sentence-transformer model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "The 'embeddings' RAG backend requires 'sentence-transformers'. "
                    "Install it with:  pip install sentence-transformers"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _encode(self, text: str) -> list[float]:
        """Encode *text* to a dense embedding vector (list of floats)."""
        model = self._get_model()
        emb = model.encode(text, convert_to_numpy=True)
        return emb.tolist()

    def _save(self) -> None:
        data: dict[str, Any] = {
            "version": 1,
            "model_name": self.model_name,
            "docs": self._docs,
        }
        _atomic_write(self.index_path, data)

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._docs = {}
            return
        # Discard index if it was built with a different model
        if data.get("model_name") != self.model_name:
            self._docs = {}
            return
        self._docs = data.get("docs", {})


# ---------------------------------------------------------------------------
# Shared atomic-write helper
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# RAGEngine — public facade
# ---------------------------------------------------------------------------


class RAGEngine:
    """Unified RAG engine — selects a backend at construction time.

    Parameters
    ----------
    root:
        Memory filesystem root directory.
    backend:
        ``"tfidf"`` (default) or ``"embeddings"``.
    embedding_model:
        Sentence-Transformers model name used when *backend* is
        ``"embeddings"`` (default: ``"all-MiniLM-L6-v2"``).
        Ignored for the ``"tfidf"`` backend.

    Raises
    ------
    ValueError
        If *backend* is not one of the supported values.

    Examples
    --------
    TF-IDF (no extra dependencies)::

        rag = RAGEngine(root)

    Sentence-Transformers embeddings::

        rag = RAGEngine(root, backend="embeddings")
        rag = RAGEngine(root, backend="embeddings", embedding_model="all-mpnet-base-v2")
    """

    def __init__(
        self,
        root: Path,
        backend: str = RAG_BACKEND_TFIDF,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        if backend == RAG_BACKEND_EMBEDDINGS:
            self._impl: _TFIDFBackend | _EmbeddingsBackend = _EmbeddingsBackend(
                root, model_name=embedding_model
            )
        elif backend == RAG_BACKEND_TFIDF:
            self._impl = _TFIDFBackend(root)
        else:
            raise ValueError(
                f"Unknown RAG backend {backend!r}. "
                f"Valid options: {RAG_BACKEND_TFIDF!r}, {RAG_BACKEND_EMBEDDINGS!r}."
            )
        self.backend = backend
        self.root = root

    # ------------------------------------------------------------------
    # Delegated public API
    # ------------------------------------------------------------------

    def index_file(self, path: Path) -> str:
        """Index (or re-index) a single *path*.

        Returns ``"indexed"`` when the file was (re-)indexed, or ``"skipped"``
        when it was unchanged or inaccessible.
        """
        return self._impl.index_file(path)

    def remove_file(self, path: Path) -> None:
        """Remove *path* from the index (e.g. after soft-delete)."""
        self._impl.remove_file(path)

    def rebuild(
        self,
        project_slug: Optional[str] = None,
        force: bool = False,
    ) -> dict[str, int]:
        """Index all ``.md`` files, skipping unchanged ones unless *force* is True.

        Scoped to a single project when *project_slug* is provided.

        Returns a counts dict with keys ``"indexed"``, ``"skipped"``, and
        ``"stale"`` (stale = file modified externally since last indexing).

        Entries for deleted files are removed automatically.
        """
        return self._impl.rebuild(project_slug=project_slug, force=force)

    def search(
        self,
        query: str,
        project_slug: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Return up to *top_k* documents most relevant to *query*.

        Optionally scoped to a project slug.  Each result dict contains
        ``path``, ``score``, and ``indexed_at``.
        """
        return self._impl.search(query, project_slug=project_slug, top_k=top_k)

    def get_stale_files(self) -> list[dict[str, Any]]:
        """Return indexed files whose on-disk mtime differs from the stored mtime."""
        return self._impl.get_stale_files()

    def indexed_count(self) -> int:
        """Return the number of documents currently in the index."""
        return self._impl.indexed_count()
