package protocol

import (
	"os"
	"strings"
	"testing"
	"time"
)

func validIdentity() Identity {
	now := time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC)
	return Identity{Version: 1, TenantID: "public", ActorKind: "user", UserID: "11111111-1111-4111-8111-111111111111", Operation: BrandingPatchOperation, RequestID: "22222222-2222-4222-8222-222222222222", Audience: "orgmesh-enterprise/v1", IssuedAt: now, ExpiresAt: now.Add(5 * time.Second)}
}
func TestWrongTenantDenied(t *testing.T) {
	i := validIdentity()
	if ValidateIdentity(i, BrandingPatchOperation, i.IssuedAt, "other") == nil {
		t.Fatal("cross-tenant identity accepted")
	}
}
func TestExpiredIdentity(t *testing.T) {
	i := validIdentity()
	if ValidateIdentity(i, BrandingPatchOperation, i.ExpiresAt, "public") == nil {
		t.Fatal("expired identity accepted")
	}
}
func TestIdentityBoundary(t *testing.T) {
	for _, mutate := range []func(*Identity){
		func(i *Identity) { i.Operation = BrandingReadOperation }, func(i *Identity) { i.Audience = "browser" }, func(i *Identity) { i.ActorKind = "anonymous" }, func(i *Identity) { i.ActorKind = "producer" }, func(i *Identity) { i.UserID = "" }, func(i *Identity) { i.RequestID = "bad" }, func(i *Identity) { i.Version = 2 }, func(i *Identity) { i.IssuedAt = i.IssuedAt.Add(time.Second) }, func(i *Identity) { i.ExpiresAt = i.ExpiresAt.Add(time.Nanosecond) },
	} {
		i := validIdentity()
		now := i.IssuedAt
		mutate(&i)
		if ValidateIdentity(i, BrandingPatchOperation, now, "public") == nil {
			t.Fatalf("invalid context accepted: %+v", i)
		}
	}
	i := validIdentity()
	if err := ValidateIdentity(i, BrandingPatchOperation, i.IssuedAt, "public"); err != nil {
		t.Fatal(err)
	}
	i.ActorKind = "anonymous"
	i.UserID = ""
	i.Operation = BrandingReadOperation
	if err := ValidateIdentity(i, BrandingReadOperation, i.IssuedAt, "public"); err != nil {
		t.Fatal(err)
	}
}
func TestStrictJSON(t *testing.T) {
	for _, input := range []string{`{"expected_version":0,"name":"OrgMesh","greeting":"","logo_asset_id":"orgmesh-default","unknown":true}`, `{"expected_version":0,"name":"a","name":"b","greeting":"","logo_asset_id":"orgmesh-default"}`, `{"expected_version":0,"name":"a","greeting":"","logo_asset_id":"orgmesh-default"} {}`, `{"expected_version":0,"name":"a","greeting":"","logo_asset_id":"orgmesh-default","cost":NaN}`} {
		var patch BrandingPatch
		if DecodeStrict([]byte(input), &patch) == nil {
			t.Fatalf("unsafe JSON accepted: %s", input)
		}
	}
	var p BrandingPatch
	if DecodeStrict([]byte(strings.Repeat(" ", MaxBytes+1)), &p) == nil {
		t.Fatal("oversized request accepted")
	}
}
func TestBrandingBounds(t *testing.T) {
	for _, p := range []BrandingPatch{{ExpectedVersion: 0, Name: "", LogoAssetID: "orgmesh-default"}, {ExpectedVersion: -1, Name: "OrgMesh", LogoAssetID: "orgmesh-default"}, {Name: strings.Repeat("界", 51), LogoAssetID: "orgmesh-default"}, {Name: "OrgMesh", Greeting: strings.Repeat("界", 121), LogoAssetID: "orgmesh-default"}, {Name: "OrgMesh", LogoAssetID: "https://evil.test/logo"}, {Name: "<script>x</script>", LogoAssetID: "orgmesh-default"}} {
		if p.Validate([]string{"orgmesh-default"}) == nil {
			t.Fatalf("bad patch accepted: %+v", p)
		}
	}
	if err := (BrandingPatch{Name: strings.Repeat("界", 50), Greeting: strings.Repeat("界", 120), LogoAssetID: "orgmesh-default"}).Validate([]string{"orgmesh-default"}); err != nil {
		t.Fatal(err)
	}
}
func TestQueryBounds(t *testing.T) {
	now := time.Date(2026, 10, 12, 0, 0, 0, 0, time.UTC)
	if (AuditQuery{Start: now.Add(-91 * 24 * time.Hour), End: now, Limit: 50}).Validate() != nil {
	} else {
		t.Fatal("91-day audit range accepted")
	}
	if (AuditQuery{Start: now.Add(-time.Hour), End: now, Limit: 101}).Validate() == nil {
		t.Fatal("101-row audit page accepted")
	}
	if (UsageQuery{Start: now.Add(-91 * 24 * time.Hour), End: now}).Validate(now) == nil {
		t.Fatal("old usage accepted")
	}
	if (UsageQuery{Start: now.Add(-time.Hour), End: now.Add(time.Hour)}).Validate(now) == nil {
		t.Fatal("future usage accepted")
	}
}

