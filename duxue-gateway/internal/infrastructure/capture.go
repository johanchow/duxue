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
	"regexp"
	"strings"
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
	diagnostic *captureDiagnostic
	input      string
}

func NewStream(ctx context.Context, binary string, arguments []string) *Stream {
	ctx, cancel := context.WithCancel(ctx)
	return startStream(ctx, cancel, binary, arguments, "", nil)
}
func startStream(ctx context.Context, cancel context.CancelFunc, binary string, args []string, input string, secrets []string) *Stream {
	s := &Stream{cancel: cancel, done: make(chan struct{}), input: input, diagnostic: &captureDiagnostic{secrets: secrets}}
	go s.loop(ctx, binary, args)
	return s
}

// A bounded stderr tail is redacted before exposure, including URL and standalone credentials.
type captureDiagnostic struct {
	mu            sync.Mutex
	text, pending string
	oversized     bool
	secrets       []string
}

var cameraURL = regexp.MustCompile(`(?i)(?:rtsp|https?)://[^\s'"<>]+`)

func (d *captureDiagnostic) redact(text string) string {
	text = cameraURL.ReplaceAllString(text, "[camera-url]")
	for _, secret := range d.secrets {
		if secret != "" {
			text = strings.ReplaceAll(text, secret, "[redacted]")
			text = strings.ReplaceAll(text, url.QueryEscape(secret), "[redacted]")
			text = strings.ReplaceAll(text, url.PathEscape(secret), "[redacted]")
		}
	}
	return strings.Map(func(r rune) rune {
		if r < 32 && r != '\n' && r != '\t' {
			return -1
		}
		return r
	}, text)
}
func (d *captureDiagnostic) appendLine() {
	if !d.oversized {
		text := d.redact(d.pending)
		// Truncate only after redaction; never expose a fragment of a secret.
		if len(text) > 2048 {
			text = text[:2048]
		}
		d.text += "\n" + text
		if len(d.text) > 2048 {
			d.text = d.text[len(d.text)-2048:]
		}
	}
	d.pending = ""
	d.oversized = false
}
func (d *captureDiagnostic) Write(p []byte) (int, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	for _, c := range p {
		if c == '\n' {
			d.appendLine()
			continue
		}
		if d.oversized {
			continue
		}
		if len(d.pending) >= 4096 {
			d.pending = ""
			d.oversized = true
			continue
		}
		d.pending += string([]byte{c})
	}
	return len(p), nil
}
func (d *captureDiagnostic) Flush() {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.pending != "" || d.oversized {
		d.appendLine()
	}
}
func (d *captureDiagnostic) Text() string {
	d.mu.Lock()
	defer d.mu.Unlock()
	return strings.TrimSpace(d.text)
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
		cmd.Stderr = s.diagnostic
		// FFmpeg needs no application credentials or FFREPORT environment; an
		// allowlist also prevents inherited debug reporting from leaking URLs.
		cmd.Env = []string{}
		for _, key := range []string{"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"} {
			if value, ok := os.LookupEnv(key); ok {
				cmd.Env = append(cmd.Env, key+"="+value)
			}
		}
		var inputRead, inputWrite *os.File
		var writeDone chan struct{}
		var inputErr error
		if s.input != "" {
			inputRead, inputWrite, inputErr = os.Pipe()
			if inputErr == nil {
				cmd.ExtraFiles = []*os.File{inputRead}
				writeDone = make(chan struct{})
				go func() { defer close(writeDone); defer inputWrite.Close(); _, _ = io.WriteString(inputWrite, s.input) }()
			}
		}
		cmd.WaitDelay = time.Second
		pipe, err := cmd.StdoutPipe()
		if err == nil {
			err = inputErr
		}
		if err == nil {
			err = cmd.Start()
		}
		if inputRead != nil {
			_ = inputRead.Close()
		}
		if err != nil && inputWrite != nil {
			_ = inputWrite.Close()
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
			s.diagnostic.Flush()
			<-watchDone
		} else {
			cancel()
			if pipe != nil {
				_ = pipe.Close()
			}
		}
		if writeDone != nil {
			_ = inputWrite.Close()
			<-writeDone
		}
		if err != nil {
			_, _ = s.diagnostic.Write([]byte("FFmpeg could not start\n"))
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
		detail := s.diagnostic.Text()
		if detail != "" {
			return nil, time.Time{}, errors.New(detail)
		}
		return nil, time.Time{}, errors.New("no fresh camera frame; check camera connectivity and codec")
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
		// Single-input concat script carries the private URL over inherited FD3.
		// Its per-file RTSP options preserve TCP transport and read timeout.
		input := "ffconcat version 1.0\nfile '" + strings.ReplaceAll(u.String(), "'", "'\\''") + "'\noption rtsp_transport tcp\noption timeout 5000000\n"
		args := []string{"-hide_banner", "-loglevel", "error", "-nostdin", "-f", "concat", "-safe", "0", "-protocol_whitelist", "pipe,rtsp,tcp", "-i", "pipe:3", "-map", "0:v:0", "-an", "-vf", "scale=640:-2,fps=2", "-q:v", "5", "-c:v", "mjpeg", "-f", "image2pipe", "pipe:1"}
		childCtx, cancel := context.WithCancel(ctx)
		secrets := []string{u.String(), os.Getenv(c.Source.UsernameEnv), os.Getenv(c.Source.PasswordEnv)}
		for _, values := range u.Query() {
			secrets = append(secrets, values...)
		}
		return startStream(childCtx, cancel, binary, args, input, secrets), nil
	}
}

func (s *Stream) Reconnects() int64 { return s.reconnects.Load() }
