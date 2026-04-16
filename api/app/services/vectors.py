from __future__ import annotations

import hashlib
import math

from google import genai

from app.core.config import Settings


class VectorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    def embed(self, text: str) -> list[float]:
        if self.client and self.settings.extraction_provider in {"auto", "gemini"}:
            try:
                response = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text,
                )
                embedding = response.embeddings[0].values
                return [float(item) for item in embedding]
            except Exception:
                return self._fallback_embedding(text)
        return self._fallback_embedding(text)

    def _fallback_embedding(self, text: str, dimensions: int = 64) -> list[float]:
        vector = [0.0] * dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(item * item for item in vector))
        if magnitude == 0:
            return vector
        return [round(item / magnitude, 6) for item in vector]
