// SPDX-License-Identifier: MIT
package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const MaxBytes = 1 << 20
const Audience = "orgmesh-enterprise/v1"

var ErrConflict = errors.New("request conflicts with stored version or receipt")
var ErrUnavailable = errors.New("enterprise store is unavailable")
var ErrInvalid = errors.New("invalid enterprise value")
var ErrNotFound = errors.New("branding is not configured")

type Operation string

const (
	BrandingReadOperation  Operation = "branding.read"
	BrandingPatchOperation Operation = "branding.patch"
	AuditListOperation     Operation = "audit.list"
	UsageSummaryOperation  Operation = "usage.summary"
	UsageBeginOperation    Operation = "usage.begin"
	UsageStageOperation    Operation = "usage.stage"
	UsageCommitOperation   Operation = "usage.commit"
)

type Identity struct {
	Version   int       `json:"version"`
	TenantID  string    `json:"tenant_id"`
	ActorKind string    `json:"actor_kind"`
	UserID    string    `json:"user_id"`
	Operation Operation `json:"operation"`
	RequestID string    `json:"request_id"`
	Audience  string    `json:"audience"`
	IssuedAt  time.Time `json:"issued_at"`
	ExpiresAt time.Time `json:"expires_at"`
}

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

func ValidUUID(value string) bool { return uuidPattern.MatchString(value) }

func ValidateIdentity(identity Identity, operation Operation, now time.Time, tenant string) error {
	if identity.Version != 1 || tenant == "" || identity.TenantID != tenant || identity.Audience != Audience || identity.Operation != operation || !uuidPattern.MatchString(identity.RequestID) {
		return errors.New("invalid trusted context")
	}
	lifetime := identity.ExpiresAt.Sub(identity.IssuedAt)
	if identity.IssuedAt.IsZero() || identity.IssuedAt.After(now) || !identity.ExpiresAt.After(now) || lifetime <= 0 || lifetime > 5*time.Second {
		return errors.New("expired trusted context")
	}
	switch operation {
	case UsageBeginOperation, UsageStageOperation, UsageCommitOperation:
		if identity.ActorKind != "producer" || identity.UserID != "" {
			return errors.New("actor cannot perform operation")
		}
		return nil
	case BrandingReadOperation, BrandingPatchOperation, AuditListOperation, UsageSummaryOperation:
	default:
		return errors.New("unknown operation")
	}
	if identity.ActorKind == "anonymous" && operation == BrandingReadOperation && identity.UserID == "" {
		return nil
	}
	if identity.ActorKind != "user" || !uuidPattern.MatchString(identity.UserID) {
		return errors.New("actor cannot perform operation")
	}
	return nil
}

type Envelope struct {
	Version  int             `json:"version"`
	Identity Identity        `json:"identity"`
	Request  json.RawMessage `json:"request"`
}
type BrandingReadRequest struct {
	Operation Operation `json:"operation"`
}
type BrandingPatchRequest struct {
	Operation Operation     `json:"operation"`
	Patch     BrandingPatch `json:"patch"`
}
type AuditListRequest struct {
	Operation Operation  `json:"operation"`
	Query     AuditQuery `json:"query"`
}
type UsageSummaryRequest struct {
	Operation Operation  `json:"operation"`
	Query     UsageQuery `json:"query"`
}
type BrandingPatch struct {
	ExpectedVersion int64  `json:"expected_version"`
	Name            string `json:"name"`
	Greeting        string `json:"greeting"`
	LogoAssetID     string `json:"logo_asset_id"`
}
type BrandingView struct {
	Name        string `json:"name"`
	Greeting    string `json:"greeting"`
	LogoAssetID string `json:"logo_asset_id"`
	Version     int64  `json:"version"`
	Source      string `json:"source"`
}
type AuditQuery struct {
	Start  time.Time `json:"start"`
	End    time.Time `json:"end"`
	Limit  int       `json:"limit"`
	Cursor string    `json:"cursor"`
	Action string    `json:"action,omitempty"`
	Result string    `json:"result,omitempty"`
}
type AuditEvent struct {
	EventID       string    `json:"event_id"`
	CreatedAt     time.Time `json:"created_at"`
	UserID        string    `json:"user_id"`
	ActorKind     string    `json:"actor_kind"`
	ResourceID    string    `json:"resource_id"`
	Action        string    `json:"action"`
	Result        string    `json:"result"`
	BeforeVersion int64     `json:"before_version"`
	AfterVersion  int64     `json:"after_version"`
	ChangedFields []string  `json:"changed_fields"`
	RequestID     string    `json:"request_id"`
}
type AuditPage struct {
	Events     []AuditEvent `json:"events"`
	NextCursor *string      `json:"next_cursor"`
}
type UsageQuery struct {
	GroupBy string    `json:"group_by,omitempty"`
	Start   time.Time `json:"start"`
	End     time.Time `json:"end"`
}

