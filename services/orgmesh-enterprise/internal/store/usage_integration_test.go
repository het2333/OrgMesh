//go:build integration

// SPDX-License-Identifier: MIT
package store_test

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
	"orgmesh.local/enterprise/internal/usage"
)

type usageFixture struct {
	pool    *pgxpool.Pool
	service *usage.Service
	tenant  string
	now     time.Time
}

func usageSetup(t *testing.T) *usageFixture {
	f := &usageFixture{pool: database(t), tenant: "usage-" + uuid(), now: time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)}
	f.service = usage.New(f.pool, f.tenant, func() time.Time { return f.now })
	t.Cleanup(func() {
		for _, table := range []string{"usage_staging", "usage_batches", "usage_rows", "usage_sync_state"} {
			if _, err := f.pool.Exec(context.Background(), "DELETE FROM orgmesh_enterprise."+table+" WHERE tenant_id=$1", f.tenant); err != nil {
				t.Error(err)
			}
		}
	})
	result, err := f.service.BeginSnapshot(context.Background(), f.identity(protocol.UsageBeginOperation), f.coverage())
	if err != nil || result.Status != "waiting" || result.Revision != 0 || result.Coverage != nil {
		t.Fatalf("activation: %+v %v", result, err)
	}
	f.now = f.now.Add(24 * time.Hour)
	return f
}
func (f *usageFixture) identity(op protocol.Operation) protocol.Identity {
	return protocol.Identity{Version: 1, TenantID: f.tenant, ActorKind: "producer", Operation: op, RequestID: uuid(), Audience: protocol.Audience, IssuedAt: f.now, ExpiresAt: f.now.Add(5 * time.Second)}
}
func (f *usageFixture) coverage() protocol.Coverage {
	day := f.now.Truncate(24 * time.Hour)
	return protocol.Coverage{From: day, To: day.Add(24 * time.Hour)}
}
func (f *usageFixture) begin(t *testing.T) protocol.SnapshotLease {
	t.Helper()
	l, e := f.service.BeginSnapshot(context.Background(), f.identity(protocol.UsageBeginOperation), f.coverage())
	if e != nil {
		t.Fatal(e)
	}
	return l
}
func (f *usageFixture) row(id int64) protocol.SnapshotRow {
	return protocol.SnapshotRow{SourceRowID: id, ActorKind: "USER", WindowStart: f.coverage().From, Model: "模型", Flow: "chat", Provider: "", InputTokens: 10, OutputTokens: 5, CacheReadTokens: 4, CacheCreationTokens: 2, CostCents: "0.123456"}
}
func (f *usageFixture) stage(t *testing.T, l protocol.SnapshotLease, index int, rows []protocol.SnapshotRow) protocol.StageAck {
	t.Helper()
	b := protocol.SnapshotBatch{Index: index, Rows: rows}
	b.Digest, _ = usage.BatchDigest(b)
	a, e := f.service.StageBatch(context.Background(), f.identity(protocol.UsageStageOperation), l, b)
	if e != nil {
		t.Fatal(e)
	}
	return a
}
func manifest(t *testing.T, l protocol.SnapshotLease, acks ...protocol.StageAck) protocol.SnapshotManifest {
	t.Helper()
	if acks == nil {
		acks = []protocol.StageAck{}
	}
	m := protocol.SnapshotManifest{Complete: true, Batches: acks}
	for _, a := range acks {
		m.TotalRows += a.RowCount
		m.TotalBytes += a.ByteCount
	}
	var e error
	m.Digest, e = usage.ManifestDigest(l, m)
	if e != nil {
		t.Fatal(e)
	}
	return m
}
func (f *usageFixture) commit(t *testing.T, l protocol.SnapshotLease, m protocol.SnapshotManifest) protocol.PublishedSnapshot {
	t.Helper()
	p, e := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, m)
	if e != nil {
		t.Fatal(e)
	}
	return p
}
func (f *usageFixture) summary(t *testing.T) protocol.UsageSummary {
	t.Helper()
	c := f.coverage()
	s, e := f.service.Summary(context.Background(), f.tenant, protocol.UsageQuery{Start: c.From, End: c.To})
	if e != nil {
		t.Fatal(e)
	}
	return s
}
func TestReplayDoesNotAdd(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	m := manifest(t, l, a)
	first := f.commit(t, l, m)
	f.service = usage.New(f.pool, f.tenant, func() time.Time { return f.now })
	f.now = f.now.Add(time.Minute)
	again := f.commit(t, l, m)
	if first != again {
		t.Fatal("restart replay changed publication")
	}
	s := f.summary(t)
	if userTokens(s) != "15" || s.Groups[0].Totals.CostCents != "0.123456" {
		t.Fatalf("replay added totals %+v", s)
	}
}
func TestSameRevisionDifferentDigest(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	m := manifest(t, l, a)
	f.commit(t, l, m)
	m.Digest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if _, e := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, m); !errors.Is(e, protocol.ErrConflict) {
		t.Fatal("changed digest accepted", e)
	}
}
func TestExpiredLeaseCannotCommit(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	f.now = *l.ExpiresAt
	if _, e := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, manifest(t, l, a)); !errors.Is(e, protocol.ErrConflict) {
		t.Fatal("expired lease accepted", e)
	}
	next := f.begin(t)
	if next.Revision != l.Revision+1 {
		t.Fatal("revision did not advance")
	}
	if _, e := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, manifest(t, l, a)); !errors.Is(e, protocol.ErrConflict) {
		t.Fatal("old lease accepted", e)
	}
}
func TestCrashBeforePublish(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	f.commit(t, l, manifest(t, l, a))
	l = f.begin(t)
	changed := f.row(1)
	changed.InputTokens = 100
	f.stage(t, l, 0, []protocol.SnapshotRow{changed})
	f.service = usage.New(f.pool, f.tenant, func() time.Time { return f.now })
	if got := userTokens(f.summary(t)); got != "15" {
		t.Fatal("staged rows published", got)
	}
}
func TestResetRemovesOldRows(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	f.commit(t, l, manifest(t, l, a))
	l = f.begin(t)
	f.commit(t, l, manifest(t, l))
	s := f.summary(t)
	if s.Status != "ready" || len(s.Groups) != 0 {
		t.Fatalf("reset failed %+v", s)
	}
}
func TestUsageAtomicCursorAndProjection(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	f.commit(t, l, manifest(t, l, a))
	l = f.begin(t)
	r := f.row(1)
	r.InputTokens = 100
	a = f.stage(t, l, 0, []protocol.SnapshotRow{r})
	ctx := context.Background()
	_, err := f.pool.Exec(ctx, `CREATE FUNCTION orgmesh_enterprise.test_reject_usage_publish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.tenant_id = TG_ARGV[0] AND NEW.published IS DISTINCT FROM OLD.published THEN RAISE EXCEPTION 'publication failure'; END IF; RETURN NEW; END $$`)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.pool.Exec(ctx, fmt.Sprintf(`CREATE TRIGGER test_reject_usage_publish BEFORE UPDATE ON orgmesh_enterprise.usage_sync_state FOR EACH ROW EXECUTE FUNCTION orgmesh_enterprise.test_reject_usage_publish('%s')`, f.tenant))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		f.pool.Exec(ctx, `DROP TRIGGER test_reject_usage_publish ON orgmesh_enterprise.usage_sync_state`)
		f.pool.Exec(ctx, `DROP FUNCTION orgmesh_enterprise.test_reject_usage_publish()`)
	})
	if _, err = f.service.CommitSnapshot(ctx, f.identity(protocol.UsageCommitOperation), l, manifest(t, l, a)); err == nil {
		t.Fatal("failed transaction published")
	}
	if got := userTokens(f.summary(t)); got != "15" {
		t.Fatal("projection escaped rollback", got)
	}
	var version int64
	var cursor time.Time
	if err = f.pool.QueryRow(ctx, `SELECT (published->>'revision')::bigint,sync_cursor FROM orgmesh_enterprise.usage_sync_state WHERE tenant_id=$1`, f.tenant).Scan(&version, &cursor); err != nil || version != 1 || !cursor.Equal(f.coverage().To) {
		t.Fatal("cursor escaped rollback", err)
	}
}
func TestUsageConcurrentLeaseAndTenantIsolation(t *testing.T) {
	f := usageSetup(t)
	other := usageSetup(t)
	const n = 8
	results := make(chan error, n)
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, e := f.service.BeginSnapshot(context.Background(), f.identity(protocol.UsageBeginOperation), f.coverage())
			results <- e
		}()
	}
	wg.Wait()
	close(results)
	success := 0
	for e := range results {
		if e == nil {
			success++
		} else if !errors.Is(e, protocol.ErrConflict) {
			t.Fatal(e)
		}
	}
	if success != 1 {
		t.Fatalf("%d concurrent leases", success)
	}
	l := other.begin(t)
	a := other.stage(t, l, 0, []protocol.SnapshotRow{other.row(1)})
	other.commit(t, l, manifest(t, l, a))
	if f.summary(t).Status != "unavailable" {
		t.Fatal("other tenant affected summary")
	}
	if _, e := f.service.Summary(context.Background(), other.tenant, protocol.UsageQuery{Start: other.coverage().From, End: other.coverage().To}); !errors.Is(e, protocol.ErrInvalid) {
		t.Fatal("foreign tenant allowed", e)
	}
}
func TestUsageRejectedBatchCannotPublishSubset(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	bad := protocol.SnapshotBatch{Index: 1, Rows: make([]protocol.SnapshotRow, 1001)}
	if _, e := f.service.StageBatch(context.Background(), f.identity(protocol.UsageStageOperation), l, bad); !errors.Is(e, protocol.ErrInvalid) {
		t.Fatal("oversize accepted", e)
	}
	if _, e := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, manifest(t, l, a)); !errors.Is(e, protocol.ErrConflict) {
		t.Fatal("published truncated snapshot", e)
	}
}

