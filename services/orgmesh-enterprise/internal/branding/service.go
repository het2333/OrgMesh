// SPDX-License-Identifier: MIT
package branding

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"slices"

	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
)

// Service is bound to one configured organization. The caller cannot select another.
type Service struct {
	db      *pgxpool.Pool
	tenant  string
	logoIDs []string
}

func New(db *pgxpool.Pool, tenant string, logoIDs []string) *Service {
	return &Service{db: db, tenant: tenant, logoIDs: slices.Clone(logoIDs)}
}
func (service *Service) Apply(ctx context.Context, identity protocol.Identity, patch protocol.BrandingPatch) (protocol.BrandingView, error) {
	if service.tenant == "" || identity.TenantID != service.tenant || identity.ActorKind != "user" || identity.Operation != protocol.BrandingPatchOperation || !protocol.ValidUUID(identity.UserID) || !protocol.ValidUUID(identity.RequestID) || patch.Validate(service.logoIDs) != nil {
		return protocol.BrandingView{}, protocol.ErrInvalid
	}
	if service.db == nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	return apply(ctx, service.db, identity, patch)
}
func (service *Service) Read(ctx context.Context, tenant string) (protocol.BrandingView, error) {
	if service.tenant == "" || tenant != service.tenant {
		return protocol.BrandingView{}, protocol.ErrInvalid
	}
	if service.db == nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	return read(ctx, service.db, tenant)
}

// planChange records field names only. An absent row is always a creation.
func planChange(before *protocol.BrandingView, patch protocol.BrandingPatch) (protocol.BrandingView, []string, string, error) {
	version := int64(0)
	if before != nil {
		version = before.Version
	}
	if patch.ExpectedVersion != version {
		return protocol.BrandingView{}, nil, "", protocol.ErrConflict
	}
	fields := make([]string, 0, 3)
	if before == nil || before.Name != patch.Name {
		fields = append(fields, "name")
	}
	if before == nil || before.Greeting != patch.Greeting {
		fields = append(fields, "greeting")
	}
	if before == nil || before.LogoAssetID != patch.LogoAssetID {
		fields = append(fields, "logo_asset_id")
	}
	if len(fields) == 0 {
		return *before, fields, "", nil
	}
	if version == math.MaxInt64 {
		return protocol.BrandingView{}, nil, "", protocol.ErrConflict
	}
	action := "branding.updated"
	if before == nil {
		action = "branding.created"
	}
	return protocol.BrandingView{Name: patch.Name, Greeting: patch.Greeting, LogoAssetID: patch.LogoAssetID, Version: version + 1, Source: "dynamic"}, fields, action, nil
}
func requestDigest(patch protocol.BrandingPatch) string {
	data, _ := json.Marshal(patch)
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}
