"""Deterministic lexical baseline and optional real semantic embeddings.

Hash embeddings are explicitly NOT a semantic model. Their role is an offline
control. Local E5 or an OpenAI-compatible embedding endpoint enables dense RAG.
"""
from collections import Counter
import hashlib
import math
import re
import numpy as np
import httpx


def tokens(text: str) -> list[str]:
    text = text.lower()
    latin = re.findall(r"[a-z0-9_./:-]+", text)
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    return latin + [part[i:i + 2] for part in chinese for i in range(max(0, len(part) - 1))]


def hash_vector(text: str, dimension: int = 384) -> list[float]:
    vector = np.zeros(dimension)
    for token, count in Counter(tokens(text)).items():
        index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % dimension
        vector[index] += 1 + math.log(count)
    norm = np.linalg.norm(vector)
    return (vector / norm if norm else vector).tolist()


class Embedder:
    def __init__(self, provider="hash", model="intfloat/multilingual-e5-small", base_url="", key=""):
        if provider not in {"hash", "fastembed", "openai"}:
            raise ValueError("Unknown embedding provider")
        self.provider, self.model, self.base_url, self.key = provider, model, base_url, key
        self.local = None
        self.fingerprint = f"{provider}:{model if provider != 'hash' else 'sha256-384-v1'}"

    def embed(self, texts: list[str], query=False) -> list[list[float]]:
        if not texts:
            return []
        if self.provider == "hash":
            return [hash_vector(text) for text in texts]
        if self.provider == "fastembed":
            if self.local is None:
                from fastembed import TextEmbedding
                self.local = TextEmbedding(model_name=self.model)
            method = self.local.query_embed if query else self.local.passage_embed
            return [np.asarray(v).tolist() for v in method(texts)]
        with httpx.Client(timeout=45) as client:
            response = client.post(self.base_url.rstrip("/") + "/embeddings", headers={"Authorization": f"Bearer {self.key}"}, json={"model": self.model, "input": texts})
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            if len(rows) != len(texts):
                raise ValueError("Embedding response count mismatch")
            return [row["embedding"] for row in rows]


def bm25(query: str, documents: list[str]) -> list[float]:
    bags = [Counter(tokens(doc)) for doc in documents]
    n = len(bags)
    average = sum(sum(b.values()) for b in bags) / max(n, 1) or 1
    scores = [0.0] * n
    for term in set(tokens(query)):
        frequency = sum(term in bag for bag in bags)
        idf = math.log(1 + (n - frequency + .5) / (frequency + .5))
        for i, bag in enumerate(bags):
            tf = bag[term]
            if tf:
                scores[i] += idf * tf * 2.5 / (tf + 1.5 * (.25 + .75 * sum(bag.values()) / average))
    return scores


def cosine(query_vector, vectors):
    if not vectors:
        return []
    matrix = np.asarray(vectors, dtype=float)
    q = np.asarray(query_vector, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(q):
        raise ValueError("Embedding dimensions changed: reindex required")
    denominator = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
    return np.divide(matrix @ q, denominator, out=np.zeros(len(vectors)), where=denominator > 0).tolist()


def rank(scores, k):
    return sorted((i for i, score in enumerate(scores) if score > 0), key=lambda i: (-scores[i], i))[:k]


def rrf(rankings, constant=60):
    fused = Counter()
    for ranking in rankings:
        for position, index in enumerate(ranking, 1):
            fused[index] += 1 / (constant + position)
    return sorted(fused, key=lambda index: (-fused[index], index)), dict(fused)


def query_route(query):
    # Precise identifier matching is the justification, not a vague difficulty label.
    if re.search(r"\b(?:ERR[_-][A-Z0-9_]+|[A-Z]+_TIMEOUT|HTTP\s*[45]\d\d)\b", query):
        return "bm25", "检测到错误码/配置标识符，优先精确匹配"
    return "hybrid", "自然语言描述，融合词项与向量召回"
