package infrastructure

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStrictConfigAndCredentialRedaction(t *testing.T) {
	t.Setenv("TEST_TOKEN", "cloud-secret")
	t.Setenv("CAM_USER", "local-user")
	t.Setenv("CAM_PASSWORD", "local-secret")
	base := `api_base_url: https://example.com/api/v1
api_token_env: TEST_TOKEN
state_dir: ./private
cameras:
 - camera_id: cam
   ward_id: 00000000-0000-4000-8000-000000000001
   source:
     kind: rtsp
     url: rtsp://192.168.1.50:554/stream
     username_env: CAM_USER
     password_env: CAM_PASSWORD
`
	path := filepath.Join(t.TempDir(), "config.yaml")
	for _, tc := range []struct {
		name, body string
		valid      bool
	}{
		{"valid", base, true},
		{"uppercase_uuid", strings.Replace(base, "00000000-0000-4000-8000-000000000001", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", 1), true},
		{"interval_overflow", base + "capture_interval_seconds: 9223372036854775807\n", false}, {"unknown", base + "unexpected: local-secret\n", false},
		{"insecure_cloud", strings.Replace(base, "https://example.com", "http://example.com", 1), false},
		{"inline_credentials", strings.Replace(base, "rtsp://192.168.1.50", "rtsp://local-user:local-secret@192.168.1.50", 1), false},
		{"duplicate", base + strings.Split(base, "cameras:\n")[1], false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := os.WriteFile(path, []byte(tc.body), 0600); err != nil {
				t.Fatal(err)
			}
			c, err := LoadConfig(path)
			if (err == nil) != tc.valid {
				t.Fatalf("validation result %v", err)
			}
			if err != nil && strings.Contains(err.Error(), "secret") {
				t.Fatal("secret disclosed")
			}
			if tc.valid && c.Cameras[0].WardID != strings.ToLower(c.Cameras[0].WardID) {
				t.Fatal("Ward UUID was not normalized")
			}
			if tc.valid && !filepath.IsAbs(c.StateDir) {
				t.Fatal("state path not resolved")
			}
		})
	}
}
