// SPDX-License-Identifier: MIT
package usage

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"orgmesh.local/enterprise/internal/protocol"
)

var sourceCost = regexp.MustCompile(`^(0|[1-9][0-9]{0,11})\.[0-9]{6}$`)
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

func validateRow(r protocol.SnapshotRow, c protocol.Coverage) error {
	if r.SourceRowID <= 0 || !protocol.UTCMidnight(r.WindowStart) || r.WindowStart.Before(c.From) || !r.WindowStart.Before(c.To) || r.InputTokens < 0 || r.OutputTokens < 0 || r.CacheReadTokens < 0 || r.CacheCreationTokens < 0 || !sourceCost.MatchString(r.CostCents) {
		return protocol.ErrInvalid
	}
	for _, value := range []string{r.Model, r.Flow, r.Provider} {
		if !utf8.ValidString(value) || strings.ContainsRune(value, 0) || utf8.RuneCountInString(value) > 512 {
			return protocol.ErrInvalid
		}
	}
	if r.Model == "" || r.Flow == "" {
		return protocol.ErrInvalid
	}
	if r.UserID != nil && !protocol.ValidUUID(*r.UserID) {
		return protocol.ErrInvalid
	}
	switch r.ActorKind {
	case "USER":
		if r.SystemAttribution != nil {
			return protocol.ErrInvalid
		}
	case "SYSTEM":
		if r.UserID != nil || r.Incognito || r.SystemAttribution == nil || (*r.SystemAttribution != "ATTRIBUTED" && *r.SystemAttribution != "UNATTRIBUTED") {
			return protocol.ErrInvalid
		}
	default:
		return protocol.ErrInvalid
	}
	return nil
}
func field(b *bytes.Buffer, s string) {
	binary.Write(b, binary.BigEndian, uint32(len([]byte(s))))
	b.WriteString(s)
}
func nullable(b *bytes.Buffer, s *string) {
	if s == nil {
		binary.Write(b, binary.BigEndian, uint32(math.MaxUint32))
		return
	}
	field(b, *s)
}
func number(b *bytes.Buffer, n int64) { field(b, strconv.FormatInt(n, 10)) }
func hash(b []byte) string            { d := sha256.Sum256(b); return hex.EncodeToString(d[:]) }

// BatchDigest binds typed values, independent of JSON whitespace and escaping.
func BatchDigest(batch protocol.SnapshotBatch) (string, error) {
	if batch.Index < 0 || batch.Index >= protocol.MaxSnapshotRows || len(batch.Rows) > protocol.MaxBatchRows || batch.Rows == nil {
		return "", protocol.ErrInvalid
	}
	var b bytes.Buffer
	b.WriteString("orgmesh.usage.batch.v1\x00")
	number(&b, int64(batch.Index))
	number(&b, int64(len(batch.Rows)))
	for _, r := range batch.Rows {
		number(&b, r.SourceRowID)
		field(&b, r.ActorKind)
		nullable(&b, r.UserID)
		nullable(&b, r.SystemAttribution)
		field(&b, r.WindowStart.UTC().Format(time.RFC3339))
		field(&b, r.Model)
		field(&b, r.Flow)
		field(&b, r.Provider)
		field(&b, strconv.FormatBool(r.Incognito))
		number(&b, r.InputTokens)
		number(&b, r.OutputTokens)
		number(&b, r.CacheReadTokens)
		number(&b, r.CacheCreationTokens)
		field(&b, r.CostCents)
	}
	return hash(b.Bytes()), nil
}
func validateBatch(batch protocol.SnapshotBatch, c protocol.Coverage) (protocol.StageAck, error) {
	if len(batch.Rows) < 1 || len(batch.Rows) > protocol.MaxBatchRows || !digestPattern.MatchString(batch.Digest) {
		return protocol.StageAck{}, protocol.ErrInvalid
	}
	encoded, err := json.Marshal(batch)
	if err != nil || len(encoded) > protocol.MaxBytes {
		return protocol.StageAck{}, protocol.ErrInvalid
	}
	seen := map[int64]bool{}
	for _, r := range batch.Rows {
		if validateRow(r, c) != nil || seen[r.SourceRowID] {
			return protocol.StageAck{}, protocol.ErrInvalid
		}
		seen[r.SourceRowID] = true
	}
	digest, err := BatchDigest(batch)
	if err != nil || batch.Digest != digest {
		return protocol.StageAck{}, protocol.ErrInvalid
	}
	return protocol.StageAck{Index: batch.Index, Digest: digest, RowCount: len(batch.Rows), ByteCount: len(encoded)}, nil
}