func TestUsageStageReplayAndConflictingBatch(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	rows := []protocol.SnapshotRow{f.row(1)}
	a := f.stage(t, l, 0, rows)
	if got := f.stage(t, l, 0, rows); got != a {
		t.Fatal("stage retry changed receipt")
	}
	b := protocol.SnapshotBatch{Index: 0, Rows: rows}
	b.Rows[0].InputTokens++
	b.Digest, _ = usage.BatchDigest(b)
	if _, err := f.service.StageBatch(context.Background(), f.identity(protocol.UsageStageOperation), l, b); !errors.Is(err, protocol.ErrConflict) {
		t.Fatal("changed batch accepted", err)
	}
	if _, err := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, manifest(t, l, a)); !errors.Is(err, protocol.ErrConflict) {
		t.Fatal("conflicting snapshot published", err)
	}
}
func TestUsageDuplicateSourceAcrossBatches(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	b := protocol.SnapshotBatch{Index: 1, Rows: []protocol.SnapshotRow{f.row(1)}}
	b.Digest, _ = usage.BatchDigest(b)
	if _, err := f.service.StageBatch(context.Background(), f.identity(protocol.UsageStageOperation), l, b); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatal("duplicate source accepted", err)
	}
}
func TestUsageCoverageReplacementKeepsOtherDays(t *testing.T) {
	f := usageSetup(t)
	firstDay := f.coverage().From
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1), f.row(2)})
	f.commit(t, l, manifest(t, l, a))
	f.now = f.now.Add(24 * time.Hour)
	l = f.begin(t)
	a = f.stage(t, l, 0, []protocol.SnapshotRow{f.row(3)})
	f.commit(t, l, manifest(t, l, a))
	l = f.begin(t)
	f.commit(t, l, manifest(t, l))
	summary, err := f.service.Summary(context.Background(), f.tenant, protocol.UsageQuery{Start: firstDay, End: f.coverage().To})
	if err != nil || userTokens(summary) != "30" || len(summary.Groups) != 1 || summary.Groups[0].Category != "USER" {
		t.Fatalf("reset removed other coverage or reclassified deleted users: %+v %v", summary, err)
	}
	if summary.Status != "stale" {
		t.Fatal("new empty publication refreshed an old day")
	}
}
func TestUsageActivationBoundarySurvivesRestart(t *testing.T) {
	f := usageSetup(t)
	f.service = usage.New(f.pool, f.tenant, func() time.Time { return f.now })
	l := f.begin(t)
	if !l.CollectionStart.Equal(time.Date(2026, 10, 11, 0, 0, 0, 0, time.UTC)) || !l.ActivatedAt.Equal(time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)) {
		t.Fatalf("restart changed activation %+v", l)
	}
	before := f.row(1)
	before.WindowStart = before.WindowStart.Add(-24 * time.Hour)
	b := protocol.SnapshotBatch{Index: 0, Rows: []protocol.SnapshotRow{before}}
	b.Digest, _ = usage.BatchDigest(b)
	if _, err := f.service.StageBatch(context.Background(), f.identity(protocol.UsageStageOperation), l, b); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatal("pre-activation row accepted", err)
	}
}
func TestUsageCommitRechecksStoredBatches(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
	_, err := f.pool.Exec(context.Background(), `UPDATE orgmesh_enterprise.usage_staging SET row_data=pg_catalog.jsonb_set(row_data,'{input_tokens}','99') WHERE tenant_id=$1 AND revision=$2`, f.tenant, l.Revision)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, manifest(t, l, a)); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatal("corrupted batch published", err)
	}
	if f.summary(t).Status != "unavailable" {
		t.Fatal("corrupted staging became visible")
	}
}
func TestUsageSnapshotCapsKeepPublishedRows(t *testing.T) {
	for _, limit := range []string{"rows", "bytes"} {
		t.Run(limit, func(t *testing.T) {
			f := usageSetup(t)
			l := f.begin(t)
			a := f.stage(t, l, 0, []protocol.SnapshotRow{f.row(1)})
			f.commit(t, l, manifest(t, l, a))
			l = f.begin(t)
			rejected := false
			for index := 0; index <= 100; index++ {
				rows := make([]protocol.SnapshotRow, 1000)
				for n := range rows {
					rows[n] = f.row(int64(index*1000 + n + 1))
					if limit == "bytes" {
						rows[n].Model = strings.Repeat("x", 512)
					}
				}
				b := protocol.SnapshotBatch{Index: index, Rows: rows}
				b.Digest, _ = usage.BatchDigest(b)
				_, err := f.service.StageBatch(context.Background(), f.identity(protocol.UsageStageOperation), l, b)
				if errors.Is(err, protocol.ErrInvalid) {
					rejected = true
					break
				}
				if err != nil {
					t.Fatal(err)
				}
			}
			if !rejected {
				t.Fatal("full snapshot cap was not enforced")
			}
			if userTokens(f.summary(t)) != "15" {
				t.Fatal("oversize snapshot changed old projection")
			}
			if _, err := f.service.CommitSnapshot(context.Background(), f.identity(protocol.UsageCommitOperation), l, manifest(t, l)); !errors.Is(err, protocol.ErrConflict) {
				t.Fatal("rejected snapshot remained publishable", err)
			}
		})
	}
}

func userTokens(s protocol.UsageSummary) string {
	for _, g := range s.Groups {
		if g.Category == "USER" && !g.Incognito {
			return g.Totals.TotalTokens
		}
	}
	return "0"
}

func TestUsageSummarySelectsDateModelAndFlow(t *testing.T) {
	f := usageSetup(t)
	l := f.begin(t)
	r1, r2 := f.row(1), f.row(2)
	r2.Model = "other"
	r2.Flow = "embedding"
	a := f.stage(t, l, 0, []protocol.SnapshotRow{r1, r2})
	f.commit(t, l, manifest(t, l, a))
	for _, by := range []string{"day", "model", "flow"} {
		summary, err := f.service.Summary(context.Background(), f.tenant, protocol.UsageQuery{Start: f.coverage().From, End: f.coverage().To, GroupBy: by})
		want := 2
		if by == "day" {
			want = 1
		}
		if err != nil || summary.GroupBy != by || len(summary.Groups) != want {
			t.Fatalf("group_by %s: %+v %v", by, summary, err)
		}
	}
}
