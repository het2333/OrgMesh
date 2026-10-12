// SPDX-License-Identifier: MIT
package branding

import (
	"context"
	"errors"
	"math"
	"reflect"
	"testing"

	"orgmesh.local/enterprise/internal/protocol"
)

func patch(version int64, name, greeting string) protocol.BrandingPatch {
	return protocol.BrandingPatch{ExpectedVersion: version, Name: name, Greeting: greeting, LogoAssetID: "orgmesh-default"}
}
func TestFirstPatchCreatesVersionOne(t *testing.T) {
	view, fields, action, err := planChange(nil, patch(0, "OrgMesh", ""))
	if err != nil || view.Version != 1 || view.Source != "dynamic" || action != "branding.created" || !reflect.DeepEqual(fields, []string{"name", "greeting", "logo_asset_id"}) {
		t.Fatalf("create: %+v %v %s %v", view, fields, action, err)
	}
}
func TestUnchangedBrandDoesNotCreateAudit(t *testing.T) {
	before := protocol.BrandingView{Name: "OrgMesh", LogoAssetID: "orgmesh-default", Version: 3, Source: "dynamic"}
	view, fields, action, err := planChange(&before, patch(3, "OrgMesh", ""))
	if err != nil || view != before || len(fields) != 0 || action != "" {
		t.Fatalf("no-op: %+v %v %s %v", view, fields, action, err)
	}
}
func TestOnlyChangedFieldNamesAreRecorded(t *testing.T) {
	before := protocol.BrandingView{Name: "OrgMesh", LogoAssetID: "orgmesh-default", Version: 3, Source: "dynamic"}
	view, fields, action, err := planChange(&before, patch(3, "Private Brand", "Private greeting"))
	if err != nil || view.Version != 4 || action != "branding.updated" || !reflect.DeepEqual(fields, []string{"name", "greeting"}) {
		t.Fatalf("update: %+v %v %s %v", view, fields, action, err)
	}
}
func TestExpectedVersionAndOverflowConflict(t *testing.T) {
	for _, tc := range []struct {
		before *protocol.BrandingView
		patch  protocol.BrandingPatch
	}{
		{nil, patch(1, "OrgMesh", "")},
		{&protocol.BrandingView{Version: 3}, patch(2, "OrgMesh", "")},
		{&protocol.BrandingView{Version: math.MaxInt64}, patch(math.MaxInt64, "OrgMesh", "")},
	} {
		if _, _, _, err := planChange(tc.before, tc.patch); !errors.Is(err, protocol.ErrConflict) {
			t.Fatalf("wanted conflict: %v", err)
		}
	}
}
func TestDigestIncludesExpectedVersion(t *testing.T) {
	first := patch(1, "OrgMesh", "")
	if requestDigest(first) != "9c70327d72110e4f6e6fba5765568617690b9bd33f9f816a948f4996c9291161" || requestDigest(first) == requestDigest(patch(2, "OrgMesh", "")) || requestDigest(first) == requestDigest(patch(1, "Other", "")) {
		t.Fatal("receipt digest does not bind full patch")
	}
}

func TestStoreRejectsCallerTenantAndInvalidFields(t *testing.T) {
	service := New(nil, "configured", []string{"orgmesh-default"})
	identity := protocol.Identity{TenantID: "configured", ActorKind: "user", UserID: "11111111-1111-4111-8111-111111111111", RequestID: "22222222-2222-4222-8222-222222222222", Operation: protocol.BrandingPatchOperation}
	invalid := patch(0, "", "")
	if _, err := service.Apply(context.Background(), identity, invalid); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatalf("invalid patch reached storage: %v", err)
	}
	identity.TenantID = "other"
	if _, err := service.Apply(context.Background(), identity, patch(0, "OrgMesh", "")); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatalf("caller selected tenant: %v", err)
	}
	if _, err := service.Read(context.Background(), "other"); !errors.Is(err, protocol.ErrInvalid) {
		t.Fatalf("caller read tenant: %v", err)
	}
}
