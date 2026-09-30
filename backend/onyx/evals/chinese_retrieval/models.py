from pydantic import BaseModel, Field, model_validator


class EvaluationQuery(BaseModel):
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    relevant_document_ids: list[str] = Field(min_length=1)


class EvaluationCorpus(BaseModel):
    queries: list[EvaluationQuery] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_query_ids(self) -> "EvaluationCorpus":
        ids = [query.id for query in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("Query IDs must be unique")
        return self


class RetrievalMetrics(BaseModel):
    query_count: int
    recall_at_k: dict[int, float]
    mrr: float
