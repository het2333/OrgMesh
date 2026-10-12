// SPDX-License-Identifier: MIT
package protocol

import (
	"math/big"
	"regexp"
	"time"
	"unicode/utf8"
)

const MaxUsageGroups = 1000
const MaxBatchRows = 1000
const MaxSnapshotRows = 100000
const MaxSnapshotBytes = 64 << 20
const UsageCostNotice = "Source-estimated USD cents; 0 may mean missing pricing. Not settled charges."

// Coverage selects whole UTC daily buckets, including the current mutable day.
type Coverage struct {
	From time.Time `json:"from"`
	To   time.Time `json:"to"`
}

func UTCMidnight(t time.Time) bool {
	_, offset := t.Zone()
	return !t.IsZero() && offset == 0 && t.Hour() == 0 && t.Minute() == 0 && t.Second() == 0 && t.Nanosecond() == 0
}
func (c Coverage) Validate() error {
	if !UTCMidnight(c.From) || !UTCMidnight(c.To) || !c.To.After(c.From) || c.To.Sub(c.From) > 90*24*time.Hour {
		return ErrInvalid
	}
	return nil
}

type SnapshotRow struct {
	SourceRowID         int64     `json:"source_row_id"`
	ActorKind           string    `json:"actor_kind"`
	UserID              *string   `json:"user_id"`
	SystemAttribution   *string   `json:"system_attribution"`
	WindowStart         time.Time `json:"window_start"`
	Model               string    `json:"model"`
	Flow                string    `json:"flow"`
	Provider            string    `json:"provider"`
	Incognito           bool      `json:"incognito"`
	InputTokens         int64     `json:"input_tokens"`
	OutputTokens        int64     `json:"output_tokens"`
	CacheReadTokens     int64     `json:"cache_read_tokens"`
	CacheCreationTokens int64     `json:"cache_creation_tokens"`
	CostCents           string    `json:"cost_cents"`
}
type SnapshotLease struct {
	Status          string     `json:"status"`
	Revision        int64      `json:"revision"`
	ActivatedAt     time.Time  `json:"activated_at"`
	CollectionStart time.Time  `json:"collection_start"`
	Coverage        *Coverage  `json:"coverage"`
	ExpiresAt       *time.Time `json:"expires_at"`
}
type SnapshotBatch struct {
	Index  int           `json:"index"`
	Rows   []SnapshotRow `json:"rows"`
	Digest string        `json:"digest"`
}
type StageAck struct {
	Index     int    `json:"index"`
	Digest    string `json:"digest"`
	RowCount  int    `json:"row_count"`
	ByteCount int    `json:"byte_count"`
}
type SnapshotManifest struct {
	Complete   bool       `json:"complete"`
	Batches    []StageAck `json:"batches"`
	TotalRows  int        `json:"total_rows"`
	TotalBytes int        `json:"total_bytes"`
	Digest     string     `json:"digest"`
}
type PublishedSnapshot struct {
	Revision    int64     `json:"revision"`
	Digest      string    `json:"digest"`
	Coverage    Coverage  `json:"coverage"`
	PublishedAt time.Time `json:"published_at"`
	TotalRows   int       `json:"total_rows"`
	TotalBytes  int       `json:"total_bytes"`
}
type UsageBeginRequest struct {
	Operation Operation `json:"operation"`
	Coverage  Coverage  `json:"coverage"`
}
type UsageStageRequest struct {
	Operation Operation     `json:"operation"`
	Lease     SnapshotLease `json:"lease"`
	Batch     SnapshotBatch `json:"batch"`
}
type UsageCommitRequest struct {
	Operation Operation        `json:"operation"`
	Lease     SnapshotLease    `json:"lease"`
	Manifest  SnapshotManifest `json:"manifest"`
}
type UsageBeginResponse struct {
	Operation Operation     `json:"operation"`
	Lease     SnapshotLease `json:"lease"`
}
type UsageStageResponse struct {
	Operation Operation `json:"operation"`
	Ack       StageAck  `json:"ack"`
}
type UsageCommitResponse struct {
	Operation Operation         `json:"operation"`
	Published PublishedSnapshot `json:"published"`
}

// String totals preserve large integers and source decimal precision in browsers.
type UsageTotals struct {
	InputTokens         string `json:"input_tokens"`
	OutputTokens        string `json:"output_tokens"`
	TotalTokens         string `json:"total_tokens"`
	CacheReadTokens     string `json:"cache_read_tokens"`
	CacheCreationTokens string `json:"cache_creation_tokens"`
	CostCents           string `json:"cost_cents"`
}
type UsageGroup struct {
	Value     string      `json:"value"`
	Category  string      `json:"category"`
	Incognito bool        `json:"incognito"`
	Totals    UsageTotals `json:"totals"`
}
type UsageSummary struct {
	GroupBy         string       `json:"group_by"`
	Status          string       `json:"status"`
	ActivatedAt     *time.Time   `json:"activated_at"`
	CollectionStart *time.Time   `json:"collection_start"`
	Coverage        *Coverage    `json:"coverage"`
	PublishedAt     *time.Time   `json:"published_at"`
	Revision        int64        `json:"revision"`
	Groups          []UsageGroup `json:"groups"`
	CostBasis       string       `json:"cost_basis"`
	CostNotice      string       `json:"cost_notice"`
}

