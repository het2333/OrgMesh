// Package historyserver serves one private, stateless Unix-socket endpoint.
package historyserver

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"orgmesh.local/core/internal/history"
	"time"
)

func Serve(ctx context.Context, socketPath string, allowedPeerUID uint32) error {
	listener, cleanup, err := privateListener(socketPath, allowedPeerUID)
	if err != nil {
		return err
	}
	defer cleanup()

	server := &http.Server{Handler: newHandler(), ReadHeaderTimeout: 100 * time.Millisecond, ReadTimeout: 250 * time.Millisecond, WriteTimeout: 500 * time.Millisecond, IdleTimeout: 100 * time.Millisecond, MaxHeaderBytes: 8192, ErrorLog: log.New(io.Discard, "", 0)}
	server.SetKeepAlivesEnabled(false)
	stopped := make(chan struct{})
	shutdownDone := make(chan struct{})
	defer close(stopped)
	go func() {
		defer close(shutdownDone)
		select {
		case <-ctx.Done():
			shutdown, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			server.Shutdown(shutdown)
			server.Close()
		case <-stopped:
		}
	}()
	err = server.Serve(listener)
	if err == http.ErrServerClosed {
		<-shutdownDone
		return nil
	}
	return err
}

func newHandler() http.Handler {
	slots := make(chan struct{}, 32)
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/v1/project-history" || r.URL.RawQuery != "" {
			http.Error(w, "unsupported_request", 404)
			return
		}
		select {
		case slots <- struct{}{}:
			defer func() { <-slots }()
		default:
			http.Error(w, "busy", 503)
			return
		}
		if r.Header.Get("Content-Encoding") != "" || r.Header.Get("Content-Type") != "application/json" {
			http.Error(w, "invalid_request", 400)
			return
		}
		data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, history.MaxBytes))
		if err != nil {
			http.Error(w, "invalid_request", 400)
			return
		}
		req, err := history.DecodeRequest(data)
		if err != nil {
			http.Error(w, "invalid_request", 400)
			return
		}
		response, err := history.Project(req)
		if err != nil {
			http.Error(w, "invalid_request", 400)
			return
		}
		body, err := json.Marshal(response)
		if err != nil || len(body) > history.MaxBytes {
			http.Error(w, "invalid_response", 500)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		w.Write(body)
	})
	return handler
}
