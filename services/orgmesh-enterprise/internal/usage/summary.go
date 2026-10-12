// SPDX-License-Identifier: MIT
package usage

import (
	"context"
	"encoding/json"
	"errors"
	"iter"
	"log/slog"
	"math/big"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"orgmesh.local/enterprise/internal/protocol"
)

type coveredWindow struct {
	Coverage    protocol.Coverage `json:"coverage"`
	PublishedAt time.Time         `json:"published_at"`
	Revision    int64             `json:"revision"`
}

func replaceCoverage(old []coveredWindow, next coveredWindow) []coveredWindow {
	result := make([]coveredWindow, 0, len(old)+2)
	for _, w := range old {
		if !w.Coverage.To.After(next.Coverage.From) || !w.Coverage.From.Before(next.Coverage.To) {
			result = append(result, w)
			continue
		}
		if w.Coverage.From.Before(next.Coverage.From) {
			left := w
			left.Coverage.To = next.Coverage.From
			result = append(result, left)
		}
		if w.Coverage.To.After(next.Coverage.To) {
			right := w
			right.Coverage.From = next.Coverage.To
			result = append(result, right)
		}
	}
	result = append(result, next)
	sort.Slice(result, func(i, j int) bool { return result[i].Coverage.From.Before(result[j].Coverage.From) })
	return result
}

type sums struct{ input, output, read, creation, cost big.Int }

func (s *sums) add(r protocol.SnapshotRow) {
	s.input.Add(&s.input, big.NewInt(r.InputTokens))
	s.output.Add(&s.output, big.NewInt(r.OutputTokens))
	s.read.Add(&s.read, big.NewInt(r.CacheReadTokens))
	s.creation.Add(&s.creation, big.NewInt(r.CacheCreationTokens))
	n, _ := new(big.Int).SetString(strings.ReplaceAll(r.CostCents, ".", ""), 10)
	s.cost.Add(&s.cost, n)
}
func (s *sums) totals() protocol.UsageTotals {
	c := s.cost.String()
	if len(c) < 7 {
		c = strings.Repeat("0", 7-len(c)) + c
	}
	c = c[:len(c)-6] + "." + c[len(c)-6:]
	return protocol.UsageTotals{InputTokens: s.input.String(), OutputTokens: s.output.String(), TotalTokens: new(big.Int).Add(&s.input, &s.output).String(), CacheReadTokens: s.read.String(), CacheCreationTokens: s.creation.String(), CostCents: c}
}
func aggregate(rows iter.Seq[protocol.SnapshotRow], groupBy string) ([]protocol.UsageGroup, error) {
	type key struct {
		value, category string
		incognito       bool
	}
	groups := map[key]*sums{}
	for r := range rows {
		value := r.WindowStart.UTC().Format("2006-01-02")
		switch groupBy {
		case "model":
			value = r.Model
		case "flow":
			value = r.Flow
		}
		k := key{value: value, category: category(r), incognito: r.Incognito}
		if groups[k] == nil {
			if len(groups) >= protocol.MaxUsageGroups {
				slog.Warn("usage summary refused", "reason", "group_limit")
				return nil, protocol.ErrUnavailable
			}
			groups[k] = &sums{}
		}
		groups[k].add(r)
	}
	keys := make([]key, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		a, b := keys[i], keys[j]
		if a.value != b.value {
			return a.value < b.value
		}
		if a.category != b.category {
			return a.category < b.category
		}
		return !a.incognito && b.incognito
	})
	result := make([]protocol.UsageGroup, 0, len(groups))
	for _, k := range keys {
		result = append(result, protocol.UsageGroup{Value: k.value, Category: k.category, Incognito: k.incognito, Totals: groups[k].totals()})
	}
	return result, nil
}
func summaryBase(s syncState, q protocol.UsageQuery, now time.Time) (protocol.UsageSummary, bool) {
	result := protocol.UsageSummary{Status: "unavailable", GroupBy: q.Grouping(), Groups: []protocol.UsageGroup{}, CostBasis: "source_estimate_usd_cents", CostNotice: protocol.UsageCostNotice}
	if s.ActivatedAt.IsZero() {
		return result, false
	}
	result.ActivatedAt = &s.ActivatedAt
	result.CollectionStart = &s.CollectionStart
	if now.Before(s.CollectionStart) {
		result.Status = "waiting"
		return result, false
	}
	start := q.Start
	if start.Before(s.CollectionStart) {
		start = s.CollectionStart
	}
	if !q.End.After(start) || s.Published == nil {
		return result, false
	}
	// A leading unpublished prefix can be disclosed and clipped. Later gaps cannot.
	for _, w := range s.Covered {
		if w.Coverage.To.After(start) {
			if w.Coverage.From.After(start) {
				start = w.Coverage.From
			}
			break
		}
	}
	if !q.End.After(start) {
		return result, false
	}
	cursor := start
	oldest := now
	for _, w := range s.Covered {
		if !w.Coverage.To.After(cursor) {
			continue
		}
		if !w.Coverage.From.Before(q.End) {
			break
		}
		if w.Coverage.From.After(cursor) {
			return result, false
		}
		if w.PublishedAt.Before(oldest) {
			oldest = w.PublishedAt
		}
		cursor = w.Coverage.To
		if !cursor.Before(q.End) {
			break
		}
	}
	if cursor.Before(q.End) {
		return result, false
	}
	result.Coverage = &protocol.Coverage{From: start, To: q.End}
	result.PublishedAt = &oldest
	result.Revision = s.Published.Revision
	result.Status = "ready"
	if now.Sub(oldest) > StaleAfter {
		result.Status = "stale"
	}
	return result, true
}
func (s *Service) Summary(ctx context.Context, tenant string, q protocol.UsageQuery) (protocol.UsageSummary, error) {
	if tenant == "" || tenant != s.tenant || q.Validate(s.now()) != nil {
		return protocol.UsageSummary{}, protocol.ErrInvalid
	}
	if s.db == nil {
		return protocol.UsageSummary{}, protocol.ErrUnavailable
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return protocol.UsageSummary{}, protocol.ErrUnavailable
	}
	defer tx.Rollback(ctx)
	state, err := loadState(ctx, tx, tenant, false)
	if errors.Is(err, pgx.ErrNoRows) {
		state = syncState{}
	} else if err != nil {
		return protocol.UsageSummary{}, protocol.ErrUnavailable
	}
	summary, covered := summaryBase(state, q, s.now())
	if !covered {
		return summary, nil
	}
	result, err := tx.Query(ctx, `SELECT row_data FROM orgmesh_enterprise.usage_rows WHERE tenant_id=$1 AND window_start >= $2 AND window_start < $3 ORDER BY source_row_id`, tenant, summary.Coverage.From, summary.Coverage.To)
	if err != nil {
		return protocol.UsageSummary{}, protocol.ErrUnavailable
	}
	var rowError error
	var aggregateError error
	summary.Groups, aggregateError = aggregate(func(yield func(protocol.SnapshotRow) bool) {
		for result.Next() {
			var data []byte
			var row protocol.SnapshotRow
			if result.Scan(&data) != nil || json.Unmarshal(data, &row) != nil || validateRow(row, *summary.Coverage) != nil {
				rowError = protocol.ErrUnavailable
				return
			}
			if !yield(row) {
				return
			}
		}
	}, q.Grouping())
	err = result.Err()
	result.Close()
	if err != nil || rowError != nil || aggregateError != nil {
		return protocol.UsageSummary{}, protocol.ErrUnavailable
	}
	return summary, nil
}
