// SPDX-License-Identifier: MIT
package audit

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
)

type Service struct {
	db     *pgxpool.Pool
	tenant string
}

func New(db *pgxpool.Pool, tenant string) *Service { return &Service{db: db, tenant: tenant} }
func (service *Service) List(ctx context.Context, tenant string, query protocol.AuditQuery) (protocol.AuditPage, error) {
	if service.tenant == "" || tenant != service.tenant || query.Validate() != nil {
		return protocol.AuditPage{}, protocol.ErrInvalid
	}
	var positionTime *time.Time
	positionID := "00000000-0000-0000-0000-000000000000"
	if query.Cursor != "" {
		position, err := decodeCursor(query.Cursor)
		if err != nil {
			return protocol.AuditPage{}, protocol.ErrInvalid
		}
		positionTime = &position.CreatedAt
		positionID = position.EventID
	}
	if service.db == nil {
		return protocol.AuditPage{}, protocol.ErrUnavailable
	}
	rows, err := service.db.Query(ctx, `SELECT event_id::text,created_at,user_id::text,actor_kind,resource_id,action,result,before_version,after_version,changed_fields,request_id::text FROM orgmesh_enterprise.audit_events WHERE tenant_id=$1 AND created_at >= $2 AND created_at < $3 AND ($4='' OR action=$4) AND ($5='' OR result=$5) AND ($6::timestamptz IS NULL OR (created_at,event_id) < ($6::timestamptz,$7::uuid)) ORDER BY created_at DESC,event_id DESC LIMIT $8`, tenant, query.Start, query.End, query.Action, query.Result, positionTime, positionID, query.Limit+1)
	if err != nil {
		return protocol.AuditPage{}, protocol.ErrUnavailable
	}
	defer rows.Close()
	page := protocol.AuditPage{Events: make([]protocol.AuditEvent, 0, query.Limit)}
	for rows.Next() {
		var event protocol.AuditEvent
		if err = rows.Scan(&event.EventID, &event.CreatedAt, &event.UserID, &event.ActorKind, &event.ResourceID, &event.Action, &event.Result, &event.BeforeVersion, &event.AfterVersion, &event.ChangedFields, &event.RequestID); err != nil {
			return protocol.AuditPage{}, protocol.ErrUnavailable
		}
		if len(page.Events) == query.Limit {
			next := encodeCursor(page.Events[len(page.Events)-1])
			page.NextCursor = &next
			break
		}
		page.Events = append(page.Events, event)
	}
	if rows.Err() != nil {
		return protocol.AuditPage{}, protocol.ErrUnavailable
	}
	return page, nil
}

type cursor struct {
	CreatedAt time.Time `json:"created_at"`
	EventID   string    `json:"event_id"`
}

func encodeCursor(event protocol.AuditEvent) string {
	data, _ := json.Marshal(cursor{CreatedAt: event.CreatedAt.UTC(), EventID: event.EventID})
	return base64.RawURLEncoding.EncodeToString(data)
}
func decodeCursor(token string) (cursor, error) {
	var position cursor
	if len(token) > 512 {
		return position, protocol.ErrInvalid
	}
	data, err := base64.RawURLEncoding.Strict().DecodeString(token)
	if err != nil || protocol.DecodeStrict(data, &position) != nil || position.CreatedAt.IsZero() || !protocol.ValidUUID(position.EventID) {
		return cursor{}, protocol.ErrInvalid
	}
	return position, nil
}
