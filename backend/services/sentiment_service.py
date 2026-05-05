from typing import List, Dict

# Prevent Transformers from importing optional TensorFlow/JAX stacks on Windows.
# This avoids crashes when those stacks are installed but binary-incompatible with NumPy.
import os

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")

from transformers import pipeline


class SentimentAnalyzer:
    """Wrapper around Hugging Face sentiment pipeline."""

    def __init__(self) -> None:
        self.max_length = 512
        self._pipeline = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
        )

    def analyze(self, texts: List[str]) -> List[Dict[str, float]]:
        if not texts:
            return []
        results = self._pipeline(
            texts,
            truncation=True,
            max_length=self.max_length,
        )
        normalized = []
        for r in results:
            label = r.get("label", "NEUTRAL").upper()
            if label not in {"POSITIVE", "NEGATIVE"}:
                label = "NEUTRAL"
            normalized.append({"label": label, "score": float(r.get("score", 0.0))})
        return normalized

