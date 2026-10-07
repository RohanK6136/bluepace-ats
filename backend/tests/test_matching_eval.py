import json
from pathlib import Path

from app.evaluation.matching_eval import MatchJudgement, aggregate_metrics, evaluate_ranked_query


FIXTURE = Path(__file__).resolve().parents[1] / "evaluation" / "golden_matches.json"


def test_golden_matching_benchmark_has_expected_metrics_shape():
    data = json.loads(FIXTURE.read_text())
    all_results = []
    for case in data:
        labels = [
            MatchJudgement(
                query_id=case["query_id"],
                candidate_id=item["candidate_id"],
                relevance=item["relevance"],
            )
            for item in case["candidates"]
        ]
        ranked = [
            {"candidate_id": item["candidate_id"], "score": item["score"]}
            for item in sorted(case["candidates"], key=lambda item: item["score"], reverse=True)
        ]
        all_results.append(evaluate_ranked_query(case["query_id"], ranked, labels))

    metrics = aggregate_metrics(all_results)

    assert metrics["queries"] == 3
    assert metrics["precision_at_1"] == 1.0
    assert metrics["recall_at_3"] >= metrics["recall_at_1"]
    assert 0.0 <= metrics["brier"] <= 1.0
