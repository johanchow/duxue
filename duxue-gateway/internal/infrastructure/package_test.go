package infrastructure

import (
	"archive/tar"
	"compress/gzip"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestReleasePackagesExcludeRuntimePhotosAndCredentials(t *testing.T) {
	// Stub only the compiler in an isolated fixture. Actual cross-compilation is
	// verified separately by build.sh; this test covers the archive privacy boundary.
	root := t.TempDir()
	for _, dir := range []string{"scripts", "configs", "deploy", "bin", "dist/duxue-gateway-linux-amd64/state"} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0700); err != nil {
			t.Fatal(err)
		}
	}
	source, err := os.ReadFile("../../scripts/build.sh")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(root, "scripts/build.sh"), source, 0700); err != nil {
		t.Fatal(err)
	}
	for path, content := range map[string]string{
		"configs/config.example.yaml": "public example", "deploy/duxue-gateway.service": "public service",
		"dist/duxue-gateway-linux-amd64/credentials.env": "private-token",
		"dist/duxue-gateway-linux-amd64/config.yaml":     "private-password",
		"dist/duxue-gateway-linux-amd64/state/frame.jpg": "private-photo",
		"bin/go": "#!/bin/sh\nwhile [ $# -gt 0 ]; do\n if [ \"$1\" = '-o' ]; then shift; printf 'public binary' > \"$1\"; exit 0; fi\n shift\ndone\nexit 1\n",
	} {
		if err = os.WriteFile(filepath.Join(root, path), []byte(content), 0700); err != nil {
			t.Fatal(err)
		}
	}
	cmd := exec.Command("bash", filepath.Join(root, "scripts/build.sh"))
	cmd.Env = append(os.Environ(), "PATH="+filepath.Join(root, "bin")+":"+os.Getenv("PATH"), "DIST_DIR="+filepath.Join(root, "dist"))
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("fixture packaging failed: %s %v", output, err)
	}
	for _, platform := range []string{"darwin-arm64", "linux-amd64", "linux-arm64"} {
		file, err := os.Open(filepath.Join(root, "dist", "duxue-gateway-"+platform+".tar.gz"))
		if err != nil {
			t.Fatal(err)
		}
		zipped, err := gzip.NewReader(file)
		if err != nil {
			file.Close()
			t.Fatal(err)
		}
		archive := tar.NewReader(zipped)
		foundBinary := false
		for {
			header, err := archive.Next()
			if err == io.EOF {
				break
			}
			if err != nil {
				t.Fatal(err)
			}
			content, err := io.ReadAll(archive)
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(header.Name, "state/") || strings.HasSuffix(header.Name, "credentials.env") || strings.HasSuffix(header.Name, "/config.yaml") || strings.Contains(string(content), "private-") {
				t.Fatalf("runtime secret included in release: %s", header.Name)
			}
			if strings.HasSuffix(header.Name, "/duxue-gateway") {
				foundBinary = true
			}
		}
		zipped.Close()
		file.Close()
		if !foundBinary {
			t.Fatal("release has no executable")
		}
	}
}