type BrandingResponse struct {
	Operation Operation    `json:"operation"`
	Branding  BrandingView `json:"branding"`
}
type AuditResponse struct {
	Operation Operation `json:"operation"`
	Page      AuditPage `json:"page"`
}
type UsageResponse struct {
	Operation Operation    `json:"operation"`
	Summary   UsageSummary `json:"summary"`
}
type ErrorResponse struct {
	ErrorCode string `json:"error_code"`
	Detail    string `json:"detail"`
}

func validText(value string, min, max int) bool {
	length := utf8.RuneCountInString(value)
	return utf8.ValidString(value) && length >= min && length <= max && !strings.ContainsAny(value, "<>") && !strings.ContainsFunc(value, func(r rune) bool { return unicode.IsControl(r) && r != '\n' && r != '\t' })
}
func (patch BrandingPatch) Validate(logoIDs []string) error {
	if patch.ExpectedVersion < 0 || !validText(patch.Name, 1, 50) || !validText(patch.Greeting, 0, 120) || !slices.Contains(logoIDs, patch.LogoAssetID) {
		return errors.New("invalid branding fields")
	}
	return nil
}
func (view BrandingView) Validate(logoIDs []string) error {
	if view.Version < 0 || (view.Source != "static" && view.Source != "dynamic") || (view.Source == "static" && view.Version != 0) || (view.Source == "dynamic" && view.Version == 0) {
		return errors.New("invalid branding response")
	}
	return (BrandingPatch{Name: view.Name, Greeting: view.Greeting, LogoAssetID: view.LogoAssetID}).Validate(logoIDs)
}
func (query AuditQuery) Validate() error {
	if query.Start.IsZero() || query.End.IsZero() || !query.End.After(query.Start) || query.End.Sub(query.Start) > 90*24*time.Hour || query.Limit < 1 || query.Limit > 100 || len(query.Cursor) > 512 || (query.Action != "" && query.Action != "branding.created" && query.Action != "branding.updated") || (query.Result != "" && query.Result != "success") {
		return errors.New("invalid audit range")
	}
	return nil
}
func (query UsageQuery) Validate(now time.Time) error {
	today := now.UTC().Truncate(24 * time.Hour)
	if (query.GroupBy != "" && query.GroupBy != "day" && query.GroupBy != "model" && query.GroupBy != "flow") || (Coverage{From: query.Start, To: query.End}).Validate() != nil || query.Start.Before(today.Add(-89*24*time.Hour)) || query.End.After(today.Add(24*time.Hour)) {
		return ErrInvalid
	}
	return nil
}

