package infrastructure

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"testing"
	"time"
)

func TestFFmpegFreshJPEGAndCancellation(t *testing.T) {
	binary, err := exec.LookPath("ffmpeg")
	if err != nil {
		t.Skip("FFmpeg not installed")
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stream := NewStream(ctx, binary, []string{"-hide_banner", "-loglevel", "error", "-nostdin", "-re", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=4", "-an", "-c:v", "mjpeg", "-threads", "1", "-f", "image2pipe", "pipe:1"})
	deadline := time.Now().Add(5 * time.Second)
	found := false
	for time.Now().Before(deadline) {
		data, _, err := stream.Latest(ctx)
		if err == nil {
			if len(data) < 4 || data[0] != 255 || data[1] != 216 {
				t.Fatal("not JPEG")
			}
			found = true
			break
		}
		time.Sleep(25 * time.Millisecond)
	}
	if !found {
		stream.Close()
		t.Fatal("FFmpeg did not produce fresh frame")
	}
	start := time.Now()
	if err = stream.Close(); err != nil {
		t.Fatal(err)
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("FFmpeg cancellation hung")
	}
	if _, _, err = stream.Latest(ctx); err == nil {
		t.Fatal("stopped source returned stale frame")
	}
}

func TestFailedFFmpegRestartIsBoundedAndCounted(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stream := NewStream(ctx, "/nonexistent-duxue-test-ffmpeg", nil)
	time.Sleep(1200 * time.Millisecond)
	if n := stream.Reconnects(); n < 1 || n > 2 {
		stream.Close()
		t.Fatalf("reconnect busy loop or missing metric: %d", n)
	}
	if err := stream.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestRTSPCredentialsNeverAppearInFFmpegArguments(t *testing.T) {
	root := t.TempDir()
	binary := filepath.Join(root, "fake-ffmpeg")
	argsFile := filepath.Join(root, "args")
	t.Setenv("TMPDIR", root)
	t.Setenv("TEST_CAMERA_USER", "private-camera-user")
	t.Setenv("TEST_CAMERA_PASSWORD", "private-password")
	if err := os.WriteFile(binary, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TMPDIR/args\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	source, err := SourceFactory(binary)(context.Background(), application.CameraConfig{Source: application.SourceConfig{Kind: "rtsp", URL: "rtsp://127.0.0.1/live", UsernameEnv: "TEST_CAMERA_USER", PasswordEnv: "TEST_CAMERA_PASSWORD"}})
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	for range 100 {
		b, err := os.ReadFile(argsFile)
		if err == nil {
			if strings.Contains(string(b), "private-password") || strings.Contains(string(b), "private-camera-user") {
				t.Fatal("camera credentials exposed in child argv")
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("FFmpeg not launched")
}
func TestFFmpegFailureHasActionableDiagnostic(t *testing.T) {
	stream := NewStream(context.Background(), "/bin/sh", []string{"-c", "echo 'method DESCRIBE failed: 401 Unauthorized' >&2; exit 1"})
	defer stream.Close()
	time.Sleep(100 * time.Millisecond)
	_, _, err := stream.Latest(context.Background())
	if err == nil || !strings.Contains(err.Error(), "401 Unauthorized") {
		t.Fatalf("camera error discarded: %v", err)
	}
}

func TestCaptureDiagnosticRedactsAcrossChunksAndBoundsOutput(t *testing.T) {
	d := &captureDiagnostic{secrets: []string{"secret-password"}}
	for _, chunk := range []string{"401 Unauthorized rtsp://user:secret-", "password@camera/live?token=private ", "secret-pass", "word\n"} {
		_, _ = d.Write([]byte(chunk))
		if strings.Contains(d.Text(), "secret") || strings.Contains(d.Text(), "private") {
			t.Fatal("partial secret exposed")
		}
	}
	if !strings.Contains(d.Text(), "401 Unauthorized") {
		t.Fatal("actionable error missing")
	}
	_, _ = d.Write([]byte(strings.Repeat("x", 4093) + "secret-password\n"))
	if strings.Contains(d.Text(), "password") {
		t.Fatal("truncated secret exposed")
	}
	if len(d.Text()) > 2048 {
		t.Fatal("diagnostic unbounded")
	}
}
