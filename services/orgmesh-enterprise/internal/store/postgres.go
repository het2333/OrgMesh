// SPDX-License-Identifier: MIT
package store

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"orgmesh.local/enterprise/internal/protocol"
)

// Open uses only the explicit enterprise DSN. It never reads Community configuration.
func Open(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	if dsn == "" {
		return nil, protocol.ErrUnavailable
	}
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, protocol.ErrUnavailable
	}
	config.MaxConns = 8
	config.MinConns = 0
	config.ConnConfig.ConnectTimeout = 2 * time.Second
	config.ConnConfig.RuntimeParams["search_path"] = "pg_catalog,orgmesh_enterprise"
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, protocol.ErrUnavailable
	}
	if err = pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, protocol.ErrUnavailable
	}
	return pool, nil
}
