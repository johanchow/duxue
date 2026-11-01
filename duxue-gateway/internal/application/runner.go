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

type Runner struct {
	Config     Config
	Repository Repository
	Cloud      Cloud
	Sources    SourceFactory
	Log        *slog.Logger
	blocked    atomic.Bool
	mu         sync.Mutex
	stopped    map[string]bool
	gatewayID  string
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
func (r *Runner) stopCamera(id string) { r.mu.Lock(); defer r.mu.Unlock(); r.stopped[id] = true }
func (r *Runner) Run(parent context.Context) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	if r.Log == nil {
		r.Log = slog.Default()
	}
	r.stopped = map[string]bool{}
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
		reg, err := r.Cloud.Register(ctx, cam)
		if err != nil {
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
	var wg sync.WaitGroup
	start := func(f func()) { wg.Add(1); go func() { defer wg.Done(); f() }() }
	for _, cam := range r.Config.Cameras {
		if r.stoppedCamera(cam.ID) {
			continue
		}
		source, err := r.Sources(ctx, cam)
		if err != nil {
			cancel()
			wg.Wait()
			return err
		}
		start(func() { defer source.Close(); r.collect(ctx, cam, regs[cam.ID], source) })
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
	<-ctx.Done()
	wg.Wait()
	return nil
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
			continue
		}
		data, at, err := source.Latest(ctx)
		if err != nil {
			_ = r.Repository.CaptureHealth(cam.ID, time.Now(), false, "capture_failed")
			r.Log.Warn("camera capture failed", "camera_id", cam.ID)
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
				r.blocked.Store(true)
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
func (r *Runner) heartbeat(ctx context.Context) {
	boot := domain.UUID()
	sequence := 0
	for ctx.Err() == nil {
		if !r.blocked.Load() {
			health, err := r.Repository.Health()
			if err == nil {
				// Only active configuration is reported; removed sources may have historical queues.
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
				var remote *RemoteError
				if errors.As(err, &remote) && remote.Status == 401 {
					r.blocked.Store(true)
				}
			}
			if err != nil {
				r.Log.Warn("gateway heartbeat failed")
			}
		}
		if !wait(ctx, 60*time.Second) {
			return
		}
	}
}

func retryBackoff(attempt int) time.Duration {
	attempt = max(attempt, 1)
	base := min(time.Duration(1<<min(attempt-1, 6))*time.Second, 60*time.Second)
	return min(base+time.Duration(rand.Int64N(int64(base/4+1))), 60*time.Second)
}
