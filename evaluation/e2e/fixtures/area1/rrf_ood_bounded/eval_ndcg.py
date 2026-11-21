"""Deterministic NDCG@10 evaluator for RRF vs linear fusion OOD benchmark."""
import math


def ndcg_at_k(relevances: list[float], k: int = 10) -> float:
    dcg = sum((2.0 ** rel - 1.0) / math.log2(idx + 2) for idx, rel in enumerate(relevances[:k]))
    ideal = sorted(relevances, reverse=True)
    idcg = sum((2.0 ** rel - 1.0) / math.log2(idx + 2) for idx, rel in enumerate(ideal[:k]))
    return dcg / idcg if idcg > 0 else 0.0
