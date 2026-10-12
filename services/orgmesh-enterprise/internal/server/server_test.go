package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"orgmesh.local/enterprise/internal/protocol"
)

type brandingFake struct {
	calls int
	large bool
}

func (s *brandingFake) Read(ctx context.Context, tenant string) (protocol.BrandingView, error) {
	s.calls++
	if tenant != "public" {
		panic("missing tenant filter")
	}
	name := "OrgMesh"
	if s.large {
		name = strings.Repeat("x", protocol.MaxBytes)
	}
	return protocol.BrandingView{Name: name, Greeting: "", LogoAssetID: "orgmesh-default", Version: 1, Source: "dynamic"}, nil
}
func (s *brandingFake) Apply(ctx context.Context, i protocol.Identity, p protocol.BrandingPatch) (protocol.BrandingView, error) {
	s.calls++
	return protocol.BrandingView{Name: p.Name, Greeting: p.Greeting, LogoAssetID: p.LogoAssetID, Version: 1, Source: "dynamic"}, nil
}
func requestBody(t *testing.T, actor string, op protocol.Operation) []byte {
	t.Helper()
	now := time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC)
	uid := "11111111-1111-4111-8111-111111111111"
	if actor == "anonymous" {
		uid = ""
	}
	b, e := json.Marshal(map[string]any{"version": 1, "identity": protocol.Identity{Version: 1, TenantID: "public", ActorKind: actor, UserID: uid, Operation: op, RequestID: "22222222-2222-4222-8222-222222222222", Audience: "orgmesh-enterprise/v1", IssuedAt: now, ExpiresAt: now.Add(5 * time.Second)}, "request": map[string]any{"operation": op}})
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func handler(store *brandingFake) http.Handler {
	return NewHandler(Dependencies{TenantID: "public", Branding: store, LogoAssetIDs: []string{"orgmesh-default"}, Now: func() time.Time { return time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC) }})
}
func TestAnonymousBrandingOnly(t *testing.T) {
	s := &brandingFake{}
	h := handler(s)
	for _, tc := range []struct {
		op   protocol.Operation
		want int
	}{{protocol.BrandingReadOperation, 200}, {protocol.AuditListOperation, 403}, {protocol.BrandingPatchOperation, 403}} {
		r := httptest.NewRequest("POST", "/v1/call", bytes.NewReader(requestBody(t, "anonymous", tc.op)))
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.want {
			t.Fatalf("%s: %d %s", tc.op, w.Code, w.Body.String())
		}
	}
	if s.calls != 1 {
		t.Fatal("unauthorized request reached store")
	}
}
func TestSizeBoundaries(t *testing.T) {
	s := &brandingFake{large: true}
	h := handler(s)
	for _, b := range [][]byte{requestBody(t, "anonymous", protocol.BrandingReadOperation), []byte(strings.Repeat("x", protocol.MaxBytes+1))} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/call", bytes.NewReader(b)))
		if w.Code != 503 && w.Code != 413 {
			t.Fatalf("unsafe result %d", w.Code)
		}
		if w.Body.Len() > protocol.MaxBytes {
			t.Fatal("oversized response escaped")
		}
	}
}
func TestNoStoreIsUnavailable(t *testing.T) {
	h := NewHandler(Dependencies{TenantID: "public", Now: func() time.Time { return time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC) }})
	for _, path := range []string{"/readyz", "/v1/call"} {
		w := httptest.NewRecorder()
		method := "GET"
		if path == "/v1/call" {
			method = "POST"
		}
		h.ServeHTTP(w, httptest.NewRequest(method, path, bytes.NewReader(requestBody(t, "anonymous", protocol.BrandingReadOperation))))
		if w.Code != 503 {
			t.Fatalf("pretended persistence: %d", w.Code)
		}
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/healthz", nil))
	if w.Code != 200 || strings.Contains(w.Body.String(), "public") {
		t.Fatal("health leaks configuration")
	}
}

