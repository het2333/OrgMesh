// SPDX-License-Identifier: MIT
package usage

import (
	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
	"time"
)

const LeaseDuration = 45 * time.Second
const StaleAfter = 120 * time.Second

type Service struct {
	db     *pgxpool.Pool
	tenant string
	now    func() time.Time
}

func New(db *pgxpool.Pool, tenant string, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, tenant: tenant, now: now}
}

type syncState struct {
	ActivatedAt     time.Time
	CollectionStart time.Time
	Revision        int64
	Lease           protocol.SnapshotLease
	BeginRequestID  string
	Failed          bool
	StagedRows      int
	StagedBytes     int
	Published       *protocol.PublishedSnapshot
	Covered         []coveredWindow
}

func collectionStart(at time.Time) time.Time {
	return at.UTC().Truncate(24 * time.Hour).Add(24 * time.Hour)
}
func category(r protocol.SnapshotRow) string {
	if r.ActorKind == "USER" {
		return "USER"
	}
	if r.SystemAttribution != nil && *r.SystemAttribution == "ATTRIBUTED" {
		return "SYSTEM_ATTRIBUTED"
	}
	return "SYSTEM_UNATTRIBUTED"
}
