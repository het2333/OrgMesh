import pytest

from onyx.evals.chinese_retrieval.metrics import evaluate_rankings
from onyx.evals.chinese_retrieval.models import EvaluationQuery


def test_metrics_measure_document_recall_and_first_relevant_rank() -> None:
    queries = [
        EvaluationQuery(id="q1", query="报销", relevant_document_ids=["a", "b"]),
        EvaluationQuery(id="q2", query="休假", relevant_document_ids=["c"]),
    ]
    result = evaluate_rankings(
        queries, {"q1": ["x", "a", "a", "b"], "q2": ["c"]}, [1, 3]
    )
    assert result.recall_at_k == {1: 0.5, 3: 1.0}
    assert result.mrr == 0.75
    assert result.query_count == 2


def test_empty_results_score_zero_and_missing_query_results_fail() -> None:
    query = EvaluationQuery(id="q1", query="报销", relevant_document_ids=["a"])
    result = evaluate_rankings([query], {"q1": []}, [5])
    assert result.recall_at_k == {5: 0.0}
    assert result.mrr == 0.0
    with pytest.raises(ValueError, match="Missing rankings"):
        evaluate_rankings([query], {}, [5])
