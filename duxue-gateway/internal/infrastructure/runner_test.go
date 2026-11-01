package infrastructure

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
)

func TestRunnerIsolatesBrokenCameraAndStopsCleanly(t *testing.T) {
	camera := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte{255, 216, 1, 2, 255, 217}) }))
	defer camera.Close()
	var server *httptest.Server
	var mu sync.Mutex
	commits := 0
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/gateway/cameras":
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			_ = json.NewEncoder(w).Encode(map[string]any{"gateway_id": "home", "device_id": "device-" + body["camera_id"], "ward_id": body["ward_id"], "assignment_revision": 1})
		case "/gateway/frames/upload-url":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			_ = json.NewEncoder(w).Encode(application.Target{Key: "key/" + body["frame_id"].(string), URL: server.URL + "/object", ExpiresAt: time.Now().Add(time.Minute)})
		case "/object":
			w.WriteHeader(204)
		case "/gateway/frames":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			mu.Lock()
			commits++
			mu.Unlock()
			_ = json.NewEncoder(w).Encode(application.Receipt{ID: "accepted", FrameID: body["frame_id"].(string)})
		case "/gateway/heartbeat":
			w.WriteHeader(200)
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	c := testConfig(t)
	c.IntervalSeconds = 1
	c.Cameras = []application.CameraConfig{
		{ID: "healthy", WardID: "ward", Source: application.SourceConfig{Kind: "snapshot", URL: camera.URL}},
		{ID: "broken", WardID: "ward-two", Source: application.SourceConfig{Kind: "snapshot", URL: camera.URL + "/bad"}},
	}
	// A separate snapshot endpoint fails immediately, rather than holding a global lock.
	failed := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	defer failed.Close()
	c.Cameras[1].Source.URL = failed.URL
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 2600*time.Millisecond)
	defer cancel()
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Sources: SourceFactory("ffmpeg"), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if err = runner.Run(ctx); err != nil {
		t.Fatal(err)
	}
	health, err := store.Health()
	if err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	count := commits
	mu.Unlock()
	if count < 1 {
		t.Fatal("healthy camera made no progress")
	}
	if health[0].CameraID != "broken" || health[0].Gaps < 1 || health[1].LastSubmit == nil {
		t.Fatalf("camera health not isolated: %+v", health)
	}
}

func TestStartupErasurePurgesRecoveredOrphanBundle(t *testing.T) {
	c := testConfig(t)
	c.Cameras = []application.CameraConfig{{ID: "cam", WardID: "ward-cam"}}
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	frame := testFrame(t, store, "cam", time.Now().UTC())
	if _, err = store.db.Exec("DELETE FROM frames WHERE id=?", frame.ID); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(403)
		_, _ = w.Write([]byte(`{"error_code":"WARD_DATA_ERASED"}`))
	}))
	defer server.Close()
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if err = runner.Run(context.Background()); err == nil {
		t.Fatal("erased source reactivated")
	}
	health, err := store.Health()
	if err != nil {
		t.Fatal(err)
	}
	if health[0].QueueFrames != 0 || health[0].Dropped != 1 {
		t.Fatalf("orphan evidence was not erased: %+v", health)
	}
	if _, err = store.ReadImage(frame); err == nil {
		t.Fatal("erased image retained")
	}
}

type erasureSource struct {
	calls                      int
	started, release, returned chan struct{}
}