func TestRequiredFields(t *testing.T) {
	for _, input := range []string{`{"name":"OrgMesh","greeting":"","logo_asset_id":"orgmesh-default"}`, `{"expected_version":null,"name":"OrgMesh","greeting":"","logo_asset_id":"orgmesh-default"}`, `{"expected_version":0,"name":"OrgMesh","greeting":null,"logo_asset_id":"orgmesh-default"}`} {
		var p BrandingPatch
		if DecodeStrict([]byte(input), &p) == nil {
			t.Fatalf("missing or null field accepted: %s", input)
		}
	}
}

func TestSharedFixtures(t *testing.T) {
	for _, tc := range []struct {
		name    string
		allowed bool
	}{{"legal", true}, {"unauthorized", false}} {
		data, err := os.ReadFile("../../../../contracts/orgmesh-enterprise/fixtures/" + tc.name + ".json")
		if err != nil {
			t.Fatal(err)
		}
		var envelope Envelope
		if err := DecodeStrict(data, &envelope); err != nil {
			t.Fatal(err)
		}
		err = ValidateIdentity(envelope.Identity, envelope.Identity.Operation, time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC), "public")
		if (err == nil) != tc.allowed {
			t.Fatalf("fixture %s: %v", tc.name, err)
		}
	}
	data, err := os.ReadFile("../../../../contracts/orgmesh-enterprise/fixtures/overlimit.json")
	if err != nil {
		t.Fatal(err)
	}
	var envelope Envelope
	if DecodeStrict(data, &envelope) != nil {
		t.Fatal("overlimit envelope malformed")
	}
	var request BrandingPatchRequest
	if DecodeStrict(envelope.Request, &request) != nil {
		t.Fatal("overlimit request malformed")
	}
	if request.Patch.Validate([]string{"orgmesh-default"}) == nil {
		t.Fatal("oversized branding fixture accepted")
	}
}

func TestUsageContractRejectsFloatMoneyAndMissingMetadata(t *testing.T) {
	var summary UsageSummary
	for _, raw := range []string{`{"status":"unavailable"}`, `{"status":"unavailable","estimated_cost":0.1}`} {
		if DecodeStrict([]byte(raw), &summary) == nil {
			t.Fatal("incomplete or float summary accepted")
		}
	}
}

func TestCaseSensitiveJSONFields(t *testing.T) {
	for _, input := range []string{
		`{"expected_version":0,"name":"OrgMesh","NAME":"Override","greeting":"","logo_asset_id":"orgmesh-default"}`,
		`{"expected_version":0,"name":"OrgMesh","Name":"Override","greeting":"","logo_asset_id":"orgmesh-default"}`,
		`{"expected_version":0,"NAME":"OrgMesh","greeting":"","logo_asset_id":"orgmesh-default"}`,
		`{"expected_version":0,"name":"OrgMesh","greeting":"","logo_asset_id":"orgmesh-default","LOGO_ASSET_ID":"orgmesh-default"}`,
	} {
		var patch BrandingPatch
		if err := DecodeStrict([]byte(input), &patch); err == nil {
			t.Fatalf("non-canonical field accepted: %s -> %+v", input, patch)
		}
	}
	var canonical BrandingPatch
	if err := DecodeStrict([]byte(`{"expected_version":0,"name":"OrgMesh","greeting":"","logo_asset_id":"orgmesh-default"}`), &canonical); err != nil {
		t.Fatal(err)
	}
	if canonical.Name != "OrgMesh" || canonical.LogoAssetID != "orgmesh-default" {
		t.Fatal("canonical patch changed")
	}
}

func TestAuditFiltersAreBounded(t *testing.T) {
	query := AuditQuery{Start: time.Now().Add(-time.Hour), End: time.Now(), Limit: 50, Action: "branding.updated", Result: "success"}
	if query.Validate() != nil {
		t.Fatal("approved filters rejected")
	}
	query.Action = "usage.read"
	if query.Validate() == nil {
		t.Fatal("unapproved action accepted")
	}
	query.Action = ""
	query.Result = "failure"
	if query.Validate() == nil {
		t.Fatal("unapproved result accepted")
	}
}

func TestBrandingSourceHasPersistentVersion(t *testing.T) {
	for _, view := range []BrandingView{
		{Name: "OrgMesh", LogoAssetID: "orgmesh-default", Version: 1, Source: "static"},
		{Name: "OrgMesh", LogoAssetID: "orgmesh-default", Version: 0, Source: "dynamic"},
	} {
		if view.Validate([]string{"orgmesh-default"}) == nil {
			t.Fatalf("invalid source/version accepted: %+v", view)
		}
	}
}
func TestAuditFiltersRemainOptionalOnWire(t *testing.T) {
	var query AuditQuery
	if err := DecodeStrict([]byte(`{"start":"2026-10-12T09:00:00Z","end":"2026-10-12T10:00:00Z","limit":50,"cursor":""}`), &query); err != nil {
		t.Fatal(err)
	}
}

