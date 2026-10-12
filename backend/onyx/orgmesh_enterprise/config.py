# SPDX-License-Identifier: MIT
"""Independent, disabled-by-default configuration. No enterprise lookups."""

import os
from dataclasses import dataclass
from pathlib import Path

from onyx.orgmesh_enterprise.models import (
    MAX_BYTES,
    BrandingFields,
    BrandingView,
    validate_json_bytes,
)

DEFAULT_SOCKET = "/run/orgmesh-enterprise/enterprise.sock"


@dataclass(frozen=True)
class EnterpriseConfig:
    branding_enabled: bool = False
    audit_enabled: bool = False
    usage_enabled: bool = False
    static_branding_file: str | None = None
    tenant_id: str = "public"
    socket_path: str = DEFAULT_SOCKET

    def __post_init__(self) -> None:
        if not self.tenant_id or len(self.tenant_id) > 128:
            raise ValueError("invalid configured organization")
        path = Path(self.socket_path)
        if (
            not path.is_absolute()
            or str(path) != self.socket_path
            or ".." in path.parts
        ):
            raise ValueError("private socket path must be clean and absolute")

    @classmethod
    def from_env(cls) -> "EnterpriseConfig":
        config = cls(
            branding_enabled=os.environ.get(
                "ORGMESH_ENTERPRISE_BRANDING_ENABLED", "false"
            ).lower()
            == "true",
            audit_enabled=os.environ.get(
                "ORGMESH_ENTERPRISE_AUDIT_ENABLED", "false"
            ).lower()
            == "true",
            usage_enabled=os.environ.get(
                "ORGMESH_ENTERPRISE_USAGE_ENABLED", "false"
            ).lower()
            == "true",
            static_branding_file=os.environ.get(
                "ORGMESH_ENTERPRISE_STATIC_BRANDING_FILE"
            )
            or None,
            tenant_id=os.environ.get(
                "ORGMESH_ENTERPRISE_TENANT_ID",
                os.environ.get("POSTGRES_DEFAULT_SCHEMA", "public"),
            ),
        )
        if os.environ.get("MULTI_TENANT", "false").lower() == "true" and (
            config.branding_enabled or config.audit_enabled or config.usage_enabled
        ):
            raise ValueError("enterprise phase one requires a single organization")
        if config.branding_enabled or config.audit_enabled or config.usage_enabled:
            from shared_configs.contextvars import get_current_tenant_id

            if get_current_tenant_id() != config.tenant_id:
                raise ValueError(
                    "current organization differs from configured organization"
                )
        return config


def load_static_branding(config: EnterpriseConfig) -> BrandingView:
    if config.static_branding_file is None:
        return BrandingView(
            name="OrgMesh",
            greeting="",
            logo_asset_id="orgmesh-default",
            version=0,
            source="static",
        )
    with Path(config.static_branding_file).open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    validate_json_bytes(data)
    fields = BrandingFields.model_validate_json(data)
    return BrandingView(**fields.model_dump(), version=0, source="static")