func (s *erasureSource) Latest(ctx context.Context) ([]byte, time.Time, error) {
	s.calls++
	if s.calls == 2 {
		close(s.started)
		defer close(s.returned)
		select {
		case <-ctx.Done():
			return nil, time.Time{}, ctx.Err()
		case <-s.release:
		}
	}
	return []byte{255, 216, 1, 255, 217}, time.Now().UTC(), nil
}
func (s *erasureSource) Close() error { return nil }
func TestErasureCannotRaceWithAnInFlightCameraCapture(t *testing.T) {
	c := testConfig(t)
	c.IntervalSeconds = 1
	c.Cameras = []application.CameraConfig{{ID: "cam", WardID: "ward"}}
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	source := &erasureSource{started: make(chan struct{}), release: make(chan struct{}), returned: make(chan struct{})}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/gateway/cameras":
			_ = json.NewEncoder(w).Encode(map[string]any{"gateway_id": "home", "device_id": "device", "ward_id": "ward", "assignment_revision": 1})
		case "/gateway/frames/upload-url":
			select {
			case <-source.started:
			case <-r.Context().Done():
				return
			}
			w.WriteHeader(403)
			_, _ = w.Write([]byte(`{"error_code":"WARD_DATA_ERASED"}`))
		case "/gateway/heartbeat":
			w.WriteHeader(200)
		default:
			t.Error("erased source attempted object upload")
			w.WriteHeader(500)
		}
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Sources: func(context.Context, application.CameraConfig) (application.Source, error) { return source, nil }, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	done := make(chan error, 1)
	go func() { done <- runner.Run(ctx) }()
	select {
	case <-source.started:
	case <-ctx.Done():
		t.Fatal("second capture did not start")
	}
	erased := false
	for range 100 {
		health, err := store.Health()
		if err != nil {
			t.Fatal(err)
		}
		if len(health) > 0 && health[0].Dropped == 1 {
			erased = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	close(source.release)
	select {
	case <-source.returned:
	case <-ctx.Done():
		t.Fatal("capture failed to return")
	}
	cancel()
	if err = <-done; err != nil {
		t.Fatal(err)
	}
	health, err := store.Health()
	if err != nil {
		t.Fatal(err)
	}
	if !erased || health[0].QueueFrames != 0 || health[0].CapturedCount != 1 {
		t.Fatalf("in-flight capture escaped erasure: %+v", health)
	}
}

type constantSource struct{}

func (constantSource) Latest(context.Context) ([]byte, time.Time, error) {
	return []byte{255, 216, 1, 255, 217}, time.Now().UTC(), nil
}
func (constantSource) Close() error { return nil }
func TestDisabledRegistrationDoesNotPreventOtherCameraStarting(t *testing.T) {
	c := testConfig(t)
	c.IntervalSeconds = 1
	c.Cameras = []application.CameraConfig{{ID: "erased", WardID: "ward-old"}, {ID: "healthy", WardID: "ward"}}
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/gateway/cameras" {
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["camera_id"] == "erased" {
				w.WriteHeader(403)
				_, _ = w.Write([]byte(`{"error_code":"WARD_DATA_ERASED"}`))
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"gateway_id": "home", "device_id": "device", "ward_id": "ward", "assignment_revision": 1})
			return
		}
		if r.URL.Path == "/gateway/heartbeat" {
			w.WriteHeader(200)
			return
		}
		w.WriteHeader(503)
	}))
	defer server.Close()
	created := []string{}
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Sources: func(_ context.Context, cam application.CameraConfig) (application.Source, error) {
		created = append(created, cam.ID)
		return constantSource{}, nil
	}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ctx, cancel := context.WithTimeout(context.Background(), 1400*time.Millisecond)
	defer cancel()
	if err = runner.Run(ctx); err != nil {
		t.Fatal(err)
	}
	if len(created) != 1 || created[0] != "healthy" {
		t.Fatalf("inactive source affected peers: %v", created)
	}
	health, err := store.Health()
	if err != nil || len(health) != 1 || health[0].CapturedCount < 1 {
		t.Fatalf("healthy camera failed to capture: %+v %v", health, err)
	}
}

type closeObservedSource struct {
	constantSource
	closed chan struct{}
	once   sync.Once
}

