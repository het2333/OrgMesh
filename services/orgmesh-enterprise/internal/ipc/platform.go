// SPDX-License-Identifier: MIT
package ipc

import "errors"

func ValidatePlatform(platform string) error {
	if platform != "linux" {
		return errors.New("private enterprise transport requires Linux SO_PEERCRED")
	}
	return nil
}
