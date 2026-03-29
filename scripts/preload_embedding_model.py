"""Preload/download sentence-transformers model into local cache.

Usage:
    python scripts/preload_embedding_model.py
    python scripts/preload_embedding_model.py --model all-MiniLM-L6-v2
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rag import DEFAULT_EMBEDDING_MODEL, RAG_BACKEND_EMBEDDINGS, RAGEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and preload embedding model for Project Memory RAG"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("./memory-root"),
        help="Memory root path (default: ./memory-root)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"Sentence-Transformers model name (default: {DEFAULT_EMBEDDING_MODEL})",
    )
    args = parser.parse_args()

    rag = RAGEngine(
        args.root.resolve(),
        backend=RAG_BACKEND_EMBEDDINGS,
        embedding_model=args.model,
    )
    print(f"[rag] Preloading embedding model '{args.model}'...")
    rag.warmup()
    print("[rag] Embedding model is ready.")


if __name__ == "__main__":
    main()
