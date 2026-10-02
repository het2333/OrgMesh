package historyserver

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"orgmesh.local/core/internal/history"
)

func TestRequestBoundsAndTrailingJSON(t *testing.T) {
	fixture, err := os.ReadFile("../../testdata/history/statuses.json")
	if err != nil {
		t.Fatal(err)
	}
	var f struct {
		Request json.RawMessage `json:"request"`
	}
	json.Unmarshal(fixture, &f)
	for name, data := range map[string][]byte{
		"trailing":  append(append([]byte{}, f.Request...), []byte(" {}")...),
		"large":     []byte(strings.Repeat(" ", history.MaxBytes+1)),
		"missing":   []byte(`{"version":1}`),
		"duplicate": []byte(`{"version":1,"version":1}`),
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := history.DecodeRequest(data); err == nil {
				t.Fatal("accepted invalid request")
			}
		})
	}
	req, err := history.DecodeRequest(f.Request)
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(req)
	if _, err := history.DecodeRequest(data); err != nil {
		t.Fatal(err)
	}
}
func TestSocketRejectsUnsafePathAndForeignUID(t *testing.T) {
	dir, err := os.MkdirTemp("", "history-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	os.Chmod(dir, 0700)
	path := filepath.Join(dir, "history.sock")
	os.WriteFile(path, []byte("retain"), 0600)
	if err := Serve(context.Background(), path, uint32(os.Getuid())); err == nil {
		t.Fatal("accepted regular file")
	}
	data, _ := os.ReadFile(path)
	if string(data) != "retain" {
		t.Fatal("removed regular file")
	}
	os.Remove(path)
	os.Symlink(dir, filepath.Join(dir, "link"))
	if err := Serve(context.Background(), filepath.Join(dir, "link", "history.sock"), uint32(os.Getuid())); err == nil {
		t.Fatal("accepted symlink parent")
	}
	os.Chmod(dir, 0755)
	if err := Serve(context.Background(), path, uint32(os.Getuid())); err == nil {
		t.Fatal("accepted open directory")
	}
	os.Chmod(dir, 0700)
	requireUnixSocket(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, path, uint32(os.Getuid()+1)) }()
	for i := 0; i < 100; i++ {
		if _, err := os.Lstat(path); err == nil {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", path)
	}}
	client := &http.Client{Transport: transport, Timeout: time.Second}
	_, err = client.Post("http://history/v1/project-history", "application/json", bytes.NewReader([]byte("{}")))
	if err == nil {
		t.Fatal("accepted foreign UID")
	}
	transport.CloseIdleConnections()
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("shutdown timeout")
	}
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatal("socket remains")
	}
}
func TestRealHTTPProjectionAndBounds(t *testing.T) {
	dir, err := os.MkdirTemp("", "history-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	os.Chmod(dir, 0700)
	path := filepath.Join(dir, "history.sock")
	requireUnixSocket(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, path, uint32(os.Getuid())) }()
	for i := 0; i < 100; i++ {
		if _, err := os.Lstat(path); err == nil {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("socket permissions")
	}
	if err := Serve(context.Background(), path, uint32(os.Getuid())); err == nil {
		t.Fatal("replaced active socket")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", path)
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Second}
	fixture, _ := os.ReadFile("../../testdata/history/statuses.json")
	var f struct {
		Request  json.RawMessage
		Response json.RawMessage
	}
	json.Unmarshal(fixture, &f)
	for _, test := range []struct {
		data   []byte
		status int
	}{{f.Request, 200}, {[]byte(strings.Repeat(" ", history.MaxBytes+1)), 400}, {append(append([]byte{}, f.Request...), []byte(" {}")...), 400}} {
		response, err := client.Post("http://history/v1/project-history", "application/json", bytes.NewReader(test.data))
		if err != nil {
			t.Fatal(err)
		}
		body, _ := io.ReadAll(response.Body)
		response.Body.Close()
		if response.StatusCode != test.status {
			t.Fatalf("status %d", response.StatusCode)
		}
		if test.status == 200 {
			var got, want any
			json.Unmarshal(body, &got)
			json.Unmarshal(f.Response, &want)
			if !reflectEqual(got, want) {
				t.Fatal("projection changed")
			}
		}
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}
func reflectEqual(a, b any) bool {
	aa, _ := json.Marshal(a)
	bb, _ := json.Marshal(b)
	return bytes.Equal(aa, bb)
}

func requireUnixSocket(t *testing.T) {
	t.Helper()
	fd, err := syscall.Socket(syscall.AF_UNIX, syscall.SOCK_STREAM, 0)
	if errors.Is(err, syscall.EPERM) {
		t.Skip("Executor forbids AF_UNIX sockets; run IPC tests on Linux outside this sandbox")
	}
	if err != nil {
		t.Fatal(err)
	}
	syscall.Close(fd)
}
func TestHandlerWithoutSocket(t *testing.T) {
	fixture, _ := os.ReadFile("../../testdata/history/statuses.json")
	var f struct{ Request json.RawMessage }
	json.Unmarshal(fixture, &f)
	for _, test := range []struct {
		data         []byte
		method, path string
		status       int
	}{
		{f.Request, "POST", "/v1/project-history", 200},
		{[]byte(strings.Repeat(" ", history.MaxBytes+1)), "POST", "/v1/project-history", 400},
		{append(append([]byte{}, f.Request...), []byte(" {}")...), "POST", "/v1/project-history", 400},
		{f.Request, "GET", "/v1/project-history", 404},
		{f.Request, "POST", "/v1/project-history?owner=other", 404},
	} {
		req := httptest.NewRequest(test.method, test.path, bytes.NewReader(test.data))
		req.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		newHandler().ServeHTTP(recorder, req)
		if recorder.Code != test.status {
			t.Fatalf("status=%d expected=%d", recorder.Code, test.status)
		}
	}
}