var WholeNumberPattern = regexp.MustCompile(`^(0|[1-9][0-9]{0,31})$`)
var CostTotalPattern = regexp.MustCompile(`^(0|[1-9][0-9]{0,31})\.[0-9]{6}$`)

func (v UsageTotals) Validate() error {
	for _, n := range []string{v.InputTokens, v.OutputTokens, v.TotalTokens, v.CacheReadTokens, v.CacheCreationTokens} {
		if !WholeNumberPattern.MatchString(n) {
			return ErrInvalid
		}
	}
	input, _ := new(big.Int).SetString(v.InputTokens, 10)
	output, _ := new(big.Int).SetString(v.OutputTokens, 10)
	if new(big.Int).Add(input, output).String() != v.TotalTokens {
		return ErrInvalid
	}
	if !CostTotalPattern.MatchString(v.CostCents) {
		return ErrInvalid
	}
	return nil
}
func (s UsageSummary) Validate() error {
	if (s.GroupBy != "day" && s.GroupBy != "model" && s.GroupBy != "flow") || s.Groups == nil || len(s.Groups) > MaxUsageGroups || s.Revision < 0 || s.CostBasis != "source_estimate_usd_cents" || s.CostNotice != UsageCostNotice {
		return ErrInvalid
	}
	if s.Status != "ready" && s.Status != "stale" && s.Status != "waiting" && s.Status != "unavailable" {
		return ErrInvalid
	}
	if s.Status == "ready" || s.Status == "stale" {
		if s.Coverage == nil || s.Coverage.Validate() != nil || s.PublishedAt == nil || s.ActivatedAt == nil || s.CollectionStart == nil || s.Revision < 1 {
			return ErrInvalid
		}
	} else if s.Coverage != nil || len(s.Groups) > 0 {
		return ErrInvalid
	}
	seen := map[string]bool{}
	for _, g := range s.Groups {
		key := g.Value + "\x00" + g.Category
		if g.Incognito {
			key += "/incognito"
		}
		if g.Value == "" || !utf8.ValidString(g.Value) || utf8.RuneCountInString(g.Value) > 512 || seen[key] || g.Totals.Validate() != nil || (g.Category != "USER" && g.Category != "SYSTEM_ATTRIBUTED" && g.Category != "SYSTEM_UNATTRIBUTED") || (g.Category != "USER" && g.Incognito) {
			return ErrInvalid
		}
		seen[key] = true
	}
	return nil
}

var SHA256Pattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (l SnapshotLease) Validate() error {
	if l.ActivatedAt.IsZero() || !UTCMidnight(l.CollectionStart) || !l.CollectionStart.Equal(l.ActivatedAt.UTC().Truncate(24*time.Hour).Add(24*time.Hour)) {
		return ErrInvalid
	}
	if l.Status == "waiting" {
		if l.Revision != 0 || l.Coverage != nil || l.ExpiresAt != nil {
			return ErrInvalid
		}
		return nil
	}
	if l.Status != "ready" || l.Revision < 1 || l.Coverage == nil || l.Coverage.Validate() != nil || l.Coverage.From.Before(l.CollectionStart) || l.ExpiresAt == nil || l.ExpiresAt.IsZero() {
		return ErrInvalid
	}
	return nil
}
func (a StageAck) Validate() error {
	if a.Index < 0 || a.Index >= MaxSnapshotRows || a.RowCount < 1 || a.RowCount > MaxBatchRows || a.ByteCount < 1 || a.ByteCount > MaxBytes || !SHA256Pattern.MatchString(a.Digest) {
		return ErrInvalid
	}
	return nil
}
func (p PublishedSnapshot) Validate() error {
	if p.Revision < 1 || !SHA256Pattern.MatchString(p.Digest) || p.Coverage.Validate() != nil || p.PublishedAt.IsZero() || p.TotalRows < 0 || p.TotalRows > MaxSnapshotRows || p.TotalBytes < 0 || p.TotalBytes > MaxSnapshotBytes {
		return ErrInvalid
	}
	return nil
}

func (q UsageQuery) Grouping() string {
	if q.GroupBy == "" {
		return "day"
	}
	return q.GroupBy
}
