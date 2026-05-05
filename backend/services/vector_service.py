from __future__ import annotations

import json
import os
from typing import List, Dict, Any, Tuple

import faiss
import numpy as np


class VectorService:
    """FAISS-based vector index with simple metadata storage."""

    def __init__(self, index_path: str = "vector_index.faiss", meta_path: str | None = None) -> None:
        self.index_path = index_path
        self.meta_path = meta_path or f"{index_path}.meta.json"
        self.index: faiss.Index | None = None
        self.metadata: List[Dict[str, Any]] = []
        self._load()

    # --------------------------------------------------------------------- #
    # Persistence helpers
    # --------------------------------------------------------------------- #
    def _load(self) -> None:
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
        if os.path.exists(self.meta_path):
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)

    def _save(self) -> None:
        if self.index is not None:
            faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    # --------------------------------------------------------------------- #
    # Core operations
    # --------------------------------------------------------------------- #
    def _ensure_index(self, dim: int) -> None:
        if self.index is None:
            self.index = faiss.IndexFlatL2(dim)

    def add_embeddings(self, embeddings: np.ndarray, metadata: List[Dict[str, Any]]) -> None:
        if embeddings.size == 0:
            return
        self._ensure_index(embeddings.shape[1])
        self.index.add(embeddings.astype("float32"))
        self.metadata.extend(metadata)
        self._save()

    def search(
        self, query_embedding: np.ndarray, top_k: int = 5
    ) -> List[Tuple[float, Dict[str, Any]]]:
        if self.index is None or self.index.ntotal == 0:
            return []
        query_embedding = np.asarray(query_embedding, dtype="float32").reshape(1, -1)
        distances, indices = self.index.search(query_embedding, min(top_k, self.index.ntotal))
        results: List[Tuple[float, Dict[str, Any]]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            results.append((float(dist), self.metadata[idx]))
        return results

