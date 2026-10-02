from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DocumentSnapshot(BaseModel):
    document_id: UUID
    version_id: UUID
    content_hash: str
    title: str
    project_id: None = None


class VersionResult(DocumentSnapshot):
    parent_version_id: UUID | None
    operation: Literal["import", "manual"]


class WordStatus(BaseModel):
    enabled: bool
