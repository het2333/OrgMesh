-- SPDX-License-Identifier: MIT
CREATE TABLE orgmesh_enterprise.branding_configs (
    tenant_id text PRIMARY KEY CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 50),
    greeting text NOT NULL CHECK (char_length(greeting) <= 120),
    logo_asset_id text NOT NULL CHECK (logo_asset_id = 'orgmesh-default'),
    version bigint NOT NULL CHECK (version >= 1),
    updated_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp()
);

CREATE TABLE orgmesh_enterprise.branding_receipts (
    tenant_id text NOT NULL,
    user_id uuid NOT NULL,
    request_id uuid NOT NULL,
    request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    PRIMARY KEY (tenant_id, user_id, request_id),
    FOREIGN KEY (tenant_id) REFERENCES orgmesh_enterprise.branding_configs (tenant_id)
);

CREATE TABLE orgmesh_enterprise.audit_events (
    tenant_id text NOT NULL,
    event_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    actor_kind text NOT NULL DEFAULT 'user' CHECK (actor_kind = 'user'),
    user_id uuid NOT NULL,
    resource_id text NOT NULL DEFAULT 'branding-config' CHECK (resource_id = 'branding-config'),
    action text NOT NULL CHECK (action IN ('branding.created', 'branding.updated')),
    result text NOT NULL CHECK (result = 'success'),
    before_version bigint NOT NULL CHECK (before_version >= 0),
    after_version bigint NOT NULL CHECK (after_version >= 1 AND after_version - 1 = before_version),
    changed_fields text[] NOT NULL CHECK (
        cardinality(changed_fields) BETWEEN 1 AND 3
        AND changed_fields <@ ARRAY['name', 'greeting', 'logo_asset_id']::text[]
    ),
    request_id uuid NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    UNIQUE (tenant_id, user_id, request_id),
    FOREIGN KEY (tenant_id) REFERENCES orgmesh_enterprise.branding_configs (tenant_id),
    CHECK ((action = 'branding.created' AND before_version = 0)
        OR (action = 'branding.updated' AND before_version >= 1))
);

CREATE INDEX audit_events_tenant_order
    ON orgmesh_enterprise.audit_events (tenant_id, created_at DESC, event_id DESC);
