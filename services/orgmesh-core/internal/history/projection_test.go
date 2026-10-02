package history

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestProjectGoldenCases(t *testing.T) {
	paths, _ := filepath.Glob("../../testdata/history/*.json")
	if len(paths) != 2 {
		t.Fatal("missing golden cases")
	}
	for _, path := range paths {
		t.Run(filepath.Base(path), func(t *testing.T) {
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var fixture struct {
				Request  json.RawMessage    `json:"request"`
				Response ProjectionResponse `json:"response"`
			}
			if err = json.Unmarshal(data, &fixture); err != nil {
				t.Fatal(err)
			}
			req, err := DecodeRequest(fixture.Request)
			if err != nil {
				t.Fatal(err)
			}
			got, err := Project(req)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, fixture.Response) {
				t.Fatalf("projection differs")
			}
		})
	}
}

func TestStrictRequestValidation(t *testing.T) {
	data, _ := os.ReadFile("../../testdata/history/statuses.json")
	var fixture map[string]json.RawMessage
	json.Unmarshal(data, &fixture)
	var req map[string]any
	json.Unmarshal(fixture["request"], &req)
	for _, test := range []struct {
		key   string
		value any
	}{
		{"version", nil}, {"version", true}, {"version", 2}, {"request_id", "bad"}, {"facts", nil},
		{"query", map[string]any{"limit": true, "offset": 0, "status": nil}},
		{"query", map[string]any{"limit": 101, "offset": 0, "status": nil}},
		{"query", map[string]any{"limit": 1, "offset": 100001, "status": nil}},
	} {
		var changed map[string]any
		json.Unmarshal(fixture["request"], &changed)
		changed[test.key] = test.value
		invalid, _ := json.Marshal(changed)
		if _, err := DecodeRequest(invalid); err == nil {
			t.Fatalf("accepted invalid %s", test.key)
		}
	}
	facts := req["facts"].([]any)
	fact := facts[0].(map[string]any)
	for key := range fact {
		var changed map[string]any
		json.Unmarshal(fixture["request"], &changed)
		delete(changed["facts"].([]any)[0].(map[string]any), key)
		invalid, _ := json.Marshal(changed)
		if _, err := DecodeRequest(invalid); err == nil {
			t.Fatalf("accepted missing %s", key)
		}
	}
	for _, test := range []struct {
		key   string
		value any
	}{
		{"platform_id", "bad"}, {"state", "unknown"}, {"visible_project_id", true},
		{"created_at", ""}, {"created_at", "bad\n"}, {"created_at", strings.Repeat("x", 65)},
	} {
		var changed map[string]any
		json.Unmarshal(fixture["request"], &changed)
		changed["facts"].([]any)[0].(map[string]any)[test.key] = test.value
		invalid, _ := json.Marshal(changed)
		if _, err := DecodeRequest(invalid); err == nil {
			t.Fatalf("accepted invalid fact %s", test.key)
		}
	}
	req["facts"] = append(facts, fact)
	invalid, _ := json.Marshal(req)
	if _, err := DecodeRequest(invalid); err == nil {
		t.Fatal("accepted duplicate platform ID")
	}
}
func FuzzDecodeRequest(f *testing.F) {
	fixture, _ := os.ReadFile("../../testdata/history/statuses.json")
	var input map[string]json.RawMessage
	json.Unmarshal(fixture, &input)
	f.Add([]byte(input["request"]))
	f.Add([]byte(`{"version":1,"version":1}`))
	f.Add([]byte("{} {}"))
	f.Fuzz(func(t *testing.T, data []byte) {
		req, err := DecodeRequest(data)
		if err == nil {
			if _, err := Project(req); err != nil {
				t.Fatal("decoder accepted invalid project request")
			}
		}
	})
}
