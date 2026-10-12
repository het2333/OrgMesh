//go:build integration

// SPDX-License-Identifier: MIT
package store_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"regexp"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
	"orgmesh.local/enterprise/internal/store"
	"orgmesh.local/enterprise/internal/usage"
)

// A write outside the owned migration schema changes this independent legacy fixture hash.
func TestRecoveryFreshMigrationsPreserveLegacySchema(t *testing.T) {
	dsn := os.Getenv("ORGMESH_RECOVERY_DATABASE_URL")
	if dsn == "" {
		t.Fatal("ORGMESH_RECOVERY_DATABASE_URL must name a second fresh disposable orgmesh_enterprise_test_* database")
	}
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil || !regexp.MustCompile(`^orgmesh_enterprise_test_[a-z0-9_]+$`).MatchString(config.ConnConfig.Database) {
		t.Fatal("refusing a database outside the disposable test naming rule")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal("recovery database connection failed")
	}
	defer pool.Close()
	var exists bool
	if err = pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='orgmesh_enterprise') OR pg_catalog.to_regclass('public.orgmesh_recovery_legacy_fixture') IS NOT NULL`).Scan(&exists); err != nil || exists {
		t.Fatal("recovery database must be reachable and fresh; no existing object is deleted")
	}
	if _, err = pool.Exec(ctx, `CREATE TABLE public.orgmesh_recovery_legacy_fixture (id bigint PRIMARY KEY, value text NOT NULL); INSERT INTO public.orgmesh_recovery_legacy_fixture VALUES (1,'preserve'), (2,'unchanged')`); err != nil {
		t.Fatal(err)
	}
	hash := func() string {
		var structure, data, objects, constraints, indexes string
		if err := pool.QueryRow(ctx, `SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name='orgmesh_recovery_legacy_fixture'`).Scan(&structure); err != nil {
			t.Fatal(err)
		}
		if err := pool.QueryRow(ctx, `SELECT jsonb_agg(to_jsonb(fixture) ORDER BY id)::text FROM public.orgmesh_recovery_legacy_fixture fixture`).Scan(&data); err != nil {
			t.Fatal(err)
		}
		if err := pool.QueryRow(ctx, `SELECT coalesce(string_agg(c.relname || ':' || c.relkind, ',' ORDER BY c.relname), '') FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'`).Scan(&objects); err != nil {
			t.Fatal(err)
		}
		if err := pool.QueryRow(ctx, `SELECT coalesce(string_agg(c.conname || ':' || pg_catalog.pg_get_constraintdef(c.oid), ',' ORDER BY c.conname), '') FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public'`).Scan(&constraints); err != nil {
			t.Fatal(err)
		}
		if err := pool.QueryRow(ctx, `SELECT coalesce(string_agg(indexname || ':' || indexdef, ',' ORDER BY indexname), '') FROM pg_catalog.pg_indexes WHERE schemaname='public'`).Scan(&indexes); err != nil {
			t.Fatal(err)
		}
		digest := sha256.Sum256([]byte(structure + "\n" + objects + "\n" + constraints + "\n" + indexes + "\n" + data))
		return hex.EncodeToString(digest[:])
	}
	before := hash()
	for attempt := 0; attempt < 2; attempt++ {
		if err = store.Migrate(ctx, pool); err != nil {
			t.Fatal(err)
		}
		if after := hash(); after != before {
			t.Fatalf("legacy schema/data changed: before=%s after=%s", before, after)
		}
	}
	var versions int
	if err = pool.QueryRow(ctx, `SELECT count(*) FROM orgmesh_enterprise.schema_migrations`).Scan(&versions); err != nil || versions != 2 {
		t.Fatalf("migration metadata count=%d err=%v", versions, err)
	}
	t.Logf("legacy structure/data SHA256 unchanged after fresh and repeated migration: %s", before)
}

// Removing the transaction audit when its query UI is absent fails this test.
func TestBrandingWithoutAuditUIStillRecords(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	view, err := brand.Apply(context.Background(), identity, patch(0, "Audit remains"))
	if err != nil {
		t.Fatal(err)
	}
	counts(t, pool, identity.TenantID, 1, 1, 1)
	var after int64
	if err = pool.QueryRow(context.Background(), `SELECT after_version FROM orgmesh_enterprise.audit_events WHERE tenant_id=$1 AND request_id=$2`, identity.TenantID, identity.RequestID).Scan(&after); err != nil || after != view.Version {
		t.Fatal("branding committed without its matching audit", err)
	}
}

// Restarting and replaying a publication must replace rows, never add usage.
func TestReenableNoDoubleCount(t *testing.T) {
	f := usageSetup(t)
	lease := f.begin(t)
	ack := f.stage(t, lease, 0, []protocol.SnapshotRow{f.row(1)})
	payload := manifest(t, lease, ack)
	first := f.commit(t, lease, payload)
	f.service = usage.New(f.pool, f.tenant, func() time.Time { return f.now })
	f.now = f.now.Add(time.Minute)
	if replay := f.commit(t, lease, payload); replay != first {
		t.Fatal("reenable replay changed publication")
	}
	next := f.begin(t)
	nextAck := f.stage(t, next, 0, []protocol.SnapshotRow{f.row(1)})
	f.commit(t, next, manifest(t, next, nextAck))
	if total := userTokens(f.summary(t)); total != "15" {
		t.Fatal("reenable double counted", total)
	}
	for table, want := range map[string]int{"usage_rows": 1, "usage_batches": 2, "usage_staging": 2} {
		var got int
		if err := f.pool.QueryRow(context.Background(), fmt.Sprintf("SELECT count(*) FROM orgmesh_enterprise.%s WHERE tenant_id=$1", table), f.tenant).Scan(&got); err != nil || got != want {
			t.Fatalf("%s retained count=%d want=%d err=%v", table, got, want, err)
		}
	}
}
