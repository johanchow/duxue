package application

import (
	"context"
	"errors"
	"log/slog"
	"math/rand/v2"
	"sync"
	"sync/atomic"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
)

var ErrGatewayAuthentication = errors.New("gateway authentication required; update credentials and restart")

type Runner struct {
	Config        Config
	Repository    Repository
	Cloud         Cloud
	Sources       SourceFactory
	Log           *slog.Logger
	blocked       atomic.Bool
	mu            sync.Mutex
	stopped       map[string]bool
	gatewayID     string
	sourceCancels map[string]context.CancelFunc
	authWake      chan struct{}
	fatal         chan error
}

func wait(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
func (r *Runner) stoppedCamera(id string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.stopped[id]
}
func (r *Runner) stopCamera(id string) {
	r.mu.Lock()
	r.stopped[id] = true
	cancel := r.sourceCancels[id]
	r.mu.Unlock()
	if cancel != nil {
		cancel()
	}
}
func (r *Runner) Run(parent context.Context) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	if r.Log == nil {
		r.Log = slog.Default()
	}
	r.stopped = map[string]bool{}
	r.sourceCancels = map[string]context.CancelFunc{}
	r.authWake = make(chan struct{}, 1)
	r.fatal = make(chan error, 1)
	r.blocked.Store(false)
	regs := map[string]domain.Registration{}
	// Restore orphan bundles before contacting the API, so erasure also covers them.
	for _, cam := range r.Config.Cameras {
		cached, err := r.Repository.Registration(cam.ID)
		if err == nil && cached.WardID != cam.WardID {
			return errors.New("camera Ward differs from saved registration; use a new camera ID")
		}
	}
	if err := r.Repository.Recover(time.Now()); err != nil {
		return err
	}

	// Revalidate registration; a source-specific revocation does not stop peers.
	for _, cam := range r.Config.Cameras {
		cached, cacheErr := r.Repository.Registration(cam.ID)
		reg, err := r.register(ctx, cam)
		if err != nil {
			if errors.Is(err, ErrGatewayAuthentication) {
				return err
			}
			var remote *RemoteError
			if errors.As(err, &remote) && (remote.Code == "WARD_DELETED" || remote.Code == "WARD_DATA_ERASED") {
				if purgeErr := r.Repository.DropCamera(cam.ID, "ward_erased"); purgeErr != nil {
					return purgeErr
				}
			}
			if errors.As(err, &remote) && remote.Status == 403 {
				r.stopCamera(cam.ID)
				r.Log.Warn("camera registration is disabled", "camera_id", cam.ID)
				continue
			}
			if cacheErr != nil || !errors.As(err, &remote) || !remote.Temporary() {
				return errors.New("camera registration failed; check configuration, authorization and connectivity")
			}
			reg = cached
			r.Log.Warn("using saved registration during network outage", "camera_id", cam.ID)
		}
		if err = r.Repository.Register(cam.ID, reg); err != nil {
			return err
		}
		if r.gatewayID != "" && r.gatewayID != reg.GatewayID {
			return errors.New("camera registrations belong to different gateways")
		}
		r.gatewayID = reg.GatewayID
		regs[cam.ID] = reg
	}
	if len(regs) == 0 {
		return errors.New("no authorized cameras; remove inactive sources or explicitly configure a new camera ID")
	}
	if err := r.Repository.SetGatewayAuth(""); err != nil {
		return err
	}
	var wg sync.WaitGroup
	start := func(f func()) { wg.Add(1); go func() { defer wg.Done(); f() }() }
	for _, cam := range r.Config.Cameras {
		if r.stoppedCamera(cam.ID) {
			continue
		}
		sourceCtx, sourceCancel := context.WithCancel(ctx)
		r.sourceCancels[cam.ID] = sourceCancel
		source, err := r.Sources(sourceCtx, cam)
		if err != nil {
			cancel()
			wg.Wait()
			return err
		}
		start(func() { defer source.Close(); r.collect(sourceCtx, cam, regs[cam.ID], source) })
	}
	for range 2 {
		start(func() { r.upload(ctx) })
	}
	start(func() { r.heartbeat(ctx) })
	start(func() {
		for wait(ctx, 5*time.Second) {
			if err := r.Repository.Prune(time.Now()); err != nil {
				r.Log.Error("queue maintenance failed")
			}
		}
	})
	var result error
	select {
	case <-ctx.Done():
	case result = <-r.fatal:
	}
	cancel()
	wg.Wait()
	return result
}
func (r *Runner) collect(ctx context.Context, cam CameraConfig, reg domain.Registration, source Source) {
	interval := time.Duration(r.Config.IntervalSeconds) * time.Second
	lastTick := time.Now()
	var reconnects int64
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case at := <-ticker.C:
			skipped := int((at.Sub(lastTick)+interval/2)/interval) - 1
			lastTick = at
			if skipped > 0 {
				_ = r.Repository.AddDiagnostics(cam.ID, skipped, 0)
			}
		}
		if diagnostic, ok := source.(interface{ Reconnects() int64 }); ok {
			current := diagnostic.Reconnects()
			if current > reconnects {
				_ = r.Repository.AddDiagnostics(cam.ID, 0, current-reconnects)
				reconnects = current
			}
		}
		if r.stoppedCamera(cam.ID) {
			return
		}
		data, at, err := source.Latest(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			_ = r.Repository.CaptureHealth(cam.ID, time.Now(), false, "capture_failed")
			// Source errors are bounded and redacted by the capture adapter.
			_ = r.Repository.CaptureDiagnostic(cam.ID, err.Error())
			r.Log.Warn("camera capture failed", "camera_id", cam.ID, "detail", err.Error())
			continue
		}
		if at.IsZero() || time.Since(at) > 5*time.Second || at.After(time.Now().Add(time.Second)) {
			_ = r.Repository.CaptureHealth(cam.ID, time.Now(), false, "stale_frame")
			continue
		}
		r.mu.Lock()
		if r.stopped[cam.ID] {
			r.mu.Unlock()
			continue
		}
		frame, err := domain.NewFrame(cam.ID, reg, at, data)
		if err == nil {
			err = r.Repository.Enqueue(frame, data)
		}
		r.mu.Unlock()
		if err != nil {
			_ = r.Repository.CaptureHealth(cam.ID, at, false, "storage_failed")
			r.Log.Error("frame persistence failed", "camera_id", cam.ID)
			continue
		}
		_ = r.Repository.CaptureHealth(cam.ID, at, true, "")
		if err = r.Repository.Prune(time.Now()); err != nil {
			r.Log.Error("queue capacity check failed")
		}
	}
}
func (r *Runner) Deliver(ctx context.Context, f domain.Frame) error {
	if r.gatewayID != "" && f.GatewayID != r.gatewayID {
		return &RemoteError{Status: 409, Code: "GATEWAY_ID_CHANGED"}
	}
	if f.State == domain.Queued || f.State == domain.PutPending {
		target, err := r.Cloud.Reserve(ctx, f)
		if err != nil {
			return err
		}
		if err = f.AssignTarget(target.Key); err != nil {
			return err
		}
		if err = r.Repository.Save(f); err != nil {
			return err
		}
		data, err := r.Repository.ReadImage(f)
		if err != nil {
			return err
		}
		if err = r.Cloud.Put(ctx, target, data); err != nil {
			return err
		}
		if err = f.MarkUploaded(); err != nil {
			return err
		}
		if err = r.Repository.Save(f); err != nil {
			return err
		}
	}
	receipt, err := r.Cloud.Commit(ctx, f)
	if err != nil {
		return err
	}
	if err = f.Acknowledge(receipt.ID); err != nil {
		return err
	}
	return r.Repository.Save(f)
}
func (r *Runner) upload(ctx context.Context) {
	for ctx.Err() == nil {
		if r.blocked.Load() {
			if !wait(ctx, time.Second) {
				return
			}
			continue
		}
		frame, attempt, ok, err := r.Repository.Claim(time.Now())
		if err != nil {
			r.Log.Error("queue read failed")
			if !wait(ctx, time.Second) {
				return
			}
			continue
		}
		if !ok {
			if !wait(ctx, 250*time.Millisecond) {
				return
			}
			continue
		}
		if r.stoppedCamera(frame.CameraID) {
			_ = r.Repository.Retry(frame.ID, attempt, time.Now(), true, "camera_disabled")
			continue
		}
		if time.Since(frame.CapturedAt) > time.Duration(r.Config.TTLSeconds)*time.Second {
			_ = frame.Discard("expired")
			_ = r.Repository.Save(frame)
			continue
		}
		err = r.Deliver(ctx, frame)
		if err == nil {
			_ = r.Repository.Retry(frame.ID, attempt, time.Now(), false, "")
			continue
		}
		attempt++
		delay := retryBackoff(attempt)
		permanent := false
		code := "delivery_failed"
		var remote *RemoteError
		if errors.As(err, &remote) {
			permanent = !remote.Temporary()
			code = "upload_failed"
			if remote.RetryAfter > delay {
				delay = remote.RetryAfter
			}
			if remote.Status == 401 && remote.Origin != "object" {
				permanent = false
				code = "gateway_auth_retrying"
				r.pauseAuthentication()
			}
			if remote.Status == 403 && remote.Origin != "object" {
				r.stopCamera(frame.CameraID)
				if remote.Code == "WARD_DELETED" || remote.Code == "WARD_DATA_ERASED" {
					_ = r.Repository.DropCamera(frame.CameraID, "ward_erased")
				}
			}
		}
		_ = r.Repository.Retry(frame.ID, attempt, time.Now().Add(delay), permanent, code)
		r.Log.Warn("frame delivery deferred", "camera_id", frame.CameraID, "frame_id", frame.ID, "blocked", permanent)
	}
}
func (r *Runner) register(ctx context.Context, cam CameraConfig) (domain.Registration, error) {
	for attempt := 1; ; attempt++ {
		reg, err := r.Cloud.Register(ctx, cam)
		var remote *RemoteError
		if !errors.As(err, &remote) || remote.Status != 401 || remote.Origin == "object" {
			return reg, err
		}
		_ = r.Repository.SetGatewayAuth("retrying")
		if attempt >= 3 {
			_ = r.Repository.SetGatewayAuth("required")
			return reg, ErrGatewayAuthentication
		}
		if !wait(ctx, retryBackoff(attempt)) {
			return reg, ctx.Err()
		}
	}
}
func (r *Runner) pauseAuthentication() {
	r.blocked.Store(true)
	_ = r.Repository.SetGatewayAuth("retrying")
	select {
	case r.authWake <- struct{}{}:
	default:
	}
}
func (r *Runner) heartbeat(ctx context.Context) {
	boot := domain.UUID()
	sequence := 0
	failures := 0
	unauthorized := 0
	for ctx.Err() == nil {
		health, err := r.Repository.Health()
		if err == nil {
			active := map[string]bool{}
			for _, c := range r.Config.Cameras {
				active[c.ID] = true
			}
			filtered := []CameraHealth{}
			for _, h := range health {
				if active[h.CameraID] && !r.stoppedCamera(h.CameraID) {
					filtered = append(filtered, h)
				}
			}
			sequence++
			err = r.Cloud.Heartbeat(ctx, boot, sequence, filtered)
		}
		delay := 60 * time.Second
		if err == nil {
			failures = 0
			unauthorized = 0
			_ = r.Repository.SetGatewayAuth("")
			r.blocked.Store(false)
		} else {
			failures++
			var remote *RemoteError
			if errors.As(err, &remote) && remote.Status == 401 && remote.Origin != "object" {
				unauthorized++
				r.blocked.Store(true)
				_ = r.Repository.SetGatewayAuth("retrying")
				if unauthorized >= 3 {
					_ = r.Repository.SetGatewayAuth("required")
					r.Log.Error("gateway authentication rejected repeatedly; update credentials and restart")
					select {
					case r.fatal <- ErrGatewayAuthentication:
					case <-ctx.Done():
					}
					return
				}
			} else {
				unauthorized = 0
			}
			if errors.As(err, &remote) && remote.Status == 403 {
				// Heartbeat may contain multiple cameras; revalidate to identify the revoked one.
				for _, cam := range r.Config.Cameras {
					if r.stoppedCamera(cam.ID) {
						continue
					}
					_, checkErr := r.Cloud.Register(ctx, cam)
					var denied *RemoteError
					if errors.As(checkErr, &denied) && denied.Status == 403 {
						r.stopCamera(cam.ID)
						if denied.Code == "WARD_DELETED" || denied.Code == "WARD_DATA_ERASED" {
							_ = r.Repository.DropCamera(cam.ID, "ward_erased")
						}
					}
				}
			}
			delay = retryBackoff(failures)
			r.Log.Warn("gateway heartbeat failed", "auth_paused", r.blocked.Load())
		}
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-r.authWake:
			timer.Stop()
		case <-timer.C:
		}
	}
}

func retryBackoff(attempt int) time.Duration {
	attempt = max(attempt, 1)
	base := min(time.Duration(1<<min(attempt-1, 6))*time.Second, 60*time.Second)
	return min(base+time.Duration(rand.Int64N(int64(base/4+1))), 60*time.Second)
}
