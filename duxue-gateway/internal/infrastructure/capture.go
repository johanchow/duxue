package infrastructure

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
)

type Snapshot struct {
	config application.SourceConfig
	client *http.Client
}

func (s *Snapshot) Latest(ctx context.Context) ([]byte, time.Time, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "GET", s.config.URL, nil)
	if err != nil {
		return nil, time.Time{}, errors.New("invalid snapshot request")
	}
	if s.config.UsernameEnv != "" {
		req.SetBasicAuth(os.Getenv(s.config.UsernameEnv), os.Getenv(s.config.PasswordEnv))
	}
	r, err := s.client.Do(req)
	if err != nil {
		return nil, time.Time{}, errors.New("snapshot unavailable")
	}
	defer r.Body.Close()
	if r.StatusCode != 200 {
		return nil, time.Time{}, errors.New("snapshot rejected")
	}
	data, err := io.ReadAll(io.LimitReader(r.Body, domain.MaxFrameBytes+1))
	if err != nil || len(data) > domain.MaxFrameBytes || !bytes.HasPrefix(data, []byte{255, 216}) || !bytes.HasSuffix(data, []byte{255, 217}) {
		return nil, time.Time{}, errors.New("invalid JPEG snapshot")
	}
	return data, time.Now().UTC(), nil
}
func (s *Snapshot) Close() error { s.client.CloseIdleConnections(); return nil }

type Stream struct {
	reconnects atomic.Int64
	mu         sync.RWMutex
	data       []byte
	at         time.Time
	lastRead   time.Time
	cancel     context.CancelFunc
	done       chan struct{}
}

func NewStream(ctx context.Context, binary string, arguments []string) *Stream {
	ctx, cancel := context.WithCancel(ctx)
	s := &Stream{cancel: cancel, done: make(chan struct{})}
	go s.loop(ctx, binary, arguments)
	return s
}
func splitJPEG(data []byte, atEOF bool) (int, []byte, error) {
	start := bytes.Index(data, []byte{255, 216})
	if start < 0 {
		if len(data) > domain.MaxFrameBytes {
			return 0, nil, errors.New("invalid JPEG stream")
		}
		return 0, nil, nil
	}
	end := bytes.Index(data[start+2:], []byte{255, 217})
	if end >= 0 {
		end += start + 4
		return end, data[start:end], nil
	}
	if atEOF && len(data) > 0 {
		return 0, nil, errors.New("incomplete JPEG stream")
	}
	return 0, nil, nil
}
func (s *Stream) loop(ctx context.Context, binary string, args []string) {
	defer close(s.done)
	delay := time.Second
	firstAttempt := true
	for ctx.Err() == nil {
		if !firstAttempt {
			s.reconnects.Add(1)
		}
		firstAttempt = false
		attempt, cancel := context.WithCancel(ctx)
		cmd := exec.CommandContext(attempt, binary, args...)
		cmd.Stderr = io.Discard
		cmd.WaitDelay = time.Second
		pipe, err := cmd.StdoutPipe()
		if err == nil {
			err = cmd.Start()
		}
		if err == nil {
			started := time.Now()
			watchDone := make(chan struct{})
			go func() {
				defer close(watchDone)
				tick := time.NewTicker(time.Second)
				defer tick.Stop()
				for {
					select {
					case <-attempt.Done():
						return
					case <-tick.C:
						s.mu.RLock()
						at := s.at
						s.mu.RUnlock()
						if at.Before(started) {
							at = started
						}
						if time.Since(at) > 10*time.Second {
							cancel()
							return
						}
					}
				}
			}()
			scanner := bufio.NewScanner(pipe)
			scanner.Buffer(make([]byte, 64*1024), domain.MaxFrameBytes+64*1024)
			scanner.Split(splitJPEG)
			for scanner.Scan() {
				if len(scanner.Bytes()) > domain.MaxFrameBytes {
					break
				}
				s.mu.Lock()
				s.data = bytes.Clone(scanner.Bytes())
				s.at = time.Now().UTC()
				s.mu.Unlock()
				delay = time.Second
			}
			cancel()
			_ = cmd.Wait()
			<-watchDone
		} else {
			cancel()
			if pipe != nil {
				_ = pipe.Close()
			}
		}
		s.mu.Lock()
		s.data = nil
		s.at = time.Time{}
		s.mu.Unlock()
		if !pause(ctx, delay) {
			return
		}
		delay = min(delay*2, 60*time.Second)
	}
}
func (s *Stream) Latest(ctx context.Context) ([]byte, time.Time, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.data) == 0 || time.Since(s.at) > 5*time.Second || !s.at.After(s.lastRead) {
		return nil, time.Time{}, errors.New("no fresh camera frame")
	}
	s.lastRead = s.at
	return bytes.Clone(s.data), s.at, nil
}
func (s *Stream) Close() error { s.cancel(); <-s.done; return nil }
func pause(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
func SourceFactory(binary string) application.SourceFactory {
	return func(ctx context.Context, c application.CameraConfig) (application.Source, error) {
		if c.Source.Kind == "snapshot" {
			return &Snapshot{config: c.Source, client: &http.Client{Transport: &http.Transport{Proxy: nil}, Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
		}
		if _, err := exec.LookPath(binary); err != nil {
			return nil, errors.New("FFmpeg executable not found")
		}
		u, err := url.Parse(c.Source.URL)
		if err != nil {
			return nil, errors.New("invalid RTSP address")
		}
		if c.Source.UsernameEnv != "" {
			u.User = url.UserPassword(os.Getenv(c.Source.UsernameEnv), os.Getenv(c.Source.PasswordEnv))
		}
		args := []string{"-hide_banner", "-loglevel", "error", "-nostdin", "-rtsp_transport", "tcp", "-timeout", "5000000", "-i", u.String(), "-map", "0:v:0", "-an", "-vf", "scale=640:-2,fps=2", "-q:v", "5", "-c:v", "mjpeg", "-f", "image2pipe", "pipe:1"}
		return NewStream(ctx, binary, args), nil
	}
}

func (s *Stream) Reconnects() int64 { return s.reconnects.Load() }
