package infrastructure

import (
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"go.yaml.in/yaml/v3"
)

var identifier = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)
var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
var envName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

func LoadConfig(path string, requireSecrets ...bool) (application.Config, error) {
	secretsRequired := len(requireSecrets) == 0 || requireSecrets[0]
	c := application.Config{IntervalSeconds: 15, FFmpeg: "ffmpeg", MaxFrames: 2000, MaxBytes: 1_000_000_000, TTLSeconds: 43200, MinFreeBytes: 100_000_000}
	f, err := os.Open(path)
	if err != nil {
		return c, errors.New("cannot read configuration file")
	}
	defer f.Close()
	decoder := yaml.NewDecoder(io.LimitReader(f, 1<<20))
	decoder.KnownFields(true)
	if err = decoder.Decode(&c); err != nil {
		return c, errors.New("invalid YAML configuration or unknown field")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return c, errors.New("configuration must contain one YAML document")
	}
	u, err := url.Parse(c.APIBaseURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "https" && !(u.Scheme == "http" && (u.Hostname() == "localhost" || u.Hostname() == "127.0.0.1" || u.Hostname() == "::1"))) {
		return c, errors.New("API must use HTTPS (HTTP only on loopback)")
	}
	if !envName.MatchString(c.TokenEnv) || (secretsRequired && os.Getenv(c.TokenEnv) == "") {
		return c, errors.New("gateway credential environment variable is missing")
	}
	if c.StateDir == "" || c.IntervalSeconds < 1 || c.IntervalSeconds > 3600 || c.MaxFrames < 1 || c.MaxBytes < 1 || c.TTLSeconds < 1 || c.TTLSeconds > 43200 || c.FFmpeg == "" || len(c.Cameras) == 0 || len(c.Cameras) > 64 {
		return c, errors.New("invalid runtime limits or camera list")
	}
	if !filepath.IsAbs(c.StateDir) {
		c.StateDir = filepath.Join(filepath.Dir(path), c.StateDir)
	}
	c.StateDir, err = filepath.Abs(c.StateDir)
	if err != nil {
		return c, errors.New("invalid state directory")
	}
	seen := map[string]bool{}
	for index, cam := range c.Cameras {
		c.Cameras[index].WardID = strings.ToLower(cam.WardID)
		if !identifier.MatchString(cam.ID) || seen[cam.ID] || !uuidPattern.MatchString(cam.WardID) {
			return c, errors.New("camera ID must be unique and Ward ID must be a UUID")
		}
		seen[cam.ID] = true
		u, err := url.Parse(cam.Source.URL)
		if err != nil || u.Host == "" || u.User != nil || (cam.Source.Kind != "rtsp" && cam.Source.Kind != "snapshot") || (cam.Source.Kind == "rtsp" && u.Scheme != "rtsp" && u.Scheme != "rtsps") || (cam.Source.Kind == "snapshot" && u.Scheme != "http" && u.Scheme != "https") {
			return c, fmt.Errorf("camera %s has invalid source configuration", cam.ID)
		}
		for _, name := range []string{cam.Source.UsernameEnv, cam.Source.PasswordEnv} {
			if name != "" && (!envName.MatchString(name) || (secretsRequired && os.Getenv(name) == "")) {
				return c, fmt.Errorf("camera %s credential environment variable is missing", cam.ID)
			}
		}
	}
	if strings.ContainsRune(c.FFmpeg, os.PathSeparator) && !filepath.IsAbs(c.FFmpeg) {
		c.FFmpeg = filepath.Join(filepath.Dir(path), c.FFmpeg)
	}
	c.APIBaseURL = strings.TrimRight(c.APIBaseURL, "/")
	return c, nil
}
