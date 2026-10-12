// SPDX-License-Identifier: MIT
package usage

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"orgmesh.local/enterprise/internal/protocol"
)

func loadState(ctx context.Context, tx pgx.Tx, tenant string, lock bool) (syncState, error) {
	var s syncState
	var lease, published, covered []byte
	suffix := ""
	if lock {
		suffix = " FOR UPDATE"
	}
	err := tx.QueryRow(ctx, `SELECT activated_at,collection_start,revision,lease,begin_request_id,failed,staged_rows,staged_bytes,published,published_coverage FROM orgmesh_enterprise.usage_sync_state WHERE tenant_id=$1`+suffix, tenant).Scan(&s.ActivatedAt, &s.CollectionStart, &s.Revision, &lease, &s.BeginRequestID, &s.Failed, &s.StagedRows, &s.StagedBytes, &published, &covered)
	if err != nil {
		return s, err
	}
	if json.Unmarshal(lease, &s.Lease) != nil || json.Unmarshal(published, &s.Published) != nil || json.Unmarshal(covered, &s.Covered) != nil {
		return s, protocol.ErrUnavailable
	}
	return s, nil
}
func saveState(ctx context.Context, tx pgx.Tx, tenant string, s syncState) error {
	lease, err := json.Marshal(s.Lease)
	if err != nil {
		return err
	}
	published, err := json.Marshal(s.Published)
	if err != nil {
		return err
	}
	covered, err := json.Marshal(s.Covered)
	if err != nil {
		return err
	}
	var cursor *time.Time
	if s.Published != nil {
		cursor = &s.Published.Coverage.To
	}
	_, err = tx.Exec(ctx, `UPDATE orgmesh_enterprise.usage_sync_state SET revision=$2,lease=$3::jsonb,begin_request_id=$4,failed=$5,staged_rows=$6,staged_bytes=$7,published=$8::jsonb,published_coverage=$9::jsonb,sync_cursor=$10 WHERE tenant_id=$1`, tenant, s.Revision, string(lease), s.BeginRequestID, s.Failed, s.StagedRows, s.StagedBytes, string(published), string(covered), cursor)
	return err
}
func (s *Service) authenticate(i protocol.Identity, op protocol.Operation) error {
	if protocol.ValidateIdentity(i, op, s.now(), s.tenant) != nil {
		return protocol.ErrInvalid
	}
	if s.db == nil {
		return protocol.ErrUnavailable
	}
	return nil
}
func (s *Service) BeginSnapshot(ctx context.Context, i protocol.Identity, c protocol.Coverage) (protocol.SnapshotLease, error) {
	if err := s.authenticate(i, protocol.UsageBeginOperation); err != nil {
		return protocol.SnapshotLease{}, err
	}
	now := s.now().UTC().Truncate(time.Microsecond)
	if c.Validate() != nil || c.From.Before(now.Truncate(24*time.Hour).Add(-89*24*time.Hour)) || c.To.After(collectionStart(now)) {
		return protocol.SnapshotLease{}, protocol.ErrInvalid
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return protocol.SnapshotLease{}, protocol.ErrUnavailable
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.usage_sync_state (tenant_id,activated_at,collection_start) VALUES ($1,$2,$3) ON CONFLICT (tenant_id) DO NOTHING`, s.tenant, now, collectionStart(now))
	if err != nil {
		return protocol.SnapshotLease{}, protocol.ErrUnavailable
	}
	state, err := loadState(ctx, tx, s.tenant, true)
	if err != nil {
		return protocol.SnapshotLease{}, protocol.ErrUnavailable
	}
	state, err = planBegin(state, c, i.RequestID, now)
	if err != nil {
		return protocol.SnapshotLease{}, err
	}
	if saveState(ctx, tx, s.tenant, state) != nil || tx.Commit(ctx) != nil {
		return protocol.SnapshotLease{}, protocol.ErrUnavailable
	}
	return state.Lease, nil
}
func failSnapshot(ctx context.Context, tx pgx.Tx, tenant string, state syncState, cause error) error {
	state.Failed = true
	if saveState(ctx, tx, tenant, state) != nil || tx.Commit(ctx) != nil {
		return protocol.ErrUnavailable
	}
	return cause
}
func (s *Service) StageBatch(ctx context.Context, i protocol.Identity, l protocol.SnapshotLease, b protocol.SnapshotBatch) (protocol.StageAck, error) {
	if err := s.authenticate(i, protocol.UsageStageOperation); err != nil {
		return protocol.StageAck{}, err
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	defer tx.Rollback(ctx)
	state, err := loadState(ctx, tx, s.tenant, true)
	if errors.Is(err, pgx.ErrNoRows) {
		return protocol.StageAck{}, protocol.ErrConflict
	}
	if err != nil {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	if err = checkLease(state, l, s.now()); err != nil {
		return protocol.StageAck{}, err
	}
	ack, err := validateBatch(b, *l.Coverage)
	if err != nil {
		return protocol.StageAck{}, failSnapshot(ctx, tx, s.tenant, state, err)
	}
	var old protocol.StageAck
	err = tx.QueryRow(ctx, `SELECT batch_index,digest,row_count,byte_count FROM orgmesh_enterprise.usage_batches WHERE tenant_id=$1 AND revision=$2 AND batch_index=$3`, s.tenant, l.Revision, b.Index).Scan(&old.Index, &old.Digest, &old.RowCount, &old.ByteCount)
	if err == nil {
		if ack != old {
			return protocol.StageAck{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrConflict)
		}
		return old, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	if state.StagedRows+ack.RowCount > protocol.MaxSnapshotRows || state.StagedBytes+ack.ByteCount > protocol.MaxSnapshotBytes {
		return protocol.StageAck{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrInvalid)
	}
	ids := make([]int64, len(b.Rows))
	for n, r := range b.Rows {
		ids[n] = r.SourceRowID
	}
	var duplicate bool
	if tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM orgmesh_enterprise.usage_staging WHERE tenant_id=$1 AND revision=$2 AND source_row_id=ANY($3::bigint[]))`, s.tenant, l.Revision, ids).Scan(&duplicate) != nil {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	if duplicate {
		return protocol.StageAck{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrInvalid)
	}
	_, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.usage_batches (tenant_id,revision,batch_index,digest,row_count,byte_count) VALUES ($1,$2,$3,$4,$5,$6)`, s.tenant, l.Revision, ack.Index, ack.Digest, ack.RowCount, ack.ByteCount)
	if err != nil {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	records := make([][]any, len(b.Rows))
	for n, r := range b.Rows {
		data, e := json.Marshal(r)
		if e != nil {
			return protocol.StageAck{}, protocol.ErrInvalid
		}
		records[n] = []any{s.tenant, l.Revision, r.SourceRowID, b.Index, n, r.WindowStart, string(data)}
	}
	_, err = tx.CopyFrom(ctx, pgx.Identifier{"orgmesh_enterprise", "usage_staging"}, []string{"tenant_id", "revision", "source_row_id", "batch_index", "row_index", "window_start", "row_data"}, pgx.CopyFromRows(records))
	if err != nil {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	state.StagedRows += ack.RowCount
	state.StagedBytes += ack.ByteCount
	if checkLease(state, l, s.now()) != nil {
		return protocol.StageAck{}, protocol.ErrConflict
	}
	if saveState(ctx, tx, s.tenant, state) != nil || tx.Commit(ctx) != nil {
		return protocol.StageAck{}, protocol.ErrUnavailable
	}
	return ack, nil
}
func (s *Service) CommitSnapshot(ctx context.Context, i protocol.Identity, l protocol.SnapshotLease, m protocol.SnapshotManifest) (protocol.PublishedSnapshot, error) {
	if err := s.authenticate(i, protocol.UsageCommitOperation); err != nil {
		return protocol.PublishedSnapshot{}, err
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	defer tx.Rollback(ctx)
	state, err := loadState(ctx, tx, s.tenant, true)
	if errors.Is(err, pgx.ErrNoRows) {
		return protocol.PublishedSnapshot{}, protocol.ErrConflict
	}
	if err != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	digest, digestError := ManifestDigest(l, m)
	// Only the latest issued revision can replay a committed receipt, even after expiry.
	if state.Published != nil && l.Revision == state.Revision && l.Revision == state.Published.Revision {
		if digestError != nil || digest != m.Digest || m.Digest != state.Published.Digest || !sameLease(state.Lease, l) {
			return protocol.PublishedSnapshot{}, protocol.ErrConflict
		}
		return *state.Published, nil
	}
	if err = checkLease(state, l, s.now()); err != nil {
		return protocol.PublishedSnapshot{}, err
	}
	if digestError != nil || digest != m.Digest || m.TotalRows != state.StagedRows || m.TotalBytes != state.StagedBytes {
		return protocol.PublishedSnapshot{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrInvalid)
	}
	refs, err := readBatchRefs(ctx, tx, s.tenant, l.Revision)
	if err != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	if len(refs) != len(m.Batches) {
		return protocol.PublishedSnapshot{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrInvalid)
	}
	for n, ref := range refs {
		if ref != m.Batches[n] {
			return protocol.PublishedSnapshot{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrInvalid)
		}
	}
	if err = verifyStaging(ctx, tx, s.tenant, l, refs); err != nil {
		if errors.Is(err, protocol.ErrInvalid) {
			return protocol.PublishedSnapshot{}, failSnapshot(ctx, tx, s.tenant, state, err)
		}
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	// A stable source ID cannot silently move a row from an uncovered day.
	var collision bool
	if tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM orgmesh_enterprise.usage_rows r JOIN orgmesh_enterprise.usage_staging s ON r.tenant_id=s.tenant_id AND r.source_row_id=s.source_row_id WHERE r.tenant_id=$1 AND s.tenant_id=$1 AND s.revision=$2 AND (r.window_start < $3 OR r.window_start >= $4))`, s.tenant, l.Revision, l.Coverage.From, l.Coverage.To).Scan(&collision) != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	if collision {
		return protocol.PublishedSnapshot{}, failSnapshot(ctx, tx, s.tenant, state, protocol.ErrInvalid)
	}
	if _, err = tx.Exec(ctx, `DELETE FROM orgmesh_enterprise.usage_rows WHERE tenant_id=$1 AND window_start >= $2 AND window_start < $3`, s.tenant, l.Coverage.From, l.Coverage.To); err != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	if _, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.usage_rows (tenant_id,source_row_id,revision,window_start,row_data) SELECT tenant_id,source_row_id,revision,window_start,row_data FROM orgmesh_enterprise.usage_staging WHERE tenant_id=$1 AND revision=$2`, s.tenant, l.Revision); err != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	now := s.now().UTC().Truncate(time.Microsecond)
	if checkLease(state, l, now) != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrConflict
	}
	published := protocol.PublishedSnapshot{Revision: l.Revision, Digest: digest, Coverage: *l.Coverage, PublishedAt: now, TotalRows: m.TotalRows, TotalBytes: m.TotalBytes}
	state.Published = &published
	state.Covered = replaceCoverage(state.Covered, coveredWindow{Coverage: *l.Coverage, PublishedAt: now, Revision: l.Revision})
	if saveState(ctx, tx, s.tenant, state) != nil || tx.Commit(ctx) != nil {
		return protocol.PublishedSnapshot{}, protocol.ErrUnavailable
	}
	return published, nil
}
func sameLease(a, b protocol.SnapshotLease) bool {
	return a.Status == b.Status && a.Revision == b.Revision && a.Coverage != nil && b.Coverage != nil && a.Coverage.From.Equal(b.Coverage.From) && a.Coverage.To.Equal(b.Coverage.To) && a.ExpiresAt != nil && b.ExpiresAt != nil && a.ExpiresAt.Equal(*b.ExpiresAt) && a.ActivatedAt.Equal(b.ActivatedAt) && a.CollectionStart.Equal(b.CollectionStart)
}
func readBatchRefs(ctx context.Context, tx pgx.Tx, tenant string, revision int64) ([]protocol.StageAck, error) {
	rows, err := tx.Query(ctx, `SELECT batch_index,digest,row_count,byte_count FROM orgmesh_enterprise.usage_batches WHERE tenant_id=$1 AND revision=$2 ORDER BY batch_index`, tenant, revision)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	refs := []protocol.StageAck{}
	for rows.Next() {
		var a protocol.StageAck
		if err = rows.Scan(&a.Index, &a.Digest, &a.RowCount, &a.ByteCount); err != nil {
			return nil, err
		}
		refs = append(refs, a)
	}
	return refs, rows.Err()
}
func verifyStaging(ctx context.Context, tx pgx.Tx, tenant string, l protocol.SnapshotLease, refs []protocol.StageAck) error {
	rows, err := tx.Query(ctx, `SELECT batch_index,row_index,source_row_id,window_start,row_data FROM orgmesh_enterprise.usage_staging WHERE tenant_id=$1 AND revision=$2 ORDER BY batch_index,row_index`, tenant, l.Revision)
	if err != nil {
		return err
	}
	defer rows.Close()
	batch := protocol.SnapshotBatch{Index: 0, Rows: []protocol.SnapshotRow{}}
	position := 0
	verify := func() error {
		if position >= len(refs) {
			return protocol.ErrInvalid
		}
		batch.Digest = refs[position].Digest
		ack, e := validateBatch(batch, *l.Coverage)
		if e != nil || ack != refs[position] {
			return protocol.ErrInvalid
		}
		position++
		batch = protocol.SnapshotBatch{Index: position, Rows: []protocol.SnapshotRow{}}
		return nil
	}
	for rows.Next() {
		var index, rowIndex int
		var id int64
		var at time.Time
		var data []byte
		var row protocol.SnapshotRow
		if rows.Scan(&index, &rowIndex, &id, &at, &data) != nil || json.Unmarshal(data, &row) != nil {
			return protocol.ErrInvalid
		}
		if index != batch.Index {
			if len(batch.Rows) == 0 || verify() != nil {
				return protocol.ErrInvalid
			}
		}
		if index != batch.Index || rowIndex != len(batch.Rows) || id != row.SourceRowID || !at.Equal(row.WindowStart) || len(batch.Rows) >= protocol.MaxBatchRows {
			return protocol.ErrInvalid
		}
		batch.Rows = append(batch.Rows, row)
	}
	if rows.Err() != nil {
		return rows.Err()
	}
	if len(batch.Rows) > 0 {
		if err = verify(); err != nil {
			return err
		}
	}
	if position != len(refs) {
		return protocol.ErrInvalid
	}
	return nil
}
