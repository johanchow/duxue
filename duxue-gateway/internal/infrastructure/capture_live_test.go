package infrastructure

import (
	"bytes"
	"context"
	"image/jpeg"
	"os"
	"testing"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
)

// Opt-in field check: credentials stay in environment variables, and no images
// are saved. Uses the same authenticated FFmpeg path as the running gateway.
func TestLiveRTSPFreshJPEG(t *testing.T) {
	address := os.Getenv("GATEWAY_LIVE_RTSP_URL")
	if address == "" {
		t.Skip("GATEWAY_LIVE_RTSP_URL enables real camera verification")
	}
	for _, name := range []string{"GATEWAY_LIVE_CAMERA_USER", "GATEWAY_LIVE_CAMERA_PASSWORD"} {
		if os.Getenv(name) == "" {
			t.Fatalf("%s is required", name)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	source, err := SourceFactory("ffmpeg")(ctx, application.CameraConfig{Source: application.SourceConfig{
		Kind: "rtsp", URL: address,
		UsernameEnv: "GATEWAY_LIVE_CAMERA_USER", PasswordEnv: "GATEWAY_LIVE_CAMERA_PASSWORD",
	}})
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	var previous time.Time
	count := 0
	var lastError error
	for ctx.Err() == nil {
		data, capturedAt, err := source.Latest(ctx)
		if err != nil {
			lastError = err
		} else if capturedAt.After(previous) {
			frame, err := jpeg.Decode(bytes.NewReader(data))
			if err != nil {
				t.Fatal("camera frame is not a decodable JPEG")
			}
			bounds := frame.Bounds()
			if bounds.Dx() != 640 || bounds.Dy() < 1 {
				t.Fatalf("unexpected frame dimensions: %dx%d", bounds.Dx(), bounds.Dy())
			}
			if age := time.Since(capturedAt); age < 0 || age > 5*time.Second {
				t.Fatal("camera frame timestamp is not fresh")
			}
			previous = capturedAt
			count++
			t.Logf("fresh JPEG %d: %dx%d, %d bytes", count, bounds.Dx(), bounds.Dy(), len(data))
			if count == 3 {
				return
			}
		}
		time.Sleep(600 * time.Millisecond)
	}
	t.Fatalf("received %d of 3 fresh frames; last capture error: %v", count, lastError)
}
