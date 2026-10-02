// Package history maps one already-authorized page. It has no I/O or credentials.
package history

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"unicode"
	"unicode/utf8"
)

const MaxBytes = 256 * 1024
const MaxRecords = 100

var ErrContract = errors.New("invalid_contract")
var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type Query struct {
	Limit  int     `json:"limit"`
	Offset int     `json:"offset"`
	Status *string `json:"status"`
}
type Fact struct {
	PlatformID          string  `json:"platform_id"`
	EngineTaskID        *string `json:"engine_task_id"`
	DeckID              *string `json:"deck_id"`
	State               string  `json:"state"`
	VisibleProjectID    *int64  `json:"visible_project_id"`
	VisibleSourceChatID *string `json:"visible_source_chat_id"`
	CreatedAt           string  `json:"created_at"`
	UpdatedAt           string  `json:"updated_at"`
}
type Row struct {
	PlatformTaskID string  `json:"platform_task_id"`
	TaskID         *string `json:"task_id"`
	PresentationID *string `json:"presentation_id"`
	Status         string  `json:"status"`
	ProjectID      *int64  `json:"project_id"`
	SourceChatID   *string `json:"source_chat_id"`
	CreatedAt      string  `json:"created_at"`
	UpdatedAt      string  `json:"updated_at"`
}
type ProjectionRequest struct {
	Version   int    `json:"version"`
	RequestID string `json:"request_id"`
	Query     Query  `json:"query"`
	Facts     []Fact `json:"facts"`
}
type ProjectionResponse struct {
	Version   int    `json:"version"`
	RequestID string `json:"request_id"`
	Rows      []Row  `json:"rows"`
}

func validStatus(s string) bool {
	return s == "submitting" || s == "pending" || s == "completed" || s == "error"
}
func validTime(s string) bool {
	if !utf8.ValidString(s) || utf8.RuneCountInString(s) == 0 || utf8.RuneCountInString(s) > 64 {
		return false
	}
	for _, r := range s {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}
func validUUID(s *string) bool { return s == nil || uuidPattern.MatchString(*s) }

func (req ProjectionRequest) Validate() error {
	if req.Version != 1 || !uuidPattern.MatchString(req.RequestID) || req.Query.Limit < 1 || req.Query.Limit > 100 || req.Query.Offset < 0 || req.Query.Offset > 100000 || (req.Query.Status != nil && !validStatus(*req.Query.Status)) || req.Facts == nil || len(req.Facts) > MaxRecords || len(req.Facts) > req.Query.Limit {
		return ErrContract
	}
	seen := make(map[string]bool, len(req.Facts))
	for _, f := range req.Facts {
		if !uuidPattern.MatchString(f.PlatformID) || seen[f.PlatformID] || !validUUID(f.EngineTaskID) || !validUUID(f.DeckID) || !validUUID(f.VisibleSourceChatID) || !validStatus(f.State) || !validTime(f.CreatedAt) || !validTime(f.UpdatedAt) || (req.Query.Status != nil && f.State != *req.Query.Status) {
			return ErrContract
		}
		seen[f.PlatformID] = true
	}
	return nil
}

// parseValue rejects duplicate keys and excessive nesting before typed decoding.
func parseValue(d *json.Decoder, depth int) (any, error) {
	if depth > 8 {
		return nil, ErrContract
	}
	tok, err := d.Token()
	if err != nil {
		return nil, ErrContract
	}
	delim, ok := tok.(json.Delim)
	if !ok {
		return tok, nil
	}
	switch delim {
	case '{':
		obj := map[string]any{}
		for d.More() {
			key, err := d.Token()
			if err != nil {
				return nil, ErrContract
			}
			s, ok := key.(string)
			if !ok {
				return nil, ErrContract
			}
			if _, exists := obj[s]; exists {
				return nil, ErrContract
			}
			value, err := parseValue(d, depth+1)
			if err != nil {
				return nil, err
			}
			obj[s] = value
		}
		end, err := d.Token()
		if err != nil || end != json.Delim('}') {
			return nil, ErrContract
		}
		return obj, nil
	case '[':
		arr := make([]any, 0)
		for d.More() {
			if len(arr) >= MaxRecords {
				return nil, ErrContract
			}
			value, err := parseValue(d, depth+1)
			if err != nil {
				return nil, err
			}
			arr = append(arr, value)
		}
		end, err := d.Token()
		if err != nil || end != json.Delim(']') {
			return nil, ErrContract
		}
		return arr, nil
	default:
		return nil, ErrContract
	}
}
func exactObject(value any, required []string, nullable map[string]bool) (map[string]any, error) {
	obj, ok := value.(map[string]any)
	if !ok || len(obj) != len(required) {
		return nil, ErrContract
	}
	for _, key := range required {
		v, exists := obj[key]
		if !exists || (v == nil && !nullable[key]) {
			return nil, ErrContract
		}
	}
	return obj, nil
}

func DecodeRequest(data []byte) (ProjectionRequest, error) {
	var req ProjectionRequest
	if len(data) > MaxBytes || !utf8.Valid(data) {
		return req, ErrContract
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	value, err := parseValue(d, 0)
	if err != nil {
		return req, ErrContract
	}
	if _, err = d.Token(); err != io.EOF {
		return req, ErrContract
	}
	env, err := exactObject(value, []string{"version", "request_id", "query", "facts"}, nil)
	if err != nil {
		return req, err
	}
	if _, err = exactObject(env["query"], []string{"limit", "offset", "status"}, map[string]bool{"status": true}); err != nil {
		return req, err
	}
	facts, ok := env["facts"].([]any)
	if !ok {
		return req, ErrContract
	}
	keys := []string{"platform_id", "engine_task_id", "deck_id", "state", "visible_project_id", "visible_source_chat_id", "created_at", "updated_at"}
	nullable := map[string]bool{"engine_task_id": true, "deck_id": true, "visible_project_id": true, "visible_source_chat_id": true}
	for _, fact := range facts {
		if _, err = exactObject(fact, keys, nullable); err != nil {
			return req, err
		}
	}
	typed := json.NewDecoder(bytes.NewReader(data))
	typed.DisallowUnknownFields()
	if err = typed.Decode(&req); err != nil {
		return req, ErrContract
	}
	return req, req.Validate()
}
