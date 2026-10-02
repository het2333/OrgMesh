"""Shared wire cases and authorized SQL snapshots; no engine access."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from onyx.db.models import Base, PresentationRecord, PresentationTask
from onyx.db.presentation_history import history_facts_for_owner, history_for_owner
from onyx.presentation_history.contract import (
    decode_request,
    decode_response,
    project_history_python,
)

CASES = Path(__file__).resolve().parents[4] / "services/orgmesh-core/testdata/history"


def test_python_projection_retains_public_contract() -> None:
    for case in CASES.glob("*.json"):
        fixture = json.loads(case.read_text())
        req = decode_request(json.dumps(fixture["request"]).encode())
        response = decode_response(json.dumps(fixture["response"]).encode())
        assert project_history_python(req.facts) == fixture["response"]["rows"]
        assert response.rows_json() == fixture["response"]["rows"]
        with pytest.raises(ValueError):
            req.version = 2
        if req.facts:
            with pytest.raises(ValueError):
                req.facts[0].state = "error"


def test_history_facts_keep_owner_filter_and_live_acl() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[PresentationTask.__table__, PresentationRecord.__table__]
    )
    owner, other, source = uuid4(), uuid4(), uuid4()
    ids = [uuid4() for _ in range(3)]
    with Session(engine) as db:
        for i, (user, status) in enumerate(
            [(owner, "pending"), (owner, "error"), (other, "error")]
        ):
            now = datetime(2026, 10, i + 1, tzinfo=timezone.utc)
            db.add(
                PresentationTask(
                    id=ids[i],
                    user_id=user,
                    status=status,
                    project_id=3,
                    source_chat_id=source,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()
        with patch(
            "onyx.db.presentation_history.visible_source", return_value=(None, None)
        ) as acl:
            facts = history_facts_for_owner(db, owner, 1, 0, "error")
            assert [f.platform_id for f in facts] == [ids[1]]
            assert facts[0].visible_source_chat_id is None
            assert facts[0].visible_project_id is None
            assert acl.call_count == 1
            assert history_for_owner(
                db, owner, 1, 0, "error"
            ) == project_history_python(facts)
        assert not db.new and not db.dirty and not db.deleted
    engine.dispose()


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"request_id": "bad"},
        {"query": {"limit": True, "offset": 0, "status": None}},
        {"query": {"limit": 101, "offset": 0, "status": None}},
        {"query": {"limit": 1, "offset": -1, "status": None}},
        {"query": {"limit": 1, "offset": 0, "status": "unknown"}},
        {"extra": 1},
        {"facts": None},
    ],
)
def test_request_rejects_invalid_types_and_bounds(change: dict) -> None:
    fixture = json.loads((CASES / "statuses.json").read_text())["request"]
    fixture.update(change)
    with pytest.raises(ValueError):
        decode_request(json.dumps(fixture).encode())


def test_contract_rejects_missing_nullable_duplicate_trailing_and_large() -> None:
    fixture = json.loads((CASES / "statuses.json").read_text())["request"]
    for key in fixture["facts"][0]:
        changed = json.loads(json.dumps(fixture))
        del changed["facts"][0][key]
        with pytest.raises(ValueError):
            decode_request(json.dumps(changed).encode())
    for invalid in [b"{} {}", b'{"version":1,"version":1}', b" " * (256 * 1024 + 1)]:
        with pytest.raises(ValueError):
            decode_request(invalid)
    fixture["facts"].append(fixture["facts"][0])
    with pytest.raises(ValueError):
        decode_request(json.dumps(fixture).encode())
