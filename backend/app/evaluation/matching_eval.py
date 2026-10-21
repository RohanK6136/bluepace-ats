"""Offline evaluation utilities for ATS candidate matching.

This module deliberately does not call external models. It scores a fixed,
human-labelled benchmark so changes to prompts, embeddings, rerankers, or
weights can be compared reproducibly.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class MatchJudgement:
    query_id: str
    candidate_id: str
    relevance: int  # 0 = irrelevant, 1 = weak/partial, 2 = strong


def precision_at_k(items: list[MatchJudgement], k: int = 5, relevant_at: int = 2) -> float:
    top = items[: max(1, k)]
    return sum(item.relevance >= relevant_at for item in top) / len(top) if top else 0.0


def recall_at_k(items: list[MatchJudgement], total_relevant: int, k: int = 5, relevant_at: int = 2) -> float:
    if total_relevant <= 0:
        return 0.0
    top = items[: max(1, k)]
    found = sum(item.relevance >= relevant_at for item in top)
    return min(1.0, found / total_relevant)


def reciprocal_rank(items: list[MatchJudgement], relevant_at: int = 2) -> float:
    for index, item in enumerate(items, start=1):
        if item.relevance >= relevant_at:
            return 1.0 / index
    return 0.0


def brier_score(predicted_scores: list[float], judgements: list[MatchJudgement], positive_at: int = 2) -> float:
    if len(predicted_scores) != len(judgements) or not predicted_scores:
        return 0.0
    errors = []
    for score, judgement in zip(predicted_scores, judgements):
        probability = max(0.0, min(1.0, float(score) / 100.0))
        target = 1.0 if judgement.relevance >= positive_at else 0.0
        errors.append((probability - target) ** 2)
    return sum(errors) / len(errors)


def evaluate_ranked_query(
    query_id: str,
    ranked: list[dict],
    labels: list[MatchJudgement],
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> dict:
    label_by_candidate = {
        item.candidate_id: item
        for item in labels
        if item.query_id == query_id
    }
    ordered = [
        MatchJudgement(
            query_id=query_id,
            candidate_id=str(item["candidate_id"]),
            relevance=label_by_candidate.get(str(item["candidate_id"]), MatchJudgement(query_id, str(item["candidate_id"]), 0)).relevance,
        )
        for item in ranked
    ]
    total_relevant = sum(item.relevance >= 2 for item in label_by_candidate.values())
    metrics = {
        "query_id": query_id,
        "mrr": reciprocal_rank(ordered),
        "total_relevant": total_relevant,
        "brier": brier_score(
            [float(item.get("score", 0)) for item in ranked],
            ordered,
        ),
    }
    for k in k_values:
        metrics[f"precision_at_{k}"] = precision_at_k(ordered, k)
        metrics[f"recall_at_{k}"] = recall_at_k(ordered, total_relevant, k)
    return metrics


def aggregate_metrics(results: list[dict]) -> dict:
    if not results:
        return {"queries": 0}
    keys = [
        key for key in results[0]
        if key not in {"query_id", "total_relevant"}
    ]
    return {
        "queries": len(results),
        **{
            key: round(
                sum(float(row.get(key, 0.0)) for row in results) / len(results),
                4,
            )
            for key in keys
        },
        "total_relevant": sum(int(row.get("total_relevant", 0)) for row in results),
    }
