package infrastructure

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
)

func testConfig(t *testing.T) application.Config {
	return application.Config{StateDir: t.TempDir(), TTLSeconds: 43200, MaxFrames: 2000, MaxBytes: 10000000}
}
func testFrame(t *testing.T, s *Store, camera string, at time.Time) domain.Frame {
	t.Helper()
	reg := domain.Registration{GatewayID: "home", DeviceID: "device-" + camera, WardID: "ward-" + camera, Revision: 1}
	if err := s.Register(camera, reg); err != nil {
		t.Fatal(err)
	}
	f, err := domain.NewFrame(camera, reg, at, []byte("image"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Enqueue(f, []byte("image")); err != nil {
		t.Fatal(err)
	}
	return f
}
func TestQueuePersistsIdentityAndResumesUploadedFrame(t *testing.T) {
	c := testConfig(t)
	s, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	f := testFrame(t, s, "cam", time.Now().UTC())
	if err = f.AssignTarget("ward/key"); err != nil {
		t.Fatal(err)
	}
	if err = f.MarkUploaded(); err != nil {
		t.Fatal(err)
	}
	if err = s.Save(f); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s, err = OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if err = s.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	loaded, _, ok, err := s.Claim(time.Now())
	if err != nil || !ok {
		t.Fatalf("claim %v %v", ok, err)
	}
	if loaded.ID != f.ID || loaded.ObjectKey != f.ObjectKey || loaded.State != domain.Uploaded || loaded.Registration != f.Registration || !loaded.CapturedAt.Equal(f.CapturedAt) {
		t.Fatalf("identity changed: %+v", loaded)
	}
	changed := loaded
	changed.WardID = "different"
	if s.Save(changed) == nil {
		t.Fatal("changed ownership accepted")
	}
	if err = loaded.Acknowledge("server-frame"); err != nil {
		t.Fatal(err)
	}
	if err = s.Save(loaded); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(s.bundle(f.ID)); !os.IsNotExist(err) {
		t.Fatalf("delivered image retained: %v", err)
	}
}
func TestRecoveryRepairsUncommittedBundleAndDetectsLostImage(t *testing.T) {
	c := testConfig(t)
	s, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	f := testFrame(t, s, "cam", time.Now().UTC())
	if _, err = s.db.Exec("DELETE FROM frames WHERE id=?", f.ID); err != nil {
		t.Fatal(err)
	}
	if err = s.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	got, _, ok, err := s.Claim(time.Now())
	if err != nil || !ok || got.ID != f.ID {
		t.Fatalf("orphan bundle not restored: %v", err)
	}
	if err = os.Remove(filepath.Join(s.bundle(f.ID), "image.jpg")); err != nil {
		t.Fatal(err)
	}
	if err = s.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	health, err := s.Health()
	if err != nil {
		t.Fatal(err)
	}
	if health[0].QueueFrames != 0 || health[0].Dropped != 1 {
		t.Fatalf("missing file not reflected: %+v", health)
	}
}
func TestQueueCapsTTLAndLeases(t *testing.T) {
	c := testConfig(t)
	c.MaxFrames = 1
	s, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	first := testFrame(t, s, "cam", time.Now().UTC().Add(-time.Minute))
	claimed, _, ok, err := s.Claim(time.Now())
	if err != nil || !ok {
		t.Fatal(err)
	}
	second := testFrame(t, s, "cam", time.Now().UTC())
	if err = s.Prune(time.Now()); err != nil {
		t.Fatal(err)
	}
	var state string
	if err = s.db.QueryRow("SELECT state FROM frames WHERE id=?", claimed.ID).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state == string(domain.Discarded) {
		t.Fatal("active upload lease evicted")
	}
	// Capacity evicts only an unleased frame, even if it is the most recent.
	if err = s.db.QueryRow("SELECT state FROM frames WHERE id=?", second.ID).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != string(domain.Discarded) {
		t.Fatal("capacity was not enforced")
	}
	if err = s.Retry(first.ID, 1, time.Now(), false, ""); err != nil {
		t.Fatal(err)
	}
	if err = s.Prune(time.Now().Add(13 * time.Hour)); err != nil {
		t.Fatal(err)
	}
	health, _ := s.Health()
	if health[0].QueueFrames != 0 || health[0].Dropped != 2 {
		t.Fatalf("TTL/cap counts: %+v", health)
	}
}
func TestSingleInstanceAndReadOnlyStatus(t *testing.T) {
	c := testConfig(t)
	s, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	testFrame(t, s, "cam", time.Now().UTC())
	duplicate, err := OpenStore(c, false)
	if err == nil {
		duplicate.Close()
		t.Fatal("second writer allowed")
	}
	reader, err := OpenStore(c, true)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	h, err := reader.Health()
	if err != nil || len(h) != 1 {
		t.Fatalf("live status unavailable: %v", err)
	}
}
func TestRecoveryDoesNotReviveDeliveredManifest(t *testing.T) {
	c := testConfig(t)
	s, _ := OpenStore(c, false)
	defer s.Close()
	f := testFrame(t, s, "cam", time.Now().UTC())
	original, _ := json.Marshal(f)
	_ = f.AssignTarget("key")
	_ = f.MarkUploaded()
	_ = f.Acknowledge("server")
	if err := s.Save(f); err != nil {
		t.Fatal(err)
	}
	// Simulate an interrupted cleanup leaving the older on-disk manifest.
	dir := s.bundle(f.ID)
	_ = os.Mkdir(dir, 0700)
	_ = os.WriteFile(filepath.Join(dir, "manifest.json"), original, 0600)
	_ = os.WriteFile(filepath.Join(dir, "image.jpg"), []byte("image"), 0600)
	if err := s.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	_, _, ok, err := s.Claim(time.Now())
	if err != nil || ok {
		t.Fatal("delivered evidence was requeued")
	}
}

var _ application.Repository = (*Store)(nil)

func TestDiagnosticsAndFutureSchemaProtection(t *testing.T) {
	c := testConfig(t)
	s, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	testFrame(t, s, "cam", time.Now().UTC())
	if err = s.CaptureHealth("cam", time.Now(), true, ""); err != nil {
		t.Fatal(err)
	}
	if err = s.AddDiagnostics("cam", 3, 2); err != nil {
		t.Fatal(err)
	}
	h, err := s.Health()
	if err != nil || h[0].CapturedCount != 1 || h[0].Gaps != 3 || h[0].Reconnects != 2 {
		t.Fatalf("diagnostics: %+v %v", h, err)
	}
	if _, err = s.db.Exec("PRAGMA user_version=99"); err != nil {
		t.Fatal(err)
	}
	s.Close()
	future, err := OpenStore(c, false)
	if err == nil {
		future.Close()
		t.Fatal("silently downgraded future queue schema")
	}
}

func TestClaimsAreFairAndReserveFreshFrameQuotaForEachCamera(t *testing.T) {
	c := testConfig(t)
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	at := time.Now().UTC().Add(-time.Minute)
	ids := map[string][]string{}
	for _, camera := range []string{"a", "b"} {
		for i := range 12 {
			f := testFrame(t, store, camera, at.Add(time.Duration(i)*time.Millisecond))
			ids[camera] = append(ids[camera], f.ID)
		}
	}
	order := []int{11, 0, 1, 2}
	for i := range 8 {
		f, _, ok, err := store.Claim(time.Now())
		if err != nil || !ok {
			t.Fatal(err)
		}
		camera := []string{"a", "b"}[i%2]
		if f.CameraID != camera || f.ID != ids[camera][order[i/2]] {
			t.Fatalf("unexpected fairness/quota at %d: %+v", i, f)
		}
	}
}