func (s *closeObservedSource) Close() error { s.once.Do(func() { close(s.closed) }); return nil }
func TestRevocationClosesSourceBeforeGatewayShutdown(t *testing.T) {
	c := testConfig(t)
	c.IntervalSeconds = 1
	c.Cameras = []application.CameraConfig{{ID: "cam", WardID: "ward"}}
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	source := &closeObservedSource{closed: make(chan struct{})}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/gateway/cameras":
			_ = json.NewEncoder(w).Encode(map[string]any{"gateway_id": "home", "device_id": "device", "ward_id": "ward", "assignment_revision": 1})
		case "/gateway/heartbeat":
			w.WriteHeader(200)
		default:
			w.WriteHeader(403)
			_, _ = w.Write([]byte(`{"error_code":"CAMERA_DISABLED"}`))
		}
	}))
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Sources: func(context.Context, application.CameraConfig) (application.Source, error) { return source, nil }, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	done := make(chan error, 1)
	go func() { done <- runner.Run(ctx) }()
	select {
	case <-source.closed:
	case <-time.After(3 * time.Second):
		cancel()
		<-done
		t.Fatal("revoked source still streaming")
	}
	cancel()
	if err = <-done; err != nil {
		t.Fatal(err)
	}
}

func TestTransientAPIUnauthorizedRecoversWithoutRestart(t *testing.T) {
	c := testConfig(t)
	c.IntervalSeconds = 1
	c.Cameras = []application.CameraConfig{{ID: "cam", WardID: "ward"}}
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	var mu sync.Mutex
	requests, commits := 0, 0
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/gateway/cameras":
			_ = json.NewEncoder(w).Encode(map[string]any{"gateway_id": "home", "device_id": "device", "ward_id": "ward", "assignment_revision": 1})
		case "/gateway/heartbeat":
			w.WriteHeader(200)
		case "/gateway/frames/upload-url":
			mu.Lock()
			requests++
			n := requests
			mu.Unlock()
			if n == 1 {
				w.WriteHeader(401)
				return
			}
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			_ = json.NewEncoder(w).Encode(application.Target{Key: "key/" + body["frame_id"].(string), URL: server.URL + "/object", ExpiresAt: time.Now().Add(time.Minute)})
		case "/object":
			w.WriteHeader(204)
		case "/gateway/frames":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			mu.Lock()
			commits++
			mu.Unlock()
			_ = json.NewEncoder(w).Encode(application.Receipt{ID: "accepted", FrameID: body["frame_id"].(string)})
		}
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Sources: func(context.Context, application.CameraConfig) (application.Source, error) {
		return constantSource{}, nil
	}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if err = runner.Run(ctx); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	defer mu.Unlock()
	if commits == 0 {
		t.Fatal("a single 401 permanently froze uploads")
	}
}

func TestPersistentUnauthorizedIsVisibleAndStopsAllCapture(t *testing.T) {
	c := testConfig(t)
	c.IntervalSeconds = 1
	c.Cameras = []application.CameraConfig{{ID: "cam", WardID: "ward"}}
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	source := &closeObservedSource{closed: make(chan struct{})}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/gateway/cameras" {
			_ = json.NewEncoder(w).Encode(map[string]any{"gateway_id": "home", "device_id": "device", "ward_id": "ward", "assignment_revision": 1})
			return
		}
		w.WriteHeader(401)
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	runner := application.Runner{Config: c, Repository: store, Cloud: NewCloud(server.URL, "token"), Sources: func(context.Context, application.CameraConfig) (application.Source, error) { return source, nil }, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if err = runner.Run(ctx); err == nil {
		t.Fatal("persistent bad credentials did not stop gateway")
	}
	select {
	case <-source.closed:
	default:
		t.Fatal("capture remained running after auth failure")
	}
	health, err := store.Health()
	if err != nil || len(health) != 1 || health[0].GatewayAuth != "required" || health[0].Error != "gateway_auth_required" {
		t.Fatalf("authentication state not explicit: %+v %v", health, err)
	}
}
