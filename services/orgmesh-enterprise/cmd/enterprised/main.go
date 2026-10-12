// SPDX-License-Identifier: MIT
package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"orgmesh.local/enterprise/internal/audit"
	"orgmesh.local/enterprise/internal/branding"
	"orgmesh.local/enterprise/internal/ipc"
	"orgmesh.local/enterprise/internal/server"
	"orgmesh.local/enterprise/internal/store"
	"orgmesh.local/enterprise/internal/usage"
)

func main() {
	socket := flag.String("socket", "/run/orgmesh-enterprise/enterprise.sock", "private Unix socket; directory must already have mode 0700")
	flag.Parse()
	if strings.EqualFold(os.Getenv("MULTI_TENANT"), "true") {
		log.Fatal("enterprise phase one requires a single organization")
	}
	tenant := os.Getenv("ORGMESH_ENTERPRISE_TENANT_ID")
	if tenant == "" {
		tenant = os.Getenv("POSTGRES_DEFAULT_SCHEMA")
	}
	if tenant == "" {
		tenant = "public"
	}
	startup, cancelStartup := context.WithTimeout(context.Background(), 10*time.Second)
	db, err := store.Open(startup, os.Getenv("ORGMESH_ENTERPRISE_DATABASE_URL"))
	if err != nil {
		cancelStartup()
		log.Fatal("enterprise database is unavailable")
	}
	defer db.Close()
	if err = store.Migrate(startup, db); err != nil {
		cancelStartup()
		log.Fatal("enterprise database migration failed")
	}
	cancelStartup()
	listener, err := ipc.Listen(*socket, uint32(os.Getuid()))
	if err != nil {
		log.Fatal(err)
	}
	defer listener.Close()
	// These stores use only the enterprise schema. Usage is opt-in.
	deps := server.Dependencies{TenantID: tenant, Branding: branding.New(db, tenant, []string{"orgmesh-default"}), Audit: audit.New(db, tenant), Ready: db.Ping, LogoAssetIDs: []string{"orgmesh-default"}}
	if strings.EqualFold(os.Getenv("ORGMESH_ENTERPRISE_USAGE_ENABLED"), "true") {
		receiver := usage.New(db, tenant, nil)
		deps.Usage = receiver
		deps.Snapshots = receiver
	}
	application := &http.Server{Handler: server.NewHandler(deps), ReadHeaderTimeout: 2 * time.Second, ReadTimeout: 2 * time.Second, WriteTimeout: 2 * time.Second, IdleTimeout: 5 * time.Second, MaxHeaderBytes: 16 << 10}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		application.Shutdown(shutdown)
	}()
	if err := application.Serve(listener); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
