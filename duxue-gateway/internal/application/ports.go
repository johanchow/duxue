package application

import (
	"context"
	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
	"time"
)

type SourceConfig struct {
	Kind        string `yaml:"kind"`
	URL         string `yaml:"url"`
	UsernameEnv string `yaml:"username_env"`
	PasswordEnv string `yaml:"password_env"`
}
type CameraConfig struct {
	ID     string       `yaml:"camera_id"`
	WardID string       `yaml:"ward_id"`
	Source SourceConfig `yaml:"source"`
}
type Config struct {
	APIBaseURL      string         `yaml:"api_base_url"`
	TokenEnv        string         `yaml:"api_token_env"`
	StateDir        string         `yaml:"state_dir"`
	IntervalSeconds int            `yaml:"capture_interval_seconds"`
	FFmpeg          string         `yaml:"ffmpeg_path"`
	Cameras         []CameraConfig `yaml:"cameras"`
	MaxFrames       int            `yaml:"max_frames_per_camera"`
	MaxBytes        int64          `yaml:"max_cache_bytes"`
	TTLSeconds      int            `yaml:"cache_ttl_seconds"`
	MinFreeBytes    uint64         `yaml:"min_free_bytes"`
}
type CameraHealth struct {
	CapturedCount int        `json:"captured_frames"`
	Reconnects    int64      `json:"reconnects"`
	CameraID      string     `json:"camera_id"`
	LastCapture   *time.Time `json:"last_capture_at"`
	LastSubmit    *time.Time `json:"last_submit_at"`
	QueueFrames   int        `json:"queue_frames"`
	QueueBytes    int64      `json:"queue_bytes"`
	Dropped       int        `json:"dropped_count"`
	Gaps          int        `json:"capture_gaps"`
	Error         string     `json:"last_error_code,omitempty"`
}
type Target struct {
	Key       string            `json:"oss_key"`
	URL       string            `json:"upload_url"`
	Headers   map[string]string `json:"headers"`
	ExpiresAt time.Time         `json:"expires_at"`
}
type Receipt struct {
	ID      string `json:"id"`
	FrameID string `json:"frame_id"`
}
type Cloud interface {
	Register(context.Context, CameraConfig) (domain.Registration, error)
	Reserve(context.Context, domain.Frame) (Target, error)
	Put(context.Context, Target, []byte) error
	Commit(context.Context, domain.Frame) (Receipt, error)
	Heartbeat(context.Context, string, int, []CameraHealth) error
}
type Source interface {
	Latest(context.Context) ([]byte, time.Time, error)
	Close() error
}
type SourceFactory func(context.Context, CameraConfig) (Source, error)
type Repository interface {
	domain.FrameDeliveryRepository
	Registration(string) (domain.Registration, error)
	Register(string, domain.Registration) error
	Enqueue(domain.Frame, []byte) error
	Claim(time.Time) (domain.Frame, int, bool, error)
	ReadImage(domain.Frame) ([]byte, error)
	Retry(string, int, time.Time, bool, string) error
	Recover(time.Time) error
	Prune(time.Time) error
	Health() ([]CameraHealth, error)
	CaptureHealth(string, time.Time, bool, string) error
	AddDiagnostics(string, int, int64) error
	DropCamera(string, string) error
	Close() error
}
type RemoteError struct {
	Origin     string
	Status     int
	Code       string
	RetryAfter time.Duration
}

func (e *RemoteError) Error() string { return "remote request failed: " + e.Code }
func (e *RemoteError) Temporary() bool {
	return (e.Origin == "object" && (e.Status == 401 || e.Status == 403)) || e.Status == 0 || e.Status == 408 || e.Status == 429 || e.Status >= 500 || (e.Status == 422 && e.Code == "OBJECT_NOT_READY")
}
