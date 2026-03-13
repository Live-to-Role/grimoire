"""Hybrid search combining semantic vectors with keyword (BM25) scores."""


def reciprocal_rank_fusion(
    semantic_results: list[tuple[int, float]],
    keyword_results: list[tuple[int, float]],
    k: int = 60,
    semantic_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> list[tuple[int, float]]:
    """
    Merge two ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF scores each item as: sum(weight / (k + rank)) across lists.
    Items appearing in both lists get boosted naturally.

    Args:
        semantic_results: (product_id, score) sorted by score desc
        keyword_results: (product_id, score) sorted by score desc
        k: RRF constant (higher = less emphasis on top ranks; 60 is standard)
        semantic_weight: Weight multiplier for semantic ranks
        keyword_weight: Weight multiplier for keyword ranks

    Returns:
        Merged (product_id, rrf_score) sorted by rrf_score desc
    """
    scores: dict[int, float] = {}

    for rank, (pid, _) in enumerate(semantic_results):
        scores[pid] = scores.get(pid, 0.0) + semantic_weight / (k + rank + 1)

    for rank, (pid, _) in enumerate(keyword_results):
        scores[pid] = scores.get(pid, 0.0) + keyword_weight / (k + rank + 1)

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return merged