func TestAuthenticatedPatch(t *testing.T) {
	s := &brandingFake{}
	envelope := map[string]any{}
	if err := json.Unmarshal(requestBody(t, "user", protocol.BrandingPatchOperation), &envelope); err != nil {
		t.Fatal(err)
	}
	envelope["request"] = map[string]any{"operation": "branding.patch", "patch": map[string]any{"expected_version": 0, "name": "OrgMesh", "greeting": "Welcome", "logo_asset_id": "orgmesh-default"}}
	body, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	handler(s).ServeHTTP(w, httptest.NewRequest("POST", "/v1/call", bytes.NewReader(body)))
	if w.Code != 200 || s.calls != 1 {
		t.Fatalf("patch rejected %d %s", w.Code, w.Body.String())
	}
	var result protocol.BrandingResponse
	if protocol.DecodeStrict(w.Body.Bytes(), &result) != nil || result.Branding.Greeting != "Welcome" || result.Operation != protocol.BrandingPatchOperation {
		t.Fatal("patch result contract changed")
	}
}
func TestOperationMismatchDoesNotReachStore(t *testing.T) {
	s := &brandingFake{}
	body := bytes.Replace(requestBody(t, "anonymous", protocol.BrandingReadOperation), []byte(`"request":{"operation":"branding.read"}`), []byte(`"request":{"operation":"branding.patch"}`), 1)
	w := httptest.NewRecorder()
	handler(s).ServeHTTP(w, httptest.NewRequest("POST", "/v1/call", bytes.NewReader(body)))
	if w.Code != 422 || s.calls != 0 {
		t.Fatalf("cross-operation request accepted %d", w.Code)
	}
}
func TestResponseLimit(t *testing.T) {
	w := httptest.NewRecorder()
	writeJSON(w, 200, map[string]string{"value": strings.Repeat("x", protocol.MaxBytes)})
	if w.Code != 503 || w.Body.Len() > protocol.MaxBytes {
		t.Fatal("oversized response escaped")
	}
}

func TestReadinessChecksStoreWithoutLeakingErrors(t *testing.T) {
	h := NewHandler(Dependencies{TenantID: "public", Branding: &brandingFake{}, Ready: func(context.Context) error { return errors.New("postgres://user:secret@database/private") }})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/readyz", nil))
	if w.Code != 503 || strings.Contains(w.Body.String(), "secret") {
		t.Fatalf("unsafe readiness: %d %s", w.Code, w.Body.String())
	}
}

func TestSnapshotRequestsUseProducerAndExactOperation(t *testing.T) {
	now := time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC)
	for _, op := range []protocol.Operation{protocol.UsageBeginOperation, protocol.UsageStageOperation, protocol.UsageCommitOperation} {
		var request any
		lease := protocol.SnapshotLease{Status: "waiting", ActivatedAt: now, CollectionStart: now.Truncate(24 * time.Hour).Add(24 * time.Hour)}
		switch op {
		case protocol.UsageBeginOperation:
			request = protocol.UsageBeginRequest{Operation: op, Coverage: protocol.Coverage{From: now.Truncate(24 * time.Hour), To: now.Truncate(24 * time.Hour).Add(24 * time.Hour)}}
		case protocol.UsageStageOperation:
			request = protocol.UsageStageRequest{Operation: op, Lease: lease, Batch: protocol.SnapshotBatch{Rows: []protocol.SnapshotRow{}}}
		case protocol.UsageCommitOperation:
			request = protocol.UsageCommitRequest{Operation: op, Lease: lease, Manifest: protocol.SnapshotManifest{Batches: []protocol.StageAck{}}}
		}
		raw, _ := json.Marshal(request)
		i := protocol.Identity{Version: 1, TenantID: "public", ActorKind: "producer", Operation: op, RequestID: "22222222-2222-4222-8222-222222222222", Audience: protocol.Audience, IssuedAt: now, ExpiresAt: now.Add(5 * time.Second)}
		body, _ := json.Marshal(protocol.Envelope{Version: 1, Identity: i, Request: raw})
		w := httptest.NewRecorder()
		NewHandler(Dependencies{TenantID: "public", Now: func() time.Time { return now }}).ServeHTTP(w, httptest.NewRequest("POST", "/v1/call", bytes.NewReader(body)))
		if w.Code != 503 {
			t.Fatalf("operation not dispatched: %s %d", op, w.Code)
		}
		i.ActorKind = "user"
		i.UserID = "11111111-1111-4111-8111-111111111111"
		body, _ = json.Marshal(protocol.Envelope{Version: 1, Identity: i, Request: raw})
		w = httptest.NewRecorder()
		NewHandler(Dependencies{TenantID: "public", Now: func() time.Time { return now }}).ServeHTTP(w, httptest.NewRequest("POST", "/v1/call", bytes.NewReader(body)))
		if w.Code != 403 {
			t.Fatal("user entered snapshots", w.Code)
		}
	}
}

