package infrastructure

import (
	"context"
	"os/exec"
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
