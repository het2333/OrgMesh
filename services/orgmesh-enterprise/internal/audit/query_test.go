// SPDX-License-Identifier: MIT
package audit

import (
	"encoding/base64"
	"testing"
	"time"

	"orgmesh.local/enterprise/internal/protocol"
)

func TestCursorPreservesStableOrdering(t *testing.T) {
	event := protocol.AuditEvent{CreatedAt: time.Date(2026, 10, 12, 10, 0, 0, 123456000, time.UTC), EventID: "11111111-1111-4111-8111-111111111111"}
	token := encodeCursor(event)
	cursor, err := decodeCursor(token)
	if err != nil || !cursor.CreatedAt.Equal(event.CreatedAt) || cursor.EventID != event.EventID {
		t.Fatalf("cursor: %+v %v", cursor, err)
	}
}
func TestInvalidCursorRejected(t *testing.T) {
	for _, token := range []string{"!", base64.RawURLEncoding.EncodeToString([]byte(`{"created_at":"2026-10-12T10:00:00Z","event_id":"nope"}`)), base64.RawURLEncoding.EncodeToString([]byte(`{"created_at":"2026-10-12T10:00:00Z","event_id":"11111111-1111-4111-8111-111111111111","tenant_id":"victim"}`))} {
		if _, err := decodeCursor(token); err == nil {
			t.Fatalf("accepted %s", token)
		}
	}
}
