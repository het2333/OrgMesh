//go:build linux

package ipc

import (
	"net"
	"testing"
)

func TestConnectionLimitReleasesSlots(t *testing.T) {
	listener := &privateListener{slots: make(chan struct{}, 32)}
	var accepted []net.Conn
	for i := 0; i < 32; i++ {
		server, client := net.Pipe()
		defer client.Close()
		connection, ok := listener.reserveConnection(server)
		if !ok {
			t.Fatalf("connection %d refused", i)
		}
		accepted = append(accepted, connection)
		defer connection.Close()
	}
	server, client := net.Pipe()
	defer client.Close()
	if _, ok := listener.reserveConnection(server); ok {
		t.Fatal("33rd connection accepted")
	}
	var data [1]byte
	if _, err := client.Read(data[:]); err == nil {
		t.Fatal("excess connection not closed")
	}
	accepted[0].Close()
	accepted[0].Close()
	server, nextClient := net.Pipe()
	defer nextClient.Close()
	next, ok := listener.reserveConnection(server)
	if !ok {
		t.Fatal("closed connection did not release capacity")
	}
	next.Close()
}
