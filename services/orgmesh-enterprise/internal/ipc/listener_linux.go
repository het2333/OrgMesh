//go:build linux

// SPDX-License-Identifier: MIT
package ipc

import (
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
)

const MaxConnections = 32

type privateListener struct {
	listener   *net.UnixListener
	allowedUID uint32
	slots      chan struct{}
}
type privateConnection struct {
	net.Conn
	once    sync.Once
	release func()
}

func (connection *privateConnection) Close() error {
	err := connection.Conn.Close()
	connection.once.Do(connection.release)
	return err
}

// All processes with allowedUID must share the same trust boundary.
func Listen(path string, allowedUID uint32) (net.Listener, error) {
	if err := ValidatePlatform(runtime.GOOS); err != nil {
		return nil, err
	}
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, errors.New("socket path must be clean and absolute")
	}
	directory := filepath.Dir(path)
	for current := directory; ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil {
			return nil, err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("socket parent must be a real directory")
		}
		if current == directory {
			stat, ok := info.Sys().(*syscall.Stat_t)
			if !ok || stat.Uid != uint32(os.Getuid()) || info.Mode().Perm() != 0700 {
				return nil, errors.New("socket directory requires current owner and mode 0700")
			}
		}
		if current == "/" {
			break
		}
	}
	if _, err := os.Lstat(path); err == nil {
		return nil, errors.New("socket path already exists; inspect and remove it before startup")
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, err
	}
	if err = os.Chmod(path, 0600); err != nil {
		listener.Close()
		return nil, err
	}
	return &privateListener{listener: listener, allowedUID: allowedUID, slots: make(chan struct{}, MaxConnections)}, nil
}
func (listener *privateListener) Accept() (net.Conn, error) {
	for {
		connection, err := listener.listener.AcceptUnix()
		if err != nil {
			return nil, err
		}
		uid, err := peerUID(connection)
		if err != nil || uid != listener.allowedUID {
			connection.Close()
			continue
		}
		if reserved, ok := listener.reserveConnection(connection); ok {
			return reserved, nil
		}
	}
}
func (listener *privateListener) reserveConnection(connection net.Conn) (net.Conn, bool) {
	select {
	case listener.slots <- struct{}{}:
		return &privateConnection{Conn: connection, release: func() { <-listener.slots }}, true
	default:
		connection.Close()
		return nil, false
	}
}
func (listener *privateListener) Close() error   { return listener.listener.Close() }
func (listener *privateListener) Addr() net.Addr { return listener.listener.Addr() }
func peerUID(connection *net.UnixConn) (uint32, error) {
	raw, err := connection.SyscallConn()
	if err != nil {
		return 0, err
	}
	var credential *syscall.Ucred
	var controlError error
	if err := raw.Control(func(fd uintptr) {
		credential, controlError = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	}); err != nil {
		return 0, err
	}
	if controlError != nil {
		return 0, controlError
	}
	if credential == nil {
		return 0, fmt.Errorf("missing peer credentials")
	}
	return credential.Uid, nil
}
