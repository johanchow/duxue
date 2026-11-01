package infrastructure

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"strconv"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
)

type Cloud struct {
	base, token  string
	api, objects *http.Client
}

func NewCloud(base, token string) *Cloud {
	reject := func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return &Cloud{base: base, token: token, api: &http.Client{Timeout: 15 * time.Second, CheckRedirect: reject, Transport: apiTransport()}, objects: &http.Client{Timeout: 30 * time.Second, CheckRedirect: reject, Transport: apiTransport()}}
}
func (c *Cloud) request(ctx context.Context, path string, body any, out any) error {
	data, err := json.Marshal(body)
	if err != nil {
		return errors.New("cannot encode API request")
	}
	req, err := http.NewRequestWithContext(ctx, "POST", c.base+path, bytes.NewReader(data))
	if err != nil {
		return errors.New("invalid API address")
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	response, err := c.api.Do(req)
	if err != nil {
		return &application.RemoteError{Code: "network_error"}
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return remoteError(response)
	}
	if out != nil && json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(out) != nil {
		return &application.RemoteError{Code: "invalid_response"}
	}
	return nil
}
func remoteError(response *http.Response) error {
	var body struct {
		Code string `json:"error_code"`
	}
	_ = json.NewDecoder(io.LimitReader(response.Body, 4096)).Decode(&body)
	if body.Code == "" {
		body.Code = "http_error"
	}
	// Never return raw provider bodies or URLs: they can contain secrets.
	retry := time.Duration(0)
	if n, err := strconv.Atoi(response.Header.Get("Retry-After")); err == nil && n > 0 {
		retry = time.Duration(n) * time.Second
	} else if at, err := http.ParseTime(response.Header.Get("Retry-After")); err == nil {
		retry = time.Until(at)
	}
	if retry > time.Hour {
		retry = time.Hour
	}
	return &application.RemoteError{Status: response.StatusCode, Code: body.Code, RetryAfter: retry}
}
func (c *Cloud) Register(ctx context.Context, cam application.CameraConfig) (domain.Registration, error) {
	var r domain.Registration
	err := c.request(ctx, "/gateway/cameras", map[string]any{"camera_id": cam.ID, "ward_id": cam.WardID}, &r)
	if err == nil && (r.GatewayID == "" || r.DeviceID == "" || r.WardID != cam.WardID || r.Revision < 1) {
		err = &application.RemoteError{Code: "invalid_registration"}
	}
	return r, err
}
func evidence(f domain.Frame) map[string]any {
	return map[string]any{"camera_id": f.CameraID, "ward_id": f.WardID, "assignment_revision": f.Revision, "frame_id": f.ID, "captured_at": f.CapturedAt, "sha256": f.SHA256, "size_bytes": f.SizeBytes, "content_type": "image/jpeg"}
}
func (c *Cloud) Reserve(ctx context.Context, f domain.Frame) (application.Target, error) {
	var t application.Target
	err := c.request(ctx, "/gateway/frames/upload-url", evidence(f), &t)
	if err == nil && (t.Key == "" || t.URL == "" || t.ExpiresAt.Before(time.Now())) {
		err = &application.RemoteError{Code: "invalid_upload_target"}
	}
	return t, err
}
func (c *Cloud) Put(ctx context.Context, t application.Target, data []byte) error {
	req, err := http.NewRequestWithContext(ctx, "PUT", t.URL, bytes.NewReader(data))
	if err != nil {
		return errors.New("invalid upload address")
	}
	// HTTP development endpoints only on loopback. No API credentials here.
	if req.URL.User != nil {
		return errors.New("unexpected object URL credentials")
	}
	if req.URL.Scheme != "https" && !(req.URL.Scheme == "http" && (req.URL.Hostname() == "localhost" || req.URL.Hostname() == "127.0.0.1" || req.URL.Hostname() == "::1")) {
		return errors.New("unsafe upload address")
	}
	for k, v := range t.Headers {
		if http.CanonicalHeaderKey(k) == "Authorization" {
			return errors.New("unexpected object authorization header")
		}
		req.Header.Set(k, v)
	}
	response, err := c.objects.Do(req)
	if err != nil {
		return &application.RemoteError{Code: "object_network_error"}
	}
	defer response.Body.Close()
	if response.StatusCode == 409 {
		return nil
	} // Immutable key may already exist after a lost PUT response; commit verifies the bytes.
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		err := remoteError(response)
		if remote, ok := err.(*application.RemoteError); ok {
			remote.Origin = "object"
		}
		return err
	}
	return nil
}
func (c *Cloud) Commit(ctx context.Context, f domain.Frame) (application.Receipt, error) {
	var r application.Receipt
	b := evidence(f)
	b["oss_key"] = f.ObjectKey
	err := c.request(ctx, "/gateway/frames", b, &r)
	if err == nil && (r.ID == "" || r.FrameID != f.ID) {
		err = &application.RemoteError{Code: "invalid_receipt"}
	}
	return r, err
}
func (c *Cloud) Heartbeat(ctx context.Context, boot string, seq int, health []application.CameraHealth) error {
	cameras := make([]map[string]any, 0, len(health))
	for _, h := range health {
		cameras = append(cameras, map[string]any{"camera_id": h.CameraID, "last_capture_at": h.LastCapture, "last_submit_at": h.LastSubmit, "queue_frames": h.QueueFrames, "queue_bytes": h.QueueBytes, "dropped_count": h.Dropped, "last_error_code": nullableErrorCode(h.Error)})
	}
	return c.request(ctx, "/gateway/heartbeat", map[string]any{"boot_id": boot, "sequence": seq, "cameras": cameras}, nil)
}

func nullableErrorCode(code string) any {
	if code == "" {
		return nil
	}
	return code
}

func apiTransport() *http.Transport {
	return &http.Transport{Proxy: http.ProxyFromEnvironment, DialContext: (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext, ForceAttemptHTTP2: true, MaxIdleConns: 8, MaxIdleConnsPerHost: 2, IdleConnTimeout: 90 * time.Second, TLSHandshakeTimeout: 5 * time.Second}
}
func (c *Cloud) Close() { c.api.CloseIdleConnections(); c.objects.CloseIdleConnections() }
