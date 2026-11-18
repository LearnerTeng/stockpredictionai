"""1536-dimensional embeddings; provider/model/input recipe jointly identify a version."""
from math import isfinite
import os

DIMENSIONS = 1536


class OpenAIEmbedder:
    def __init__(self):
        self.model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        if self.model not in {"text-embedding-3-small", "text-embedding-3-large"}:
            raise ValueError("unsupported embedding model")
        self.version = f"openai:{self.model}:{DIMENSIONS}:cl100k-8000-v1"

    def embed(self, texts):
        import tiktoken
        from openai import OpenAI
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for vector generation")
        encoder = tiktoken.get_encoding("cl100k_base")
        inputs = [encoder.encode(t, disallowed_special=())[:8000] for t in texts]
        if any(not item for item in inputs):
            raise ValueError("empty embedding input")
        client = OpenAI(api_key=key, timeout=45, max_retries=1)
        result = client.embeddings.create(model=self.model, input=inputs, dimensions=DIMENSIONS, encoding_format="float")
        rows = sorted(result.data, key=lambda row: row.index)
        if [r.index for r in rows] != list(range(len(texts))):
            raise ValueError("embedding response count/index mismatch")
        vectors = [validate_vector(row.embedding) for row in rows]
        return vectors, int(result.usage.total_tokens)


def validate_vector(vector):
    values = [float(v) for v in vector]
    if len(values) != DIMENSIONS or any(not isfinite(v) for v in values) or sum(v*v for v in values) <= 0:
        raise ValueError("invalid embedding dimensions or values")
    return values
