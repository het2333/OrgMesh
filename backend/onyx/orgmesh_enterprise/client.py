# SPDX-License-Identifier: MIT
"""Synchronous private HTTP transport. Browser identity headers are never inputs."""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from uuid import uuid4

import httpx
from pydantic import ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.models import (
    MAX_BYTES,
    Coverage,
    EnterpriseOperation,
    PublishedSnapshot,
    RequestModel,
    ResponseModel,
    SnapshotBatch,
    SnapshotLease,
    SnapshotManifest,
    StageAck,
    TrustedIdentity,
    UsageBeginRequest,
    UsageBeginResponse,
    UsageCommitRequest,
    UsageCommitResponse,
    UsageStageRequest,
    UsageStageResponse,
    decode_response,
)


class EnterpriseClient:
    def __init__(
        self, config: EnterpriseConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.config = config
        self.transport = transport

    def call(
        self,
        operation: EnterpriseOperation,
        identity: TrustedIdentity,
        payload: RequestModel,
    ) -> ResponseModel:
        if (
            sys.platform != "linux"
            or identity.operation != operation
            or payload.operation != operation
            or identity.tenant_id != self.config.tenant_id
            or identity.actor_kind == "producer"
        ):
            raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
        return self._send(operation, identity, payload)

    def _producer_call(
        self, payload: RequestModel, *, deadline: float | None = None
    ) -> ResponseModel:
        from shared_configs.contextvars import get_current_tenant_id

        if (
            sys.platform != "linux"
            or not self.config.usage_enabled
            or get_current_tenant_id() != self.config.tenant_id
            or os.environ.get("MULTI_TENANT", "false").lower() == "true"
            or payload.operation
            not in (
                EnterpriseOperation.USAGE_BEGIN,
                EnterpriseOperation.USAGE_STAGE,
                EnterpriseOperation.USAGE_COMMIT,
            )
        ):
            raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
        now = datetime.now(timezone.utc)
        identity = TrustedIdentity(
            tenant_id=self.config.tenant_id,
            actor_kind="producer",
            user_id="",
            operation=payload.operation,
            request_id=uuid4(),
            issued_at=now,
            expires_at=now + timedelta(seconds=5),
        )
        call_deadline = time.monotonic() + 2.0
        if deadline is not None:
            call_deadline = min(call_deadline, deadline)
        return self._send(payload.operation, identity, payload, deadline=call_deadline)

    def begin(
        self, coverage: Coverage, *, deadline: float | None = None
    ) -> SnapshotLease:
        result = self._producer_call(
            UsageBeginRequest(coverage=coverage), deadline=deadline
        )
        if not isinstance(result, UsageBeginResponse):
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
        return result.lease

    def stage(
        self,
        lease: SnapshotLease,
        batch: SnapshotBatch,
        *,
        deadline: float | None = None,
    ) -> StageAck:
        result = self._producer_call(
            UsageStageRequest(lease=lease, batch=batch), deadline=deadline
        )
        if not isinstance(result, UsageStageResponse):
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
        return result.ack

    def commit(
        self,
        lease: SnapshotLease,
        manifest: SnapshotManifest,
        *,
        deadline: float | None = None,
    ) -> PublishedSnapshot:
        result = self._producer_call(
            UsageCommitRequest(lease=lease, manifest=manifest), deadline=deadline
        )
        if not isinstance(result, UsageCommitResponse):
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
        return result.published

    def _send(
        self,
        operation: EnterpriseOperation,
        identity: TrustedIdentity,
        payload: RequestModel,
        *,
        deadline: float | None = None,
    ) -> ResponseModel:
        _transport_timeout(deadline)
        now = datetime.now(timezone.utc)
        context = TrustedIdentity.model_validate(
            identity.model_dump()
            | {"issued_at": now, "expires_at": now + timedelta(seconds=5)}
        )
        body = json.dumps(
            {
                "version": 1,
                "identity": context.model_dump(mode="json"),
                "request": payload.model_dump(mode="json"),
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        if len(body) > MAX_BYTES:
            raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE)
        timeout = _transport_timeout(deadline)
        transport = self.transport or httpx.HTTPTransport(
            uds=self.config.socket_path, retries=0, trust_env=False
        )
        try:
            with httpx.Client(
                transport=transport,
                timeout=timeout,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "POST",
                    "http://orgmesh-enterprise/v1/call",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    _transport_timeout(deadline)
                    # Only bounded, known error categories cross the private boundary.
                    if (
                        response.headers.get("content-encoding", "identity").lower()
                        != "identity"
                    ):
                        raise ValueError("compressed responses are unsupported")
                    if response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
                        raise OnyxError(
                            OnyxErrorCode.VALIDATION_ERROR,
                            status_code_override=HTTPStatus.UNPROCESSABLE_ENTITY,
                        )
                    if response.status_code != HTTPStatus.OK:
                        code = {
                            HTTPStatus.FORBIDDEN: OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                            HTTPStatus.CONFLICT: OnyxErrorCode.CONFLICT,
                            HTTPStatus.REQUEST_ENTITY_TOO_LARGE: OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        }.get(response.status_code, OnyxErrorCode.SERVICE_UNAVAILABLE)
                        raise OnyxError(code)
                    result_bytes = bytearray()
                    for chunk in response.iter_bytes():
                        _transport_timeout(deadline)
                        result_bytes.extend(chunk)
                        if len(result_bytes) > MAX_BYTES:
                            raise ValueError("response exceeds limit")
                    result = decode_response(bytes(result_bytes))
                    _transport_timeout(deadline)
            if result.operation != operation:
                raise ValueError("response operation differs from request")
            return result
        except (httpx.HTTPError, ValueError, ValidationError, OSError) as error:
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE) from error


def _transport_timeout(deadline: float | None) -> float:
    if deadline is None:
        return 2.0
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    return min(2.0, remaining)
