-- SPDX-License-Identifier: MIT
-- Only the service-owned projection is changed. Source tables remain Python-owned.
CREATE TABLE orgmesh_enterprise.usage_sync_state (
 tenant_id text PRIMARY KEY,
 activated_at timestamptz NOT NULL,
 collection_start timestamptz NOT NULL,
 revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
 lease jsonb NOT NULL DEFAULT 'null',
 begin_request_id text NOT NULL DEFAULT '',
 failed boolean NOT NULL DEFAULT false,
 staged_rows integer NOT NULL DEFAULT 0 CHECK (staged_rows BETWEEN 0 AND 100000),
 staged_bytes integer NOT NULL DEFAULT 0 CHECK (staged_bytes BETWEEN 0 AND 67108864),
 published jsonb NOT NULL DEFAULT 'null',
 published_coverage jsonb NOT NULL DEFAULT '[]',
 sync_cursor timestamptz
);
CREATE TABLE orgmesh_enterprise.usage_batches (
 tenant_id text NOT NULL,
 revision bigint NOT NULL CHECK (revision > 0),
 batch_index integer NOT NULL CHECK (batch_index >= 0 AND batch_index < 100000),
 digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
 row_count integer NOT NULL CHECK (row_count BETWEEN 1 AND 1000),
 byte_count integer NOT NULL CHECK (byte_count BETWEEN 1 AND 1048576),
 PRIMARY KEY (tenant_id, revision, batch_index),
 FOREIGN KEY (tenant_id) REFERENCES orgmesh_enterprise.usage_sync_state (tenant_id)
);
CREATE TABLE orgmesh_enterprise.usage_staging (
 tenant_id text NOT NULL,
 revision bigint NOT NULL,
 source_row_id bigint NOT NULL CHECK (source_row_id > 0),
 batch_index integer NOT NULL,
 row_index integer NOT NULL CHECK (row_index >= 0 AND row_index < 1000),
 window_start timestamptz NOT NULL,
 row_data jsonb NOT NULL,
 PRIMARY KEY (tenant_id, revision, source_row_id),
 UNIQUE (tenant_id, revision, batch_index, row_index),
 FOREIGN KEY (tenant_id, revision, batch_index) REFERENCES orgmesh_enterprise.usage_batches (tenant_id, revision, batch_index)
);
CREATE TABLE orgmesh_enterprise.usage_rows (
 tenant_id text NOT NULL,
 source_row_id bigint NOT NULL CHECK (source_row_id > 0),
 revision bigint NOT NULL CHECK (revision > 0),
 window_start timestamptz NOT NULL,
 row_data jsonb NOT NULL,
 PRIMARY KEY (tenant_id, source_row_id),
 FOREIGN KEY (tenant_id) REFERENCES orgmesh_enterprise.usage_sync_state (tenant_id)
);
CREATE INDEX usage_rows_window ON orgmesh_enterprise.usage_rows (tenant_id, window_start);
