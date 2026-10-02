package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"orgmesh.local/core/internal/historyserver"
)

func main() {
	socket := flag.String("socket", "/tmp/orgmesh-history-go/history.sock", "private Unix socket")
	peerUID := flag.Uint64("peer-uid", uint64(os.Geteuid()), "authorized API process UID")
	flag.Parse()
	if *peerUID > uint64(^uint32(0)) {
		log.Fatal("invalid_peer_uid")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if err := historyserver.Serve(ctx, *socket, uint32(*peerUID)); err != nil {
		log.Fatal("history_service_failed")
	}
}
