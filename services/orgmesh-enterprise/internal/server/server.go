// SPDX-License-Identifier: MIT
package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"time"

	"orgmesh.local/enterprise/internal/protocol"
)

// Stores own tenant-qualified persistence. No fallback store is installed here.
type BrandingStore interface {
	Apply(context.Context, protocol.Identity, protocol.BrandingPatch) (protocol.BrandingView, error)
	Read(context.Context, string) (protocol.BrandingView, error)
}
type AuditStore interface {
	List(context.Context, string, protocol.AuditQuery) (protocol.AuditPage, error)
}
type UsageStore interface {
	Summary(context.Context, string, protocol.UsageQuery) (protocol.UsageSummary, error)
}
type SnapshotStore interface {
	BeginSnapshot(context.Context, protocol.Identity, protocol.Coverage) (protocol.SnapshotLease, error)
	StageBatch(context.Context, protocol.Identity, protocol.SnapshotLease, protocol.SnapshotBatch) (protocol.StageAck, error)
	CommitSnapshot(context.Context, protocol.Identity, protocol.SnapshotLease, protocol.SnapshotManifest) (protocol.PublishedSnapshot, error)
}
type Dependencies struct {
	Snapshots    SnapshotStore
	TenantID     string
	Branding     BrandingStore
	Audit        AuditStore
	Usage        UsageStore
	LogoAssetIDs []string
	Now          func() time.Time
	Ready        func(context.Context) error
}

var ErrConflict = protocol.ErrConflict
var ErrUnavailable = protocol.ErrUnavailable

func NewHandler(deps Dependencies) http.Handler {
	if deps.Now == nil {
		deps.Now = time.Now
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if deps.TenantID == "" || deps.Branding == nil || (deps.Ready != nil && deps.Ready(ctx) != nil) {
			writeError(w, http.StatusServiceUnavailable, "SERVICE_UNAVAILABLE", "not ready")
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("POST /v1/call", func(w http.ResponseWriter, r *http.Request) { serveCall(w, r, deps) })
	return mux
}
func serveCall(w http.ResponseWriter, r *http.Request, deps Dependencies) {
	data, err := io.ReadAll(io.LimitReader(r.Body, protocol.MaxBytes+1))
	if err != nil {
		writeError(w, http.StatusBadRequest, "BAD_REQUEST", "invalid body")
		return
	}
	if len(data) > protocol.MaxBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "PAYLOAD_TOO_LARGE", "request exceeds limit")
		return
	}
	var envelope protocol.Envelope
	if protocol.DecodeStrict(data, &envelope) != nil || envelope.Version != 1 {
		writeError(w, http.StatusUnprocessableEntity, "VALIDATION_ERROR", "invalid request")
		return
	}
	operation := envelope.Identity.Operation
	if protocol.ValidateIdentity(envelope.Identity, operation, deps.Now(), deps.TenantID) != nil {
		writeError(w, http.StatusForbidden, "INSUFFICIENT_PERMISSIONS", "invalid trusted context")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	var result any
	switch operation {
	case protocol.BrandingReadOperation:
		var request protocol.BrandingReadRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation {
			invalid(w)
			return
		}
		if deps.Branding == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Branding.Read(ctx, deps.TenantID)
		err = storeError
		if err == nil {
			if value.Validate(deps.LogoAssetIDs) != nil {
				unavailable(w)
				return
			}
			result = protocol.BrandingResponse{Operation: operation, Branding: value}
		}
	case protocol.BrandingPatchOperation:
		var request protocol.BrandingPatchRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation || request.Patch.Validate(deps.LogoAssetIDs) != nil {
			invalid(w)
			return
		}
		if deps.Branding == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Branding.Apply(ctx, envelope.Identity, request.Patch)
		err = storeError
		if err == nil {
			if value.Validate(deps.LogoAssetIDs) != nil {
				unavailable(w)
				return
			}
			result = protocol.BrandingResponse{Operation: operation, Branding: value}
		}
	case protocol.AuditListOperation:
		var request protocol.AuditListRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation || request.Query.Validate() != nil {
			invalid(w)
			return
		}
		if deps.Audit == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Audit.List(ctx, deps.TenantID, request.Query)
		err = storeError
		if err == nil {
			if value.Validate() != nil {
				unavailable(w)
				return
			}
			result = protocol.AuditResponse{Operation: operation, Page: value}
		}
	case protocol.UsageBeginOperation:
		var request protocol.UsageBeginRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation || request.Coverage.Validate() != nil {
			invalid(w)
			return
		}
		if deps.Snapshots == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Snapshots.BeginSnapshot(ctx, envelope.Identity, request.Coverage)
		err = storeError
		if err == nil {
			if value.Validate() != nil {
				unavailable(w)
				return
			}
			result = protocol.UsageBeginResponse{Operation: operation, Lease: value}
		}
	case protocol.UsageStageOperation:
		var request protocol.UsageStageRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation {
			invalid(w)
			return
		}
		if deps.Snapshots == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Snapshots.StageBatch(ctx, envelope.Identity, request.Lease, request.Batch)
		err = storeError
		if err == nil {
			if value.Validate() != nil {
				unavailable(w)
				return
			}
			result = protocol.UsageStageResponse{Operation: operation, Ack: value}
		}
	case protocol.UsageCommitOperation:
		var request protocol.UsageCommitRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation {
			invalid(w)
			return
		}
		if deps.Snapshots == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Snapshots.CommitSnapshot(ctx, envelope.Identity, request.Lease, request.Manifest)
		err = storeError
		if err == nil {
			if value.Validate() != nil {
				unavailable(w)
				return
			}
			result = protocol.UsageCommitResponse{Operation: operation, Published: value}
		}
	case protocol.UsageSummaryOperation:
		var request protocol.UsageSummaryRequest
		if protocol.DecodeStrict(envelope.Request, &request) != nil || request.Operation != operation || request.Query.Validate(deps.Now()) != nil {
			invalid(w)
			return
		}
		if deps.Usage == nil {
			unavailable(w)
			return
		}
		value, storeError := deps.Usage.Summary(ctx, deps.TenantID, request.Query)
		err = storeError
		if err == nil {
			if value.Validate() != nil {
				unavailable(w)
				return
			}
			result = protocol.UsageResponse{Operation: operation, Summary: value}
		}
	default:
		invalid(w)
		return
	}
	if errors.Is(err, protocol.ErrInvalid) {
		invalid(w)
		return
	}
	if errors.Is(err, ErrConflict) {
		writeError(w, http.StatusConflict, "CONFLICT", "version or request content conflicts")
		return
	}
	if err != nil || ctx.Err() != nil {
		unavailable(w)
		return
	}
	if operation == protocol.BrandingReadOperation || operation == protocol.AuditListOperation {
		slog.Info("enterprise read completed", "operation", operation)
	}
	writeJSON(w, http.StatusOK, result)
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	data, err := json.Marshal(value)
	if err != nil || len(data) > protocol.MaxBytes {
		slog.Warn("enterprise response refused", "reason", "response_size_or_encoding")
		unavailable(w)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write(data)
}
func writeError(w http.ResponseWriter, status int, code, detail string) {
	slog.Info("enterprise request refused", "error_code", code)
	writeJSON(w, status, protocol.ErrorResponse{ErrorCode: code, Detail: detail})
}
func invalid(w http.ResponseWriter) {
	writeError(w, http.StatusUnprocessableEntity, "VALIDATION_ERROR", "invalid operation payload")
}
func unavailable(w http.ResponseWriter) {
	writeError(w, http.StatusServiceUnavailable, "SERVICE_UNAVAILABLE", "enterprise service unavailable")
}
