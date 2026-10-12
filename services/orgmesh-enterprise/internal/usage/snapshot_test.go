// SPDX-License-Identifier: MIT
package usage

import (
	"encoding/json"
	"errors"
	"orgmesh.local/enterprise/internal/protocol"
	"os"
	"strings"
	"testing"
	"time"
)

func instant() time.Time { return time.Date(2026, 10, 12, 12, 0, 0, 0, time.UTC) }
func coverage() protocol.Coverage {
	return protocol.Coverage{From: instant().Truncate(24 * time.Hour), To: instant().Truncate(24 * time.Hour).Add(24 * time.Hour)}
}
func row(id int64) protocol.SnapshotRow {
	return protocol.SnapshotRow{SourceRowID: id, ActorKind: "USER", WindowStart: coverage().From, Model: "模型😀", Flow: "chat", Provider: "", InputTokens: 10, OutputTokens: 5, CacheReadTokens: 4, CacheCreationTokens: 2, CostCents: "0.123456"}
}
func TestDayBoundaryActivation(t *testing.T) {
	for _, at := range []time.Time{instant(), coverage().From} {
		want := time.Date(2026, 10, 13, 0, 0, 0, 0, time.UTC)
		if got := collectionStart(at); got != want {
			t.Fatalf("activation %s: %s", at, got)
		}
	}
}
func TestDeletedUserRemainsUser(t *testing.T) {
	r := row(1)
	if err := validateRow(r, coverage()); err != nil {
		t.Fatal(err)
	}
	if category(r) != "USER" {
		t.Fatal("deleted user became system")
	}
	for _, change := range []func(*protocol.SnapshotRow){
		func(r *protocol.SnapshotRow) { r.ActorKind = "SYSTEM" },
		func(r *protocol.SnapshotRow) { x := "ATTRIBUTED"; r.SystemAttribution = &x },
		func(r *protocol.SnapshotRow) { r.SourceRowID = 0 },
		func(r *protocol.SnapshotRow) { r.InputTokens = -1 },
		func(r *protocol.SnapshotRow) { r.CostCents = "0.1234567" },
		func(r *protocol.SnapshotRow) { r.CostCents = "1000000000000.000000" },
		func(r *protocol.SnapshotRow) { r.CostCents = "0.1" },
		func(r *protocol.SnapshotRow) { r.WindowStart = r.WindowStart.Add(-24 * time.Hour) },
	} {
		bad := r
		change(&bad)
		if validateRow(bad, coverage()) == nil {
			t.Fatalf("accepted %+v", bad)
		}
	}
}
func TestCanonicalBatchIsOrderSensitiveAndExact(t *testing.T) {
	batch := protocol.SnapshotBatch{Index: 0, Rows: []protocol.SnapshotRow{row(1)}}
	got, err := BatchDigest(batch)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 64 {
		t.Fatal(got)
	}
	batch.Rows[0].CostCents = "0.123457"
	other, _ := BatchDigest(batch)
	if got == other {
		t.Fatal("money change not bound")
	}
	batch.Rows[0] = row(2)
	batch.Rows = append(batch.Rows, row(1))
	a, _ := BatchDigest(batch)
	batch.Rows[0], batch.Rows[1] = batch.Rows[1], batch.Rows[0]
	b, _ := BatchDigest(batch)
	if a == b {
		t.Fatal("row order not bound")
	}
}
func TestSnapshotBatchLimits(t *testing.T) {
	b := protocol.SnapshotBatch{Rows: make([]protocol.SnapshotRow, 1001)}
	if _, err := validateBatch(b, coverage()); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatal("row cap not enforced", err)
	}
	b.Rows = make([]protocol.SnapshotRow, 1000)
	for i := range b.Rows {
		b.Rows[i] = row(int64(i + 1))
		b.Rows[i].Model = strings.Repeat("x", 512)
		b.Rows[i].Flow = strings.Repeat("x", 512)
		b.Rows[i].Provider = strings.Repeat("x", 512)
	}
	b.Digest, _ = BatchDigest(b)
	if _, err := validateBatch(b, coverage()); err == nil {
		t.Fatal("byte cap not enforced")
	}

}
func TestExpiredLeaseCannotCommit(t *testing.T) {
	end := instant().Add(45 * time.Second)
	c := coverage()
	l := protocol.SnapshotLease{Status: "ready", Revision: 2, Coverage: &c, ExpiresAt: &end}
	s := syncState{Revision: 2, Lease: l}
	if checkLease(s, l, instant()) != nil {
		t.Fatal("fresh lease rejected")
	}
	if checkLease(s, l, end) == nil {
		t.Fatal("expired lease accepted")
	}
	l.Revision = 1
	if checkLease(s, l, instant()) == nil {
		t.Fatal("old revision accepted")
	}
}

func TestSharedCanonicalDigestFixture(t *testing.T) {
	data, err := os.ReadFile("../../../../contracts/orgmesh-enterprise/fixtures/usage-digest.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Lease    protocol.SnapshotLease    `json:"lease"`
		Batch    protocol.SnapshotBatch    `json:"batch"`
		Ack      protocol.StageAck         `json:"ack"`
		Manifest protocol.SnapshotManifest `json:"manifest"`
	}
	if json.Unmarshal(data, &fixture) != nil {
		t.Fatal("invalid fixture")
	}
	digest, err := BatchDigest(fixture.Batch)
	if err != nil || digest != fixture.Batch.Digest {
		t.Fatal("cross-language batch differs", digest, err)
	}
	ack, err := validateBatch(fixture.Batch, *fixture.Lease.Coverage)
	if err != nil || ack != fixture.Ack {
		t.Fatalf("cross-language byte count differs %+v %v", ack, err)
	}
	digest, err = ManifestDigest(fixture.Lease, fixture.Manifest)
	if err != nil || digest != fixture.Manifest.Digest {
		t.Fatal("cross-language manifest differs", digest, err)
	}
}

func TestManifestRejectsIncompleteOverflowAndMissingBatches(t *testing.T) {
	c := coverage()
	l := protocol.SnapshotLease{Revision: 1, Coverage: &c}
	empty := protocol.SnapshotManifest{Complete: true, Batches: []protocol.StageAck{}}
	if _, err := ManifestDigest(l, empty); err != nil {
		t.Fatal("explicit complete reset rejected", err)
	}
	for _, bad := range []protocol.SnapshotManifest{{Complete: false, Batches: []protocol.StageAck{}}, {Complete: true, Batches: nil}, {Complete: true, Batches: []protocol.StageAck{}, TotalRows: 100001}, {Complete: true, Batches: []protocol.StageAck{}, TotalBytes: 64<<20 + 1}, {Complete: true, Batches: []protocol.StageAck{}, TotalRows: 1}} {
		if _, err := ManifestDigest(l, bad); err == nil {
			t.Fatal("invalid complete manifest", bad)
		}
	}
}
func TestLeaseRejectsChangedCoverageAndPublishedRevision(t *testing.T) {
	end := instant().Add(45 * time.Second)
	c := coverage()
	l := protocol.SnapshotLease{Status: "ready", Revision: 1, Coverage: &c, ExpiresAt: &end}
	s := syncState{Revision: 1, Lease: l}
	different := c
	different.From = different.From.Add(-24 * time.Hour)
	bad := l
	bad.Coverage = &different
	if checkLease(s, bad, instant()) == nil {
		t.Fatal("lease coverage changed")
	}
	s.Published = &protocol.PublishedSnapshot{Revision: 1}
	if checkLease(s, l, instant()) == nil {
		t.Fatal("staged into published revision")
	}
}