func TestAuditPageRejectsMalformedEvents(t *testing.T) {
	event := AuditEvent{EventID: "11111111-1111-4111-8111-111111111111", CreatedAt: time.Now(), UserID: "11111111-1111-4111-8111-111111111111", ActorKind: "user", ResourceID: "branding-config", Action: "branding.created", Result: "success", BeforeVersion: 0, AfterVersion: 1, ChangedFields: []string{"name", "greeting", "logo_asset_id"}, RequestID: "22222222-2222-4222-8222-222222222222"}
	if (AuditPage{Events: []AuditEvent{event}}).Validate() != nil {
		t.Fatal("valid audit page rejected")
	}
	event.ChangedFields = []string{"Private greeting"}
	if (AuditPage{Events: []AuditEvent{event}}).Validate() == nil {
		t.Fatal("audit leaked field content")
	}
	event.ChangedFields = []string{"name", "name"}
	if (AuditPage{Events: []AuditEvent{event}}).Validate() == nil {
		t.Fatal("duplicate changed fields accepted")
	}
	event.ChangedFields = []string{"name"}
	event.AfterVersion = 4
	if (AuditPage{Events: []AuditEvent{event}}).Validate() == nil {
		t.Fatal("invalid version change accepted")
	}
	if (AuditPage{Events: nil}).Validate() == nil {
		t.Fatal("null event array accepted")
	}
}

func TestProducerOnlySnapshotOperations(t *testing.T) {
	for _, op := range []Operation{"usage.begin", "usage.stage", "usage.commit"} {
		i := validIdentity()
		i.Operation = op
		i.ActorKind = "producer"
		i.UserID = ""
		if err := ValidateIdentity(i, op, i.IssuedAt, "public"); err != nil {
			t.Fatalf("producer %s refused: %v", op, err)
		}
		i.ActorKind = "user"
		i.UserID = "11111111-1111-4111-8111-111111111111"
		if ValidateIdentity(i, op, i.IssuedAt, "public") == nil {
			t.Fatal("user entered producer operation")
		}
	}
	i := validIdentity()
	i.ActorKind = "producer"
	i.UserID = ""
	i.Operation = UsageSummaryOperation
	if ValidateIdentity(i, i.Operation, i.IssuedAt, "public") == nil {
		t.Fatal("producer entered summary")
	}
}

func TestUsageTotalsRejectDoubleCountedCache(t *testing.T) {
	v := UsageTotals{InputTokens: "10", OutputTokens: "5", TotalTokens: "21", CacheReadTokens: "4", CacheCreationTokens: "2", CostCents: "0.000000"}
	if v.Validate() == nil {
		t.Fatal("cache tokens added twice")
	}
	v.TotalTokens = "15"
	if v.Validate() != nil {
		t.Fatal("exact source total rejected")
	}
}
func TestUsageDailyQueryBoundaries(t *testing.T) {
	now := time.Date(2026, 10, 12, 12, 0, 0, 0, time.UTC)
	day := now.Truncate(24 * time.Hour)
	if (UsageQuery{Start: day.Add(-89 * 24 * time.Hour), End: day.Add(24 * time.Hour)}).Validate(now) != nil {
		t.Fatal("90 UTC dates rejected")
	}
	for _, q := range []UsageQuery{{Start: day.Add(-90 * 24 * time.Hour), End: day}, {Start: day.Add(time.Second), End: day.Add(24 * time.Hour)}, {Start: day, End: day.Add(48 * time.Hour)}} {
		if q.Validate(now) == nil {
			t.Fatalf("invalid daily range %+v", q)
		}
	}
}

func TestSharedGroupedUsageSummary(t *testing.T) {
	data, err := os.ReadFile("../../../../contracts/orgmesh-enterprise/fixtures/usage-summary.json")
	if err != nil {
		t.Fatal(err)
	}
	var response UsageResponse
	if DecodeStrict(data, &response) != nil || response.Summary.Validate() != nil || len(response.Summary.Groups) != 4 || response.Summary.GroupBy != "day" {
		t.Fatal("grouped summary fixture rejected")
	}
	for _, g := range response.Summary.Groups {
		if g.Totals.TotalTokens != "15" || g.Totals.CostCents != "0.123456" || g.Value != "2026-10-13" {
			t.Fatal("grouped precision changed")
		}
	}
	raw := strings.Replace(string(data), `"status": "ready"`, `"totals": {}, "status": "ready"`, 1)
	if DecodeStrict([]byte(raw), &response) == nil {
		t.Fatal("mixed grand total accepted")
	}
}
