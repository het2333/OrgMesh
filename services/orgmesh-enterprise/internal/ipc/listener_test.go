package ipc

import (
	"os"
	"path/filepath"
	"testing"
)

func TestUnsafeSocket(t *testing.T) {
	for _, mode := range []os.FileMode{0755, 0777} {
		dir := t.TempDir()
		if err := os.Chmod(dir, mode); err != nil {
			t.Fatal(err)
		}
		if l, err := Listen(filepath.Join(dir, "enterprise.sock"), uint32(os.Getuid())); err == nil {
			l.Close()
			t.Fatal("unsafe directory accepted")
		}
	}
	dir := t.TempDir()
	os.Chmod(dir, 0700)
	path := filepath.Join(dir, "enterprise.sock")
	os.WriteFile(path, []byte("keep"), 0600)
	if l, err := Listen(path, uint32(os.Getuid())); err == nil {
		l.Close()
		t.Fatal("old file replaced")
	}
	if b, _ := os.ReadFile(path); string(b) != "keep" {
		t.Fatal("old file changed")
	}
	os.Remove(path)
	os.Symlink(filepath.Join(dir, "missing"), path)
	if l, err := Listen(path, uint32(os.Getuid())); err == nil {
		l.Close()
		t.Fatal("symlink accepted")
	}
}
func TestNonLinuxFailsClosed(t *testing.T) {
	for _, platform := range []string{"darwin", "windows", "freebsd", ""} {
		if ValidatePlatform(platform) == nil {
			t.Fatalf("%s accepted", platform)
		}
	}
}
