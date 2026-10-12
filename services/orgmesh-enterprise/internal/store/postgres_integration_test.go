//go:build integration

// SPDX-License-Identifier: MIT
package store_test

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"os"
	"regexp"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/audit"
	"orgmesh.local/enterprise/internal/branding"
	"orgmesh.local/enterprise/internal/protocol"
	"orgmesh.local/enterprise/internal/store"
)

var testPool *pgxpool.Pool
var testPoolError error
var setupOnce sync.Once

func database(t *testing.T) *pgxpool.Pool {
	t.Helper()
	setupOnce.Do(func() {
		dsn := os.Getenv("ORGMESH_TEST_DATABASE_URL")
		if dsn == "" {
			testPoolError = errors.New("ORGMESH_TEST_DATABASE_URL must name a new disposable orgmesh_enterprise_test_* database")
			return
		}
		config, err := pgxpool.ParseConfig(dsn)
		if err != nil || !regexp.MustCompile(`^orgmesh_enterprise_test_[a-z0-9_]+$`).MatchString(config.ConnConfig.Database) {
			testPoolError = errors.New("refusing a database outside the disposable test naming rule")
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		testPool, err = pgxpool.NewWithConfig(ctx, config)
		if err != nil {
			testPoolError = errors.New("test database connection failed")
			return
		}
		var exists bool
		err = testPool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='orgmesh_enterprise')`).Scan(&exists)
		if err != nil || exists {
			testPoolError = errors.New("test database must be reachable and have no orgmesh_enterprise schema; no existing schema is deleted")
			return
		}
		if err = store.Migrate(ctx, testPool); err != nil {
			testPoolError = err
			return
		}
	})
	if testPoolError != nil {
		t.Fatal(testPoolError)
	}
	return testPool
}
func uuid() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err)
	}
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
}
func fixture(t *testing.T) (*pgxpool.Pool, *branding.Service, *audit.Service, protocol.Identity) {
	t.Helper()
	pool := database(t)
	tenant := "test-" + uuid()
	identity := protocol.Identity{TenantID: tenant, UserID: "11111111-1111-4111-8111-111111111111", ActorKind: "user", Operation: protocol.BrandingPatchOperation, RequestID: uuid()}
	t.Cleanup(func() {
		for _, table := range []string{"branding_receipts", "audit_events", "branding_configs"} {
			if _, err := pool.Exec(context.Background(), "DELETE FROM orgmesh_enterprise."+table+" WHERE tenant_id=$1", tenant); err != nil {
				t.Errorf("test tenant cleanup failed: %s", table)
			}
		}
	})
	return pool, branding.New(pool, tenant, []string{"orgmesh-default"}), audit.New(pool, tenant), identity
}
func patch(version int64, name string) protocol.BrandingPatch {
	return protocol.BrandingPatch{ExpectedVersion: version, Name: name, Greeting: "Private greeting", LogoAssetID: "orgmesh-default"}
}
func query() protocol.AuditQuery {
	now := time.Now()
	return protocol.AuditQuery{Start: now.Add(-time.Hour), End: now.Add(time.Hour), Limit: 100}
}
func counts(t *testing.T, pool *pgxpool.Pool, tenant string, configs, events, receipts int) {
	t.Helper()
	for table, want := range map[string]int{"branding_configs": configs, "audit_events": events, "branding_receipts": receipts} {
		var got int
		if err := pool.QueryRow(context.Background(), "SELECT count(*) FROM orgmesh_enterprise."+table+" WHERE tenant_id=$1", tenant).Scan(&got); err != nil || got != want {
			t.Fatalf("%s count=%d want=%d err=%v", table, got, want, err)
		}
	}
}
func TestBrandingAndAuditAtomic(t *testing.T) {
	pool, brand, history, identity := fixture(t)
	ctx := context.Background()
	view, err := brand.Apply(ctx, identity, patch(0, "First"))
	if err != nil || view.Version != 1 {
		t.Fatalf("create: %+v %v", view, err)
	}
	page, err := history.List(ctx, identity.TenantID, query())
	if err != nil || len(page.Events) != 1 {
		t.Fatalf("audit: %+v %v", page, err)
	}
	event := page.Events[0]
	if event.ActorKind != "user" || event.ResourceID != "branding-config" || event.Action != "branding.created" || event.Result != "success" || event.BeforeVersion != 0 || event.AfterVersion != 1 || event.RequestID != identity.RequestID || len(event.ChangedFields) != 3 {
		t.Fatalf("wrong audit: %+v", event)
	}
	counts(t, pool, identity.TenantID, 1, 1, 1)
	// Only this disposable tenant is rejected. A real PostgreSQL trigger causes the failure.
	_, err = pool.Exec(ctx, `CREATE FUNCTION orgmesh_enterprise.test_reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.tenant_id = TG_ARGV[0] THEN RAISE EXCEPTION 'test audit failure'; END IF; RETURN NEW; END $$`)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, fmt.Sprintf(`CREATE TRIGGER test_reject_audit BEFORE INSERT ON orgmesh_enterprise.audit_events FOR EACH ROW EXECUTE FUNCTION orgmesh_enterprise.test_reject_audit('%s')`, identity.TenantID))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Exec(ctx, `DROP TRIGGER test_reject_audit ON orgmesh_enterprise.audit_events`)
		pool.Exec(ctx, `DROP FUNCTION orgmesh_enterprise.test_reject_audit()`)
	})
	identity.RequestID = uuid()
	if _, err = brand.Apply(ctx, identity, patch(1, "Rejected")); err == nil {
		t.Fatal("audit failure did not reject update")
	}
	current, err := brand.Read(ctx, identity.TenantID)
	if err != nil || current != view {
		t.Fatalf("config escaped rollback: %+v %v", current, err)
	}
	counts(t, pool, identity.TenantID, 1, 1, 1)
}
func TestAuditFailureRollsBackInitialCreate(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	ctx := context.Background()
	_, err := pool.Exec(ctx, `CREATE FUNCTION orgmesh_enterprise.test_reject_create_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.tenant_id = TG_ARGV[0] THEN RAISE EXCEPTION 'test audit failure'; END IF; RETURN NEW; END $$`)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, fmt.Sprintf(`CREATE TRIGGER test_reject_create_audit BEFORE INSERT ON orgmesh_enterprise.audit_events FOR EACH ROW EXECUTE FUNCTION orgmesh_enterprise.test_reject_create_audit('%s')`, identity.TenantID))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Exec(ctx, `DROP TRIGGER test_reject_create_audit ON orgmesh_enterprise.audit_events`)
		pool.Exec(ctx, `DROP FUNCTION orgmesh_enterprise.test_reject_create_audit()`)
	})
	if _, err = brand.Apply(ctx, identity, patch(0, "Rejected")); err == nil {
		t.Fatal("initial create succeeded without audit")
	}
	if _, err = brand.Read(ctx, identity.TenantID); !errors.Is(err, protocol.ErrNotFound) {
		t.Fatalf("unexpected absent-row result: %v", err)
	}
	counts(t, pool, identity.TenantID, 0, 0, 0)
}
func TestConcurrentExpectedVersion(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	const total = 16
	results := make(chan error, total)
	start := make(chan struct{})
	for n := 0; n < total; n++ {
		go func() {
			current := identity
			current.RequestID = uuid()
			<-start
			_, err := brand.Apply(context.Background(), current, patch(0, "First"))
			results <- err
		}()
	}
	close(start)
	successes := 0
	for n := 0; n < total; n++ {
		err := <-results
		if err == nil {
			successes++
		} else if !errors.Is(err, protocol.ErrConflict) {
			t.Fatalf("unexpected concurrency error: %v", err)
		}
	}
	if successes != 1 {
		t.Fatalf("%d concurrent initial creates succeeded", successes)
	}
	counts(t, pool, identity.TenantID, 1, 1, 1)
	results = make(chan error, total)
	start = make(chan struct{})
	for n := 0; n < total; n++ {
		go func() {
			current := identity
			current.RequestID = uuid()
			<-start
			_, err := brand.Apply(context.Background(), current, patch(1, "Updated"))
			results <- err
		}()
	}
	close(start)
	successes = 0
	for n := 0; n < total; n++ {
		err := <-results
		if err == nil {
			successes++
		} else if !errors.Is(err, protocol.ErrConflict) {
			t.Fatalf("unexpected update error: %v", err)
		}
	}
	if successes != 1 {
		t.Fatalf("%d concurrent updates succeeded", successes)
	}
	counts(t, pool, identity.TenantID, 1, 2, 2)
}
func TestRetryReturnsOriginal(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	ctx := context.Background()
	original := patch(0, "First")
	first, err := brand.Apply(ctx, identity, original)
	if err != nil {
		t.Fatal(err)
	}
	secondIdentity := identity
	secondIdentity.RequestID = uuid()
	if _, err = brand.Apply(ctx, secondIdentity, patch(1, "Second")); err != nil {
		t.Fatal(err)
	}
	retry, err := brand.Apply(ctx, identity, original)
	if err != nil || retry != first {
		t.Fatalf("retry lost original result: %+v %v", retry, err)
	}
	counts(t, pool, identity.TenantID, 1, 2, 2)
}
func TestIdempotencyBodyConflict(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	ctx := context.Background()
	if _, err := brand.Apply(ctx, identity, patch(0, "First")); err != nil {
		t.Fatal(err)
	}
	if _, err := brand.Apply(ctx, identity, patch(0, "Different")); !errors.Is(err, protocol.ErrConflict) {
		t.Fatalf("body conflict: %v", err)
	}
	counts(t, pool, identity.TenantID, 1, 1, 1)
}
func TestNoChangeSavesReceiptOnly(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	ctx := context.Background()
	first, err := brand.Apply(ctx, identity, patch(0, "First"))
	if err != nil {
		t.Fatal(err)
	}
	identity.RequestID = uuid()
	second, err := brand.Apply(ctx, identity, patch(1, "First"))
	if err != nil || second != first {
		t.Fatalf("no-op changed config: %+v %v", second, err)
	}
	counts(t, pool, identity.TenantID, 1, 1, 2)
}
func TestAuditTenantIsolation(t *testing.T) {
	pool, first, firstAudit, identity := fixture(t)
	_, second, secondAudit, other := fixture(t)
	ctx := context.Background()
	other.UserID = identity.UserID
	other.RequestID = identity.RequestID
	if _, err := first.Apply(ctx, identity, patch(0, "First tenant")); err != nil {
		t.Fatal(err)
	}
	if _, err := second.Apply(ctx, other, patch(0, "Second tenant")); err != nil {
		t.Fatal(err)
	}
	ownPage, err := secondAudit.List(ctx, other.TenantID, query())
	if err != nil || len(ownPage.Events) != 1 {
		t.Fatalf("second tenant page: %+v %v", ownPage, err)
	}
	ownEventID := ownPage.Events[0].EventID
	identity.RequestID = uuid()
	if _, err := first.Apply(ctx, identity, patch(1, "Updated first tenant")); err != nil {
		t.Fatal(err)
	}
	q := query()
	q.Limit = 1
	page, err := firstAudit.List(ctx, identity.TenantID, q)
	if err != nil || len(page.Events) != 1 || page.NextCursor == nil {
		t.Fatalf("first page: %+v %v", page, err)
	}
	q.Cursor = *page.NextCursor
	foreign, err := secondAudit.List(ctx, other.TenantID, q)
	if err != nil {
		t.Fatal(err)
	}
	for _, event := range foreign.Events {
		if event.EventID != ownEventID || event.RequestID != other.RequestID {
			t.Fatal("forged cursor exposed another tenant")
		}
	}
	if _, err := first.Read(ctx, other.TenantID); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatal("configured store accepted another tenant")
	}
	if _, err := firstAudit.List(ctx, other.TenantID, query()); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatal("configured audit store accepted another tenant")
	}
	counts(t, pool, identity.TenantID, 1, 2, 2)
	counts(t, pool, other.TenantID, 1, 1, 1)
}
func TestAuditFiltersAndStablePagination(t *testing.T) {
	pool, brand, history, identity := fixture(t)
	ctx := context.Background()
	if _, err := brand.Apply(ctx, identity, patch(0, "First")); err != nil {
		t.Fatal(err)
	}
	identity.RequestID = uuid()
	if _, err := brand.Apply(ctx, identity, patch(1, "Second")); err != nil {
		t.Fatal(err)
	}
	// The equal timestamp requires the event_id tie-breaker.
	if _, err := pool.Exec(ctx, `UPDATE orgmesh_enterprise.audit_events SET created_at=$2 WHERE tenant_id=$1`, identity.TenantID, time.Now().Truncate(time.Microsecond)); err != nil {
		t.Fatal(err)
	}
	q := query()
	q.Limit = 1
	first, err := history.List(ctx, identity.TenantID, q)
	if err != nil || first.NextCursor == nil {
		t.Fatalf("first page: %+v %v", first, err)
	}
	q.Cursor = *first.NextCursor
	second, err := history.List(ctx, identity.TenantID, q)
	if err != nil || len(second.Events) != 1 || second.NextCursor != nil || first.Events[0].EventID == second.Events[0].EventID {
		t.Fatalf("pagination: %+v %v", second, err)
	}
	q = query()
	q.Action = "branding.created"
	q.Result = "success"
	filtered, err := history.List(ctx, identity.TenantID, q)
	if err != nil || len(filtered.Events) != 1 || filtered.Events[0].Action != "branding.created" {
		t.Fatalf("filters: %+v %v", filtered, err)
	}
}
func TestMigrationsRepeatAndRejectChecksumChange(t *testing.T) {
	pool := database(t)
	ctx := context.Background()
	if err := store.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	var checksum string
	if err := pool.QueryRow(ctx, `SELECT checksum FROM orgmesh_enterprise.schema_migrations WHERE version=1`).Scan(&checksum); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `UPDATE orgmesh_enterprise.schema_migrations SET checksum='changed' WHERE version=1`); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Exec(ctx, `UPDATE orgmesh_enterprise.schema_migrations SET checksum=$1 WHERE version=1`, checksum)
	})
	if err := store.Migrate(ctx, pool); err == nil {
		t.Fatal("modified migration checksum accepted")
	}
}

func TestConcurrentRetryCreatesOneReceipt(t *testing.T) {
	pool, brand, _, identity := fixture(t)
	const total = 16
	results := make(chan struct {
		view protocol.BrandingView
		err  error
	}, total)
	start := make(chan struct{})
	for n := 0; n < total; n++ {
		go func() {
			<-start
			view, err := brand.Apply(context.Background(), identity, patch(0, "First"))
			results <- struct {
				view protocol.BrandingView
				err  error
			}{view, err}
		}()
	}
	close(start)
	for n := 0; n < total; n++ {
		result := <-results
		if result.err != nil || result.view.Version != 1 || result.view.Name != "First" {
			t.Fatalf("concurrent retry: %+v %v", result.view, result.err)
		}
	}
	counts(t, pool, identity.TenantID, 1, 1, 1)
}
