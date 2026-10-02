//go:build linux

package historyserver

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"
)

var errUnsafeSocket = errors.New("unsafe_socket")

type peerListener struct {
	*net.UnixListener
	allowedUID uint32
	slots      chan struct{}
}
type boundedConn struct {
	net.Conn
	slots chan struct{}
	once  sync.Once
}

func (c *boundedConn) Close() error {
	err := c.Conn.Close()
	c.once.Do(func() { <-c.slots })
	return err
}
func (l *peerListener) Accept() (net.Conn, error) {
	for {
		conn, err := l.AcceptUnix()
		if err != nil {
			return nil, err
		}
		raw, err := conn.SyscallConn()
		if err != nil {
			conn.Close()
			continue
		}
		var cred *syscall.Ucred
		var credErr error
		err = raw.Control(func(fd uintptr) {
			cred, credErr = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
		})
		if err != nil || credErr != nil || cred == nil || cred.Uid != l.allowedUID {
			conn.Close()
			continue
		}
		select {
		case l.slots <- struct{}{}:
			return &boundedConn{Conn: conn, slots: l.slots}, nil
		default:
			conn.Close()
		}
	}
}
func owned(info os.FileInfo) bool {
	s, ok := info.Sys().(*syscall.Stat_t)
	return ok && s.Uid == uint32(os.Geteuid())
}
func privateListener(path string, uid uint32) (*peerListener, func(), error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, nil, errUnsafeSocket
	}
	dir := filepath.Dir(path)
	for parent := dir; ; parent = filepath.Dir(parent) {
		info, err := os.Lstat(parent)
		if err != nil && !(parent == dir && os.IsNotExist(err)) {
			return nil, nil, errUnsafeSocket
		}
		if err == nil && (info.Mode()&os.ModeSymlink != 0 || !info.IsDir()) {
			return nil, nil, errUnsafeSocket
		}
		if parent == filepath.Dir(parent) {
			break
		}
	}
	if err := os.Mkdir(dir, 0700); err != nil && !os.IsExist(err) {
		return nil, nil, errUnsafeSocket
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || !owned(info) || info.Mode().Perm() != 0700 {
		return nil, nil, errUnsafeSocket
	}
	old, err := os.Lstat(path)
	if err == nil {
		if old.Mode()&os.ModeSocket == 0 || !owned(old) {
			return nil, nil, errUnsafeSocket
		}
		conn, dialErr := net.DialTimeout("unix", path, 50*time.Millisecond)
		if dialErr == nil {
			conn.Close()
			return nil, nil, errUnsafeSocket
		}
		if !errors.Is(dialErr, syscall.ECONNREFUSED) {
			return nil, nil, errUnsafeSocket
		}
		now, checkErr := os.Lstat(path)
		if checkErr != nil || !os.SameFile(old, now) {
			return nil, nil, errUnsafeSocket
		}
		if err = os.Remove(path); err != nil {
			return nil, nil, errUnsafeSocket
		}
	} else if !os.IsNotExist(err) {
		return nil, nil, errUnsafeSocket
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, nil, errUnsafeSocket
	}
	if err = os.Chmod(path, 0600); err != nil {
		listener.Close()
		return nil, nil, errUnsafeSocket
	}
	socket, err := os.Lstat(path)
	if err != nil {
		listener.Close()
		return nil, nil, errUnsafeSocket
	}
	listener.SetUnlinkOnClose(false)
	cleanup := func() {
		listener.Close()
		current, e := os.Lstat(path)
		if e == nil && os.SameFile(socket, current) && owned(current) {
			os.Remove(path)
		}
	}
	return &peerListener{UnixListener: listener, allowedUID: uid, slots: make(chan struct{}, 64)}, cleanup, nil
}
