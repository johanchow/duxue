package infrastructure

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
)

func TestLostCommitResponseResumesWithoutReuploadAndSeparatesCredentials(t *testing.T) {
	c := testConfig(t)
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	frame := testFrame(t, store, "cam", time.Now().UTC())
	puts, reserves, commits := 0, 0, 0
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "PUT" {
			puts++
			if r.Header.Get("Authorization") != "" {
				t.Error("API token leaked to object storage")
			}
			w.WriteHeader(204)
			return
		}
		if r.Header.Get("Authorization") != "Bearer secret" {
			t.Error("API authorization missing")
		}
		switch r.URL.Path {
		case "/gateway/frames/upload-url":
			reserves++
			_ = json.NewEncoder(w).Encode(application.Target{Key: "stable-key", URL: server.URL + "/object", ExpiresAt: time.Now().Add(time.Minute)})
		case "/gateway/frames":
			commits++
			if commits == 1 {
				w.WriteHeader(503)
				return
			}
			_ = json.NewEncoder(w).Encode(application.Receipt{ID: "accepted", FrameID: frame.ID})
		default:
			t.Errorf("unexpected path %s", r.URL.Path)
		}
	}))
	defer server.Close()
	runner := application.Runner{Repository: store, Cloud: NewCloud(server.URL, "secret")}
	if err = runner.Deliver(context.Background(), frame); err == nil {
		t.Fatal("lost response not simulated")
	}
	if err = store.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	frame, _, ok, err := store.Claim(time.Now())
	if err != nil || !ok {
		t.Fatal(err)
	}
	if frame.State != domain.Uploaded {
		t.Fatal("PUT checkpoint missing")
	}
	if err = runner.Deliver(context.Background(), frame); err != nil {
		t.Fatal(err)
	}
	if puts != 1 || reserves != 1 || commits != 2 {
		t.Fatalf("unexpected retries: puts=%d reserves=%d commits=%d", puts, reserves, commits)
	}
}
func TestAPIAndObjectRedirectsAreNotFollowed(t *testing.T) {
	received := 0
	sink := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { received++ }))
	defer sink.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, sink.URL, 307) }))
	defer server.Close()
	cloud := NewCloud(server.URL, "secret")
	if _, err := cloud.Commit(context.Background(), domain.Frame{}); err == nil {
		t.Fatal("API redirect accepted")
	}
	if err := cloud.Put(context.Background(), application.Target{URL: server.URL}, []byte("jpeg")); err == nil {
		t.Fatal("object redirect accepted")
	}
	if received != 0 {
		t.Fatal("followed redirect")
	}
}

func TestExpiredObjectURLRenewsSameKeyInsteadOfRevokingGateway(t *testing.T) {
	c := testConfig(t)
	store, err := OpenStore(c, false)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	frame := testFrame(t, store, "cam", time.Now().UTC())
	reserves := 0
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/gateway/frames/upload-url":
			reserves++
			path := "/fresh"
			if reserves == 1 {
				path = "/expired"
			}
			_ = json.NewEncoder(w).Encode(application.Target{Key: "same-key", URL: server.URL + path, ExpiresAt: time.Now().Add(time.Minute)})
		case "/expired":
			w.WriteHeader(403)
		case "/fresh":
			w.WriteHeader(204)
		case "/gateway/frames":
			_ = json.NewEncoder(w).Encode(application.Receipt{ID: "accepted", FrameID: frame.ID})
		}
	}))
	defer server.Close()
	runner := application.Runner{Repository: store, Cloud: NewCloud(server.URL, "token")}
	err = runner.Deliver(context.Background(), frame)
	remote, ok := err.(*application.RemoteError)
	if !ok || !remote.Temporary() || remote.Origin != "object" {
		t.Fatalf("expired URL treated as gateway revocation: %v", err)
	}
	if err = store.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	pending, _, ok, err := store.Claim(time.Now())
	if err != nil || !ok {
		t.Fatal(err)
	}
	if err = runner.Deliver(context.Background(), pending); err != nil {
		t.Fatal(err)
	}
	if reserves != 2 || pending.ObjectKey != "same-key" {
		t.Fatal("URL retry changed evidence identity")
	}
}