// ManifestDigest binds the revision, coverage and all ordered batch receipts.
func ManifestDigest(lease protocol.SnapshotLease, m protocol.SnapshotManifest) (string, error) {
	if lease.Revision < 1 || lease.Coverage == nil || lease.Coverage.Validate() != nil || !m.Complete || m.Batches == nil || m.TotalRows < 0 || m.TotalRows > protocol.MaxSnapshotRows || m.TotalBytes < 0 || m.TotalBytes > protocol.MaxSnapshotBytes {
		return "", protocol.ErrInvalid
	}
	var b bytes.Buffer
	b.WriteString("orgmesh.usage.manifest.v1\x00")
	number(&b, lease.Revision)
	field(&b, lease.Coverage.From.UTC().Format(time.RFC3339))
	field(&b, lease.Coverage.To.UTC().Format(time.RFC3339))
	field(&b, "true")
	number(&b, int64(m.TotalRows))
	number(&b, int64(m.TotalBytes))
	number(&b, int64(len(m.Batches)))
	rows, size := 0, 0
	for i, ack := range m.Batches {
		if ack.Index != i || ack.RowCount < 1 || ack.RowCount > protocol.MaxBatchRows || ack.ByteCount < 1 || ack.ByteCount > protocol.MaxBytes || !digestPattern.MatchString(ack.Digest) {
			return "", protocol.ErrInvalid
		}
		rows += ack.RowCount
		size += ack.ByteCount
		number(&b, int64(ack.Index))
		field(&b, ack.Digest)
		number(&b, int64(ack.RowCount))
		number(&b, int64(ack.ByteCount))
	}
	if rows != m.TotalRows || size != m.TotalBytes {
		return "", protocol.ErrInvalid
	}
	return hash(b.Bytes()), nil
}
func checkLease(s syncState, l protocol.SnapshotLease, now time.Time) error {
	stored := s.Lease
	if (s.Published != nil && s.Published.Revision >= l.Revision) || s.Failed || l.Status != "ready" || l.Revision < 1 || l.Revision != s.Revision || l.Revision != stored.Revision || l.Coverage == nil || stored.Coverage == nil || l.ExpiresAt == nil || stored.ExpiresAt == nil || !l.ExpiresAt.Equal(*stored.ExpiresAt) || !l.ExpiresAt.After(now) || !l.Coverage.From.Equal(stored.Coverage.From) || !l.Coverage.To.Equal(stored.Coverage.To) || !l.ActivatedAt.Equal(stored.ActivatedAt) || !l.CollectionStart.Equal(stored.CollectionStart) {
		return protocol.ErrConflict
	}
	return nil
}

func planBegin(s syncState, c protocol.Coverage, requestID string, now time.Time) (syncState, error) {
	if c.Validate() != nil || c.From.Before(now.UTC().Truncate(24*time.Hour).Add(-89*24*time.Hour)) || c.To.After(collectionStart(now)) {
		return s, protocol.ErrInvalid
	}
	if now.Before(s.CollectionStart) {
		s.Lease = protocol.SnapshotLease{Status: "waiting", ActivatedAt: s.ActivatedAt, CollectionStart: s.CollectionStart}
		return s, nil
	}
	if c.From.Before(s.CollectionStart) {
		c.From = s.CollectionStart
	}
	if !c.To.After(c.From) {
		return s, protocol.ErrInvalid
	}
	if s.Lease.Status == "ready" && !s.Failed && s.Lease.ExpiresAt != nil && s.Lease.ExpiresAt.After(now) && (s.Published == nil || s.Published.Revision < s.Revision) {
		if s.BeginRequestID == requestID && s.Lease.Coverage != nil && s.Lease.Coverage.From.Equal(c.From) && s.Lease.Coverage.To.Equal(c.To) {
			return s, nil
		}
		return s, protocol.ErrConflict
	}
	if s.Revision == math.MaxInt64 {
		return s, protocol.ErrUnavailable
	}
	s.Revision++
	expires := now.Add(LeaseDuration)
	s.Lease = protocol.SnapshotLease{Status: "ready", Revision: s.Revision, ActivatedAt: s.ActivatedAt, CollectionStart: s.CollectionStart, Coverage: &c, ExpiresAt: &expires}
	s.BeginRequestID = requestID
	s.Failed = false
	s.StagedRows = 0
	s.StagedBytes = 0
	return s, nil
}
