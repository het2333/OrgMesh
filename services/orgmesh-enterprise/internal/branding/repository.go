// SPDX-License-Identifier: MIT
package branding

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
)

const configColumns = "name, greeting, logo_asset_id, version"

func read(ctx context.Context, db *pgxpool.Pool, tenant string) (protocol.BrandingView, error) {
	var view protocol.BrandingView
	err := db.QueryRow(ctx, `SELECT `+configColumns+` FROM orgmesh_enterprise.branding_configs WHERE tenant_id=$1`, tenant).Scan(&view.Name, &view.Greeting, &view.LogoAssetID, &view.Version)
	if errors.Is(err, pgx.ErrNoRows) {
		return protocol.BrandingView{}, protocol.ErrNotFound
	}
	if err != nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	view.Source = "dynamic"
	return view, nil
}
func apply(ctx context.Context, db *pgxpool.Pool, identity protocol.Identity, patch protocol.BrandingPatch) (protocol.BrandingView, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	defer tx.Rollback(ctx)
	// A row lock cannot serialize absent rows. The tenant lock also orders receipt retries.
	lockDigest := sha256.Sum256([]byte("orgmesh_enterprise/branding/" + identity.TenantID))
	if _, err = tx.Exec(ctx, `SELECT pg_catalog.pg_advisory_xact_lock($1)`, int64(binary.BigEndian.Uint64(lockDigest[:8]))); err != nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	digest := requestDigest(patch)
	var storedDigest string
	var response []byte
	err = tx.QueryRow(ctx, `SELECT request_digest, response FROM orgmesh_enterprise.branding_receipts WHERE tenant_id=$1 AND user_id=$2 AND request_id=$3`, identity.TenantID, identity.UserID, identity.RequestID).Scan(&storedDigest, &response)
	if err == nil {
		if storedDigest != digest {
			return protocol.BrandingView{}, protocol.ErrConflict
		}
		var original protocol.BrandingView
		if protocol.DecodeStrict(response, &original) != nil {
			return protocol.BrandingView{}, protocol.ErrUnavailable
		}
		return original, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	var current protocol.BrandingView
	err = tx.QueryRow(ctx, `SELECT `+configColumns+` FROM orgmesh_enterprise.branding_configs WHERE tenant_id=$1 FOR UPDATE`, identity.TenantID).Scan(&current.Name, &current.Greeting, &current.LogoAssetID, &current.Version)
	var before *protocol.BrandingView
	if err == nil {
		current.Source = "dynamic"
		before = &current
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	view, fields, action, err := planChange(before, patch)
	if err != nil {
		return protocol.BrandingView{}, err
	}
	if action != "" {
		if before == nil {
			_, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.branding_configs (tenant_id,name,greeting,logo_asset_id,version) VALUES ($1,$2,$3,$4,$5)`, identity.TenantID, view.Name, view.Greeting, view.LogoAssetID, view.Version)
		} else {
			var result int64
			err = tx.QueryRow(ctx, `UPDATE orgmesh_enterprise.branding_configs SET name=$2,greeting=$3,logo_asset_id=$4,version=$5,updated_at=pg_catalog.clock_timestamp() WHERE tenant_id=$1 AND version=$6 RETURNING version`, identity.TenantID, view.Name, view.Greeting, view.LogoAssetID, view.Version, patch.ExpectedVersion).Scan(&result)
			if errors.Is(err, pgx.ErrNoRows) {
				return protocol.BrandingView{}, protocol.ErrConflict
			}
		}
		if err != nil {
			return protocol.BrandingView{}, protocol.ErrUnavailable
		}
		eventID, eventError := newEventID()
		if eventError != nil {
			return protocol.BrandingView{}, protocol.ErrUnavailable
		}
		_, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.audit_events (tenant_id,event_id,user_id,action,result,before_version,after_version,changed_fields,request_id) VALUES ($1,$2,$3,$4,'success',$5,$6,$7,$8)`, identity.TenantID, eventID, identity.UserID, action, patch.ExpectedVersion, view.Version, fields, identity.RequestID)
		if err != nil {
			return protocol.BrandingView{}, protocol.ErrUnavailable
		}
	}
	response, err = json.Marshal(view)
	if err != nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	_, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.branding_receipts (tenant_id,user_id,request_id,request_digest,response) VALUES ($1,$2,$3,$4,$5::jsonb)`, identity.TenantID, identity.UserID, identity.RequestID, digest, string(response))
	if err != nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	if err = tx.Commit(ctx); err != nil {
		return protocol.BrandingView{}, protocol.ErrUnavailable
	}
	return view, nil
}
func newEventID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", err
	}
	value[6] = (value[6] & 15) | 64
	value[8] = (value[8] & 63) | 128
	return fmt.Sprintf("%x-%x-%x-%x-%x", value[:4], value[4:6], value[6:8], value[8:10], value[10:]), nil
}