type snapshotFake struct {
	now  time.Time
	got  protocol.Identity
	fail bool
}

func (s *snapshotFake) BeginSnapshot(_ context.Context, i protocol.Identity, c protocol.Coverage) (protocol.SnapshotLease, error) {
	s.got = i
	return protocol.SnapshotLease{Status: "waiting", ActivatedAt: s.now, CollectionStart: s.now.Truncate(24 * time.Hour).Add(24 * time.Hour)}, nil
}
func (s *snapshotFake) StageBatch(_ context.Context, i protocol.Identity, _ protocol.SnapshotLease, b protocol.SnapshotBatch) (protocol.StageAck, error) {
	s.got = i
	if s.fail {
		return protocol.StageAck{}, protocol.ErrConflict
	}
	return protocol.StageAck{Index: b.Index, Digest: strings.Repeat("a", 64), RowCount: 1, ByteCount: 123}, nil
}
func (s *snapshotFake) CommitSnapshot(_ context.Context, i protocol.Identity, l protocol.SnapshotLease, m protocol.SnapshotManifest) (protocol.PublishedSnapshot, error) {
	s.got = i
	return protocol.PublishedSnapshot{Revision: l.Revision, Digest: m.Digest, Coverage: *l.Coverage, PublishedAt: s.now, TotalRows: m.TotalRows, TotalBytes: m.TotalBytes}, nil
}
func TestSnapshotDispatchReturnsNamedResponseAndChecksPayload(t *testing.T) {
	now := time.Date(2026, 10, 12, 12, 0, 0, 0, time.UTC)
	store := &snapshotFake{now: now}
	h := NewHandler(Dependencies{TenantID: "public", Snapshots: store, Now: func() time.Time { return now }})
	identity := protocol.Identity{Version: 1, TenantID: "public", ActorKind: "producer", Operation: protocol.UsageBeginOperation, RequestID: "22222222-2222-4222-8222-222222222222", Audience: protocol.Audience, IssuedAt: now, ExpiresAt: now.Add(5 * time.Second)}
	raw := json.RawMessage(`{"operation":"usage.begin","coverage":{"from":"2026-10-12T00:00:00Z","to":"2026-10-13T00:00:00Z"}}`)
	call := func(request json.RawMessage) *httptest.ResponseRecorder {
		body, _ := json.Marshal(protocol.Envelope{Version: 1, Identity: identity, Request: request})
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/call", bytes.NewReader(body)))
		return w
	}
	w := call(raw)
	var response protocol.UsageBeginResponse
	if w.Code != 200 || protocol.DecodeStrict(w.Body.Bytes(), &response) != nil || response.Lease.Status != "waiting" || store.got != identity {
		t.Fatalf("incorrect producer dispatch %d %s", w.Code, w.Body.String())
	}
	for _, bad := range []json.RawMessage{
		bytes.Replace(raw, []byte(`"operation":"usage.begin"`), []byte(`"operation":"usage.commit"`), 1),
		bytes.Replace(raw, []byte(`"from":`), []byte(`"extra":true,"from":`), 1),
		bytes.Replace(raw, []byte(`"from":`), []byte(`"from":null,"from":`), 1),
	} {
		store.got = protocol.Identity{}
		w = call(bad)
		if w.Code != 422 || store.got.TenantID != "" {
			t.Fatal("invalid snapshot reached store", w.Code)
		}
	}
}

func TestUsageSummaryResponseLimitDoesNotTruncateGroups(t *testing.T) {
	groups := make([]protocol.UsageGroup, 1000)
	for i := range groups {
		groups[i] = protocol.UsageGroup{Value: strings.Repeat("😀", 512), Category: "USER"}
	}
	w := httptest.NewRecorder()
	writeJSON(w, 200, protocol.UsageResponse{Operation: protocol.UsageSummaryOperation, Summary: protocol.UsageSummary{GroupBy: "model", Groups: groups}})
	if w.Code != 503 || strings.Contains(w.Body.String(), "groups") || w.Body.Len() > protocol.MaxBytes {
		t.Fatal("large summary was truncated or exposed")
	}
}
