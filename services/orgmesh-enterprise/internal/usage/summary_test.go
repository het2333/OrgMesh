// SPDX-License-Identifier: MIT
package usage

import (
	"encoding/json"
	"fmt"
	"orgmesh.local/enterprise/internal/protocol"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestSummaryPreservesSourcePrecisionAndPrivacy(t *testing.T) {
	r := row(1)
	r.InputTokens = 9223372036854775807
	r.OutputTokens = 1
	r.CacheReadTokens = 9
	r.CacheCreationTokens = 2
	second := row(2)
	second.CostCents = "0.000001"
	second.Incognito = true
	system := row(3)
	system.ActorKind = "SYSTEM"
	attr := "ATTRIBUTED"
	system.SystemAttribution = &attr
	unattributed := system
	unattributed.SourceRowID = 4
	u := "UNATTRIBUTED"
	unattributed.SystemAttribution = &u
	groups, err := aggregate(slices.Values([]protocol.SnapshotRow{r, second, system, unattributed}), "day")
	if err != nil {
		t.Fatal(err)
	}
	for _, g := range groups {
		if g.Category == "USER" && !g.Incognito {
			if g.Totals.TotalTokens != "9223372036854775808" || g.Totals.CostCents != "0.123456" || g.Totals.CacheReadTokens != "9" {
				t.Fatalf("wrong user totals %+v", g)
			}
		}
		if g.Category == "USER" && g.Incognito && g.Totals.CostCents != "0.000001" {
			t.Fatal("incognito money merged")
		}
	}
	if len(groups) != 4 {
		t.Fatalf("privacy categories merged: %+v", groups)
	}
	encoded, _ := json.Marshal(groups)
	for _, forbidden := range []string{"source_row_id", "user_id", "@", "system_attribution"} {
		if strings.Contains(string(encoded), forbidden) {
			t.Fatal("source identity leaked")
		}
	}
}
func TestSummaryCoverageAndStaleness(t *testing.T) {
	now := instant()
	at := now.Add(-48 * time.Hour)
	start := coverage().From.Add(-24 * time.Hour)
	published := protocol.PublishedSnapshot{Revision: 3, PublishedAt: now.Add(-120 * time.Second), Coverage: protocol.Coverage{From: start, To: coverage().To}}
	s := syncState{ActivatedAt: at, CollectionStart: start, Published: &published, Covered: []coveredWindow{{Coverage: published.Coverage, PublishedAt: published.PublishedAt, Revision: 3}}}
	q := protocol.UsageQuery{Start: start.Add(-24 * time.Hour), End: coverage().To}
	summary, ok := summaryBase(s, q, now)
	if !ok || summary.Status != "ready" || summary.Coverage.From != start {
		t.Fatalf("wrong coverage %+v", summary)
	}
	summary, ok = summaryBase(s, q, now.Add(time.Nanosecond))
	if !ok || summary.Status != "stale" {
		t.Fatal("120 second stale boundary lost")
	}
	s.Covered = []coveredWindow{{Coverage: protocol.Coverage{From: start, To: coverage().From}, PublishedAt: now, Revision: 3}}
	summary, ok = summaryBase(s, q, now)
	if ok || summary.Status != "unavailable" || summary.Coverage != nil {
		t.Fatal("uncovered day reported as zero")
	}
}
func TestCoverageReplacementDoesNotRefreshUnchangedDays(t *testing.T) {
	now := instant()
	old := coveredWindow{Coverage: protocol.Coverage{From: coverage().From.Add(-48 * time.Hour), To: coverage().To}, PublishedAt: now.Add(-time.Hour), Revision: 1}
	next := coveredWindow{Coverage: coverage(), PublishedAt: now, Revision: 2}
	windows := replaceCoverage([]coveredWindow{old}, next)
	if len(windows) != 2 || windows[0].PublishedAt != old.PublishedAt || windows[0].Coverage.To != next.Coverage.From {
		t.Fatalf("old coverage refreshed %+v", windows)
	}
}
func TestBeginWaitingAndPersistentBoundary(t *testing.T) {
	now := instant()
	s := syncState{ActivatedAt: now, CollectionStart: collectionStart(now)}
	waiting, err := planBegin(s, coverage(), "request", now)
	if err != nil || waiting.Lease.Status != "waiting" || waiting.Revision != 0 || waiting.Lease.Coverage != nil {
		t.Fatalf("premature lease %+v %v", waiting, err)
	}
	c := protocol.Coverage{From: coverage().From, To: coverage().To.Add(24 * time.Hour)}
	ready, err := planBegin(waiting, c, "request", coverage().To.Add(time.Hour))
	if err != nil || ready.Lease.Coverage.From != s.CollectionStart || ready.Lease.ActivatedAt != now || ready.Lease.Revision != 1 || ready.Lease.ExpiresAt.Sub(coverage().To.Add(time.Hour)) != 45*time.Second {
		t.Fatalf("activation changed %+v %v", ready, err)
	}
	if _, err = planBegin(ready, c, "other", coverage().To.Add(time.Hour)); err == nil {
		t.Fatal("two active leases")
	}
	retry, err := planBegin(ready, c, "request", coverage().To.Add(time.Hour))
	if err != nil || retry.Revision != ready.Revision {
		t.Fatal("begin retry changed revision")
	}
	next, err := planBegin(ready, c, "next", *ready.Lease.ExpiresAt)
	if err != nil || next.Revision != 2 {
		t.Fatal("expired lease did not advance")
	}
}

func TestSummaryClipsOnlyLeadingUncoveredDays(t *testing.T) {
	now := instant()
	start := coverage().From.Add(-72 * time.Hour)
	p := protocol.PublishedSnapshot{Revision: 2, PublishedAt: now, Coverage: coverage()}
	s := syncState{ActivatedAt: start.Add(-time.Hour), CollectionStart: start, Published: &p, Covered: []coveredWindow{{Coverage: coverage(), PublishedAt: now, Revision: 2}}}
	q := protocol.UsageQuery{Start: start, End: coverage().To}
	summary, ok := summaryBase(s, q, now)
	if !ok || summary.Coverage.From != coverage().From {
		t.Fatalf("leading prefix not disclosed %+v", summary)
	}
	s.Covered = append([]coveredWindow{{Coverage: protocol.Coverage{From: start, To: start.Add(24 * time.Hour)}, PublishedAt: now, Revision: 1}}, s.Covered...)
	if _, ok = summaryBase(s, q, now); ok {
		t.Fatal("internal uncovered days were skipped")
	}
	s.Covered = s.Covered[:1]
	if _, ok = summaryBase(s, q, now); ok {
		t.Fatal("trailing uncovered days were skipped")
	}
}

func TestBeginReplayUsesEqualUTCCoverage(t *testing.T) {
	now := instant()
	c := coverage()
	s := syncState{ActivatedAt: c.From.Add(-time.Hour), CollectionStart: c.From}
	first, err := planBegin(s, c, "same", now)
	if err != nil {
		t.Fatal(err)
	}
	offset := time.FixedZone("zero-offset", 0)
	c.From = c.From.In(offset)
	c.To = c.To.In(offset)
	again, err := planBegin(first, c, "same", now)
	if err != nil || again.Revision != first.Revision {
		t.Fatal("equivalent UTC coverage changed begin", err)
	}
}

func TestSummaryHasNoMixedActorGrandTotal(t *testing.T) {
	now := instant()
	s, _ := summaryBase(syncState{}, protocol.UsageQuery{}, now)
	data, _ := json.Marshal(s)
	var shape map[string]any
	json.Unmarshal(data, &shape)
	if _, exists := shape["totals"]; exists {
		t.Fatal("summary exposed a mixed USER/SYSTEM grand total")
	}
	if _, exists := shape["group_by"]; !exists {
		t.Fatal("summary lacks its selected dimension")
	}
}

func TestSummaryGroupsOnlyAllowlistedDimensions(t *testing.T) {
	rows := []protocol.SnapshotRow{row(1), row(2)}
	rows[1].WindowStart = rows[1].WindowStart.Add(24 * time.Hour)
	rows[1].Model = "different"
	rows[1].Flow = "embed"
	for _, by := range []string{"day", "model", "flow"} {
		groups, err := aggregate(slices.Values(rows), by)
		if err != nil || len(groups) != 2 {
			t.Fatalf("%s grouping failed %+v %v", by, groups, err)
		}
		for _, g := range groups {
			if g.Totals.TotalTokens != "15" {
				t.Fatal("dimension totals combined")
			}
		}
	}
}
func TestSummaryGroupOverflowRejectsWholeResponse(t *testing.T) {
	rows := make([]protocol.SnapshotRow, 1001)
	for i := range rows {
		rows[i] = row(int64(i + 1))
		rows[i].Model = fmt.Sprintf("model-%d", i)
	}
	groups, err := aggregate(slices.Values(rows), "model")
	if err == nil || groups != nil {
		t.Fatal("group overflow returned partial totals")
	}
	groups, err = aggregate(slices.Values(rows), "day")
	if err != nil || len(groups) != 1 || groups[0].Totals.TotalTokens != "15015" {
		t.Fatal("day grouping failed after model overflow")
	}
}
