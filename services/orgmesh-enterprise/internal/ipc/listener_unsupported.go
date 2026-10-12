//go:build !linux

// SPDX-License-Identifier: MIT
package ipc

import (
	"net"
	"runtime"
)

func Listen(path string, allowedUID uint32) (net.Listener, error) {
	return nil, ValidatePlatform(runtime.GOOS)
}
