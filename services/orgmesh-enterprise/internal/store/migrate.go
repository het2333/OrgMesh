// SPDX-License-Identifier: MIT
package store

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

// Migrate applies the explicit service migration list within its own namespace.
func Migrate(ctx context.Context, db *pgxpool.Pool) error {
	if db == nil {
		return protocol.ErrUnavailable
	}
	tx, err := db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return protocol.ErrUnavailable
	}
	defer tx.Rollback(ctx)
	// This service-level lock also protects the first schema creation.
	if _, err = tx.Exec(ctx, `SELECT pg_catalog.pg_advisory_xact_lock(7816429501700101)`); err != nil {
		return protocol.ErrUnavailable
	}
	if _, err = tx.Exec(ctx, `CREATE SCHEMA IF NOT EXISTS orgmesh_enterprise`); err != nil {
		return protocol.ErrUnavailable
	}
	if _, err = tx.Exec(ctx, `CREATE TABLE IF NOT EXISTS orgmesh_enterprise.schema_migrations (version bigint PRIMARY KEY, name text NOT NULL, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp())`); err != nil {
		return protocol.ErrUnavailable
	}
	// Unknown migrations indicate a newer or incompatible service version.
	var unknown bool
	if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM orgmesh_enterprise.schema_migrations WHERE version NOT IN (1,2))`).Scan(&unknown); err != nil {
		return protocol.ErrUnavailable
	}
	if unknown {
		return errors.New("enterprise migration version is unsupported")
	}
	for index, name := range []string{"001_branding.sql", "002_usage.sql"} {
		version := int64(index + 1)
		data, readError := migrationFiles.ReadFile("migrations/" + name)
		if readError != nil {
			return errors.New("enterprise migration file is unavailable")
		}
		digest := sha256.Sum256(data)
		checksum := hex.EncodeToString(digest[:])
		var storedName, storedChecksum string
		err = tx.QueryRow(ctx, `SELECT name,checksum FROM orgmesh_enterprise.schema_migrations WHERE version=$1`, version).Scan(&storedName, &storedChecksum)
		if err == nil {
			if storedName != name || storedChecksum != checksum {
				return fmt.Errorf("enterprise migration %d checksum differs", version)
			}
			continue
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return protocol.ErrUnavailable
		}
		if _, err = tx.Exec(ctx, string(data)); err != nil {
			return protocol.ErrUnavailable
		}
		if _, err = tx.Exec(ctx, `INSERT INTO orgmesh_enterprise.schema_migrations (version,name,checksum) VALUES ($1,$2,$3)`, version, name, checksum); err != nil {
			return protocol.ErrUnavailable
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return protocol.ErrUnavailable
	}
	return nil
}
