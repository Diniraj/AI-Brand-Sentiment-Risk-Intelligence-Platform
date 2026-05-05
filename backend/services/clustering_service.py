from typing import Dict, Any

import numpy as np
from sklearn.cluster import KMeans


class ClusteringService:
    """Simple KMeans-based topic clustering."""

    def __init__(self, max_clusters: int = 5) -> None:
        self.max_clusters = max_clusters

    def cluster(self, embeddings: np.ndarray) -> Dict[str, Any]:
        n_samples = embeddings.shape[0]
        if n_samples < 2:
            return {"labels": [], "n_clusters": 0}

        n_clusters = min(self.max_clusters, max(2, n_samples // 2))
        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
        labels = km.fit_predict(embeddings)
        clusters: Dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(int(label), []).append(int(idx))
        return {
            "labels": labels.tolist(),
            "clusters": clusters,
            "n_clusters": n_clusters,
        }

