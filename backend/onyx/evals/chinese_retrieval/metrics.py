from onyx.evals.chinese_retrieval.models import EvaluationQuery, RetrievalMetrics


def evaluate_rankings(
    queries: list[EvaluationQuery], rankings: dict[str, list[str]], cutoffs: list[int]
) -> RetrievalMetrics:
    if not queries or not cutoffs or any(cutoff <= 0 for cutoff in cutoffs):
        raise ValueError("Queries and positive cutoffs are required")
    recall_totals = dict.fromkeys(cutoffs, 0.0)
    reciprocal_rank_total = 0.0
    for query in queries:
        if query.id not in rankings:
            raise ValueError(f"Missing rankings for query {query.id}")
        # A document can have multiple retrieved chunks. Rank it once.
        ranked_documents = list(dict.fromkeys(rankings[query.id]))
        relevant_documents = set(query.relevant_document_ids)
        for cutoff in cutoffs:
            recall_totals[cutoff] += len(
                relevant_documents.intersection(ranked_documents[:cutoff])
            ) / len(relevant_documents)
        for rank, document_id in enumerate(ranked_documents, start=1):
            if document_id in relevant_documents:
                reciprocal_rank_total += 1 / rank
                break
    return RetrievalMetrics(
        query_count=len(queries),
        recall_at_k={
            cutoff: total / len(queries) for cutoff, total in recall_totals.items()
        },
        mrr=reciprocal_rank_total / len(queries),
    )