// DecodeStrict also rejects duplicate keys before typed decoding.
func DecodeStrict(data []byte, target any) error {
	if len(data) > MaxBytes || !utf8.Valid(data) {
		return errors.New("invalid JSON size or encoding")
	}
	check := json.NewDecoder(bytes.NewReader(data))
	check.UseNumber()
	if err := checkJSON(check, 0); err != nil {
		return err
	}
	if _, err := check.Token(); err != io.EOF {
		return errors.New("trailing JSON")
	}
	shapeDecoder := json.NewDecoder(bytes.NewReader(data))
	shapeDecoder.UseNumber()
	var shape any
	if err := shapeDecoder.Decode(&shape); err != nil {
		return err
	}
	if err := validateShape(shape, reflect.TypeOf(target)); err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	return nil
}
func checkJSON(decoder *json.Decoder, depth int) error {
	if depth > 64 {
		return errors.New("JSON depth exceeded")
	}
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delimiter {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			key, err := decoder.Token()
			if err != nil {
				return err
			}
			name, ok := key.(string)
			if !ok || seen[name] {
				return errors.New("duplicate JSON key")
			}
			seen[name] = true
			if err := checkJSON(decoder, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for decoder.More() {
			if err := checkJSON(decoder, depth+1); err != nil {
				return err
			}
		}
	default:
		return fmt.Errorf("unexpected JSON delimiter %q", delimiter)
	}
	_, err = decoder.Token()
	return err
}

func validateShape(value any, kind reflect.Type) error {
	if kind == nil {
		return errors.New("missing JSON target")
	}
	if kind.Kind() == reflect.Pointer {
		if value == nil {
			return nil
		}
		return validateShape(value, kind.Elem())
	}
	if kind == reflect.TypeOf(json.RawMessage{}) {
		return nil
	}
	if value == nil {
		return errors.New("null JSON field")
	}
	if kind == reflect.TypeOf(time.Time{}) {
		if _, ok := value.(string); !ok {
			return errors.New("timestamp must be a string")
		}
		return nil
	}
	switch kind.Kind() {
	case reflect.Struct:
		object, ok := value.(map[string]any)
		if !ok {
			return errors.New("expected JSON object")
		}
		allowedKeys := make(map[string]bool, kind.NumField())
		for index := 0; index < kind.NumField(); index++ {
			name := strings.Split(kind.Field(index).Tag.Get("json"), ",")[0]
			if name != "" && name != "-" {
				allowedKeys[name] = true
			}
		}
		for name := range object {
			if !allowedKeys[name] {
				return fmt.Errorf("unknown field %s", name)
			}
		}
		for index := 0; index < kind.NumField(); index++ {
			field := kind.Field(index)
			name := strings.Split(field.Tag.Get("json"), ",")[0]
			if name == "" || name == "-" {
				continue
			}
			entry, present := object[name]
			if !present {
				if slices.Contains(strings.Split(field.Tag.Get("json"), ",")[1:], "omitempty") {
					continue
				}
				return fmt.Errorf("missing field %s", name)
			}
			if err := validateShape(entry, field.Type); err != nil {
				return fmt.Errorf("%s: %w", name, err)
			}
		}
	case reflect.Slice, reflect.Array:
		values, ok := value.([]any)
		if !ok {
			return errors.New("expected JSON array")
		}
		for _, entry := range values {
			if err := validateShape(entry, kind.Elem()); err != nil {
				return err
			}
		}
	case reflect.String:
		if _, ok := value.(string); !ok {
			return errors.New("expected JSON string")
		}
	case reflect.Bool:
		if _, ok := value.(bool); !ok {
			return errors.New("expected JSON boolean")
		}
	case reflect.Int, reflect.Int64, reflect.Float64:
		if _, ok := value.(json.Number); !ok {
			return errors.New("expected JSON number")
		}
	}
	return nil
}

func (page AuditPage) Validate() error {
	if page.Events == nil || len(page.Events) > 100 || (page.NextCursor != nil && len(*page.NextCursor) > 512) {
		return ErrInvalid
	}
	for _, event := range page.Events {
		if !ValidUUID(event.EventID) || !ValidUUID(event.UserID) || !ValidUUID(event.RequestID) || event.CreatedAt.IsZero() || event.ActorKind != "user" || event.ResourceID != "branding-config" || event.Result != "success" || event.BeforeVersion < 0 || event.AfterVersion < 1 || event.AfterVersion-1 != event.BeforeVersion || len(event.ChangedFields) < 1 || len(event.ChangedFields) > 3 {
			return ErrInvalid
		}
		if (event.Action != "branding.created" && event.Action != "branding.updated") || (event.Action == "branding.created" && event.BeforeVersion != 0) || (event.Action == "branding.updated" && event.BeforeVersion == 0) {
			return ErrInvalid
		}
		seen := map[string]bool{}
		for _, field := range event.ChangedFields {
			if seen[field] || (field != "name" && field != "greeting" && field != "logo_asset_id") {
				return ErrInvalid
			}
			seen[field] = true
		}
	}
	return nil
}
