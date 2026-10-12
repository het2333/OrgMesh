//go:build transportintegration && linux

package ipc

import (
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPrivateListener(t *testing.T) {
	dir := t.TempDir()
	os.Chmod(dir, 0700)
	path := filepath.Join(dir, "enterprise.sock")
	l, err := Listen(path, uint32(os.Getuid()))
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("socket mode: %v %v", info, err)
	}
	done := make(chan error, 1)
	go func() {
		c, e := l.Accept()
		if e == nil {
			c.Close()
		}
		done <- e
	}()
	c, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	c.Close()
	select {
	case e := <-done:
		if e != nil {
			t.Fatal(e)
		}
	case <-time.After(time.Second):
		t.Fatal("same-UID connection refused")
	}
}
func TestWrongPeerUIDDenied(t *testing.T) {
	dir := t.TempDir()
	os.Chmod(dir, 0700)
	l, err := Listen(filepath.Join(dir, "enterprise.sock"), uint32(os.Getuid()+1))
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	go l.Accept()
	c, err := net.Dial("unix", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.SetReadDeadline(time.Now().Add(time.Second))
	var b [1]byte
	if _, err = c.Read(b[:]); err == nil {
		t.Fatal("wrong UID read accepted")
	} else if e, ok := err.(net.Error); ok && e.Timeout() {
		t.Fatal("wrong UID was not rejected")
	}
}
