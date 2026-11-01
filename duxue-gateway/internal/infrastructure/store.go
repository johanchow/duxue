package infrastructure

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"syscall"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
	"github.com/johanchow/duxue/duxue-gateway/internal/domain"
	_ "modernc.org/sqlite"
)

type Store struct {
	db     *sql.DB
	root   string
	config application.Config
	lock   *os.File
	mu     sync.Mutex
	cursor int
	quotas map[string]int
}

func OpenStore(c application.Config, readOnly bool) (*Store, error) {
	s := &Store{root: c.StateDir, config: c, quotas: map[string]int{}}
	fail := func(err error) (*Store, error) { s.Close(); return nil, err }
	if !readOnly {
		if err := os.MkdirAll(filepath.Join(c.StateDir, "frames"), 0700); err != nil {
			return nil, err
		}
		_ = os.Chmod(c.StateDir, 0700)
		var err error
		s.lock, err = os.OpenFile(filepath.Join(c.StateDir, "instance.lock"), os.O_CREATE|os.O_RDWR, 0600)
		if err != nil {
			return fail(err)
		}
		if err = syscall.Flock(int(s.lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
			return fail(errors.New("another gateway owns state directory"))
		}
	}
	u := url.URL{Scheme: "file", Path: filepath.Join(c.StateDir, "queue.db")}
	q := u.Query()
	q.Add("_pragma", "busy_timeout(5000)")
	if readOnly {
		q.Set("mode", "ro")
	} else {
		q.Add("_pragma", "journal_mode(WAL)")
		q.Add("_pragma", "synchronous(FULL)")
		q.Add("_pragma", "foreign_keys(ON)")
	}
	u.RawQuery = q.Encode()
	var err error
	s.db, err = sql.Open("sqlite", u.String())
	if err != nil {
		return fail(err)
	}
	s.db.SetMaxOpenConns(1)
	var schemaVersion int
	if err = s.db.QueryRow("PRAGMA user_version").Scan(&schemaVersion); err != nil {
		return fail(err)
	}
	if schemaVersion > 2 {
		return fail(errors.New("queue schema is newer than this gateway; do not downgrade"))
	}
	if !readOnly {
		_, err = s.db.Exec(`CREATE TABLE IF NOT EXISTS frames(id TEXT PRIMARY KEY,camera TEXT NOT NULL,captured INTEGER NOT NULL,state TEXT NOT NULL,body BLOB NOT NULL,size INTEGER NOT NULL,next_attempt INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,lease INTEGER NOT NULL DEFAULT 0,blocked INTEGER NOT NULL DEFAULT 0,UNIQUE(camera,captured));
CREATE INDEX IF NOT EXISTS frames_pending ON frames(state,next_attempt,captured);
CREATE TABLE IF NOT EXISTS registrations(camera TEXT PRIMARY KEY,body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS health(camera TEXT PRIMARY KEY,captured TEXT,submitted TEXT,dropped INTEGER NOT NULL DEFAULT 0,gaps INTEGER NOT NULL DEFAULT 0,capture_count INTEGER NOT NULL DEFAULT 0,reconnects INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',upload_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS domain_events(id INTEGER PRIMARY KEY,frame_id TEXT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,event_type TEXT NOT NULL,occurred INTEGER NOT NULL);`)
		if err != nil {
			return fail(err)
		}
		if schemaVersion < 2 {
			_, err = s.db.Exec(`BEGIN;
ALTER TABLE health ADD COLUMN capture_detail TEXT NOT NULL DEFAULT '';
ALTER TABLE health ADD COLUMN gateway_auth TEXT NOT NULL DEFAULT '';
CREATE TABLE recovery_losses(id TEXT PRIMARY KEY,camera TEXT,reason TEXT NOT NULL,occurred INTEGER NOT NULL);
PRAGMA user_version=2; COMMIT;`)
			if err != nil {
				return fail(err)
			}
		}
		if err = os.Chmod(filepath.Join(c.StateDir, "queue.db"), 0600); err != nil {
			return fail(err)
		}
	}
	return s, nil
}
func (s *Store) Close() error {
	if s.db != nil {
		_ = s.db.Close()
	}
	if s.lock != nil {
		_ = syscall.Flock(int(s.lock.Fd()), syscall.LOCK_UN)
		_ = s.lock.Close()
	}
	return nil
}
func (s *Store) Registration(camera string) (domain.Registration, error) {
	var r domain.Registration
	var b []byte
	err := s.db.QueryRow("SELECT body FROM registrations WHERE camera=?", camera).Scan(&b)
	if err != nil {
		return r, err
	}
	err = json.Unmarshal(b, &r)
	return r, err
}
func (s *Store) Register(camera string, r domain.Registration) error {
	old, err := s.Registration(camera)
	if err == nil && old != r {
		return errors.New("persisted camera assignment differs; use a new camera ID")
	}
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	b, _ := json.Marshal(r)
	_, err = s.db.Exec("INSERT INTO registrations(camera,body) VALUES(?,?) ON CONFLICT(camera) DO NOTHING", camera, b)
	if err != nil {
		return err
	}
	_, err = s.db.Exec("INSERT OR IGNORE INTO health(camera) VALUES(?)", camera)
	return err
}
func syncWrite(path string, b []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	_, err = f.Write(b)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}
func syncDir(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}
func (s *Store) bundle(id string) string { return filepath.Join(s.root, "frames", id) }
func (s *Store) Enqueue(f domain.Frame, image []byte) error {
	if !uuidPattern.MatchString(f.ID) {
		return errors.New("invalid frame ID")
	}
	var disk syscall.Statfs_t
	if err := syscall.Statfs(s.root, &disk); err != nil {
		return err
	}
	if disk.Bavail*uint64(disk.Bsize) < s.config.MinFreeBytes+uint64(len(image)) {
		return errors.New("insufficient free disk")
	}
	if f.SizeBytes != len(image) {
		return errors.New("evidence length differs")
	}
	dir := s.bundle(f.ID)
	temp, err := os.MkdirTemp(filepath.Join(s.root, "frames"), ".tmp-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(temp)
	b, err := json.Marshal(f)
	if err != nil {
		return err
	}
	if err = syncWrite(filepath.Join(temp, "image.jpg"), image); err != nil {
		return err
	}
	if err = syncWrite(filepath.Join(temp, "manifest.json"), b); err != nil {
		return err
	}
	if err = syncDir(temp); err != nil {
		return err
	}
	if err = os.Rename(temp, dir); err != nil {
		return err
	}
	if err = syncDir(filepath.Dir(dir)); err != nil {
		return err
	}
	return s.Save(f)
}
func (s *Store) Save(f domain.Frame) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.save(f)
}
func (s *Store) save(f domain.Frame) error {
	b, err := json.Marshal(f)
	if err != nil {
		return err
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var previous []byte
	err = tx.QueryRow("SELECT body FROM frames WHERE id=?", f.ID).Scan(&previous)
	event := ""
	if errors.Is(err, sql.ErrNoRows) {
		event = "FrameQueued"
	} else if err != nil {
		return err
	} else {
		var old domain.Frame
		if err = json.Unmarshal(previous, &old); err != nil {
			return err
		}
		if old.ID != f.ID || old.Registration != f.Registration || old.CameraID != f.CameraID || old.CapturedAt != f.CapturedAt || old.SHA256 != f.SHA256 || old.SizeBytes != f.SizeBytes || (old.ObjectKey != "" && old.ObjectKey != f.ObjectKey) {
			return errors.New("immutable evidence changed")
		}
		if old.Terminal() && old.State != f.State {
			return errors.New("terminal evidence cannot be revived")
		}
		if old.State != f.State {
			if f.State == domain.Delivered {
				event = "FrameDelivered"
			}
			if f.State == domain.Discarded {
				event = "FrameDiscarded"
			}
		}
	}
	_, err = tx.Exec(`INSERT INTO frames(id,camera,captured,state,body,size) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,body=excluded.body`, f.ID, f.CameraID, f.CapturedAt.UnixNano(), f.State, b, f.SizeBytes)
	if err != nil {
		return err
	}
	if event != "" {
		if _, err = tx.Exec("INSERT INTO domain_events(frame_id,event_type,occurred) VALUES(?,?,?)", f.ID, event, time.Now().Unix()); err != nil {
			return err
		}
	}
	if event == "FrameDelivered" {
		_, err = tx.Exec("UPDATE health SET submitted=?,upload_error='' WHERE camera=?", time.Now().UTC().Format(time.RFC3339Nano), f.CameraID)
	}
	if event == "FrameDiscarded" {
		_, err = tx.Exec("UPDATE health SET dropped=dropped+1,error=? WHERE camera=?", f.Reason, f.CameraID)
	}
	if err != nil {
		return err
	}
	if err = tx.Commit(); err != nil {
		return err
	}
	if f.Terminal() {
		return os.RemoveAll(s.bundle(f.ID))
	}
	return nil
}
func (s *Store) Claim(at time.Time) (domain.Frame, int, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var f domain.Frame
	rows, err := s.db.Query(`SELECT DISTINCT camera FROM frames WHERE state IN ('queued','put_pending','uploaded') AND blocked=0 AND lease<? AND next_attempt<=? ORDER BY camera`, at.Unix(), at.Unix())
	if err != nil {
		return f, 0, false, err
	}
	cameras := []string{}
	for rows.Next() {
		var c string
		if err = rows.Scan(&c); err != nil {
			rows.Close()
			return f, 0, false, err
		}
		cameras = append(cameras, c)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return f, 0, false, err
	}
	if len(cameras) == 0 {
		return f, 0, false, nil
	}
	camera := cameras[s.cursor%len(cameras)]
	s.cursor++
	order := "ASC"
	if s.quotas[camera]%4 == 0 {
		order = "DESC"
	}
	s.quotas[camera]++
	var b []byte
	attempt := 0
	err = s.db.QueryRow("SELECT body,attempts FROM frames WHERE camera=? AND state IN ('queued','put_pending','uploaded') AND blocked=0 AND lease<? AND next_attempt<=? ORDER BY captured "+order+" LIMIT 1", camera, at.Unix(), at.Unix()).Scan(&b, &attempt)
	if errors.Is(err, sql.ErrNoRows) {
		return f, 0, false, nil
	}
	if err != nil {
		return f, 0, false, err
	}
	if err = json.Unmarshal(b, &f); err != nil {
		return f, 0, false, err
	}
	_, err = s.db.Exec("UPDATE frames SET lease=? WHERE id=?", at.Add(2*time.Minute).Unix(), f.ID)
	return f, attempt, true, err
}
func (s *Store) Retry(id string, attempt int, next time.Time, blocked bool, reason string) error {
	_, err := s.db.Exec("UPDATE frames SET lease=0,attempts=?,next_attempt=?,blocked=? WHERE id=?", attempt, next.Unix(), blocked, id)
	if err != nil {
		return err
	}
	if reason != "" {
		_, err = s.db.Exec("UPDATE health SET upload_error=? WHERE camera=(SELECT camera FROM frames WHERE id=?)", reason, id)
	}
	return err
}
func (s *Store) ReadImage(f domain.Frame) ([]byte, error) {
	if !uuidPattern.MatchString(f.ID) {
		return nil, errors.New("invalid frame ID")
	}
	file, err := os.Open(filepath.Join(s.bundle(f.ID), "image.jpg"))
	if err != nil {
		return nil, errors.New("image missing")
	}
	defer file.Close()
	b, err := io.ReadAll(io.LimitReader(file, domain.MaxFrameBytes+1))
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(b)
	if len(b) != f.SizeBytes || hex.EncodeToString(sum[:]) != f.SHA256 {
		return nil, errors.New("image integrity failed")
	}
	return b, nil
}
func (s *Store) Recover(at time.Time) error {
	if _, err := s.db.Exec("UPDATE frames SET lease=0,blocked=0,next_attempt=0"); err != nil {
		return err
	}
	entries, err := os.ReadDir(filepath.Join(s.root, "frames"))
	if err != nil {
		return err
	}
	for _, entry := range entries {
		path := filepath.Join(s.root, "frames", entry.Name())
		if !uuidPattern.MatchString(entry.Name()) {
			if err = os.RemoveAll(path); err != nil {
				return err
			}
			continue
		}
		var state string
		err = s.db.QueryRow("SELECT state FROM frames WHERE id=?", entry.Name()).Scan(&state)
		if err == nil {
			if state == string(domain.Delivered) || state == string(domain.Discarded) {
				if err = os.RemoveAll(path); err != nil {
					return err
				}
			}
			continue
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		file, openErr := os.Open(filepath.Join(path, "manifest.json"))
		var b []byte
		if openErr == nil {
			b, openErr = io.ReadAll(io.LimitReader(file, 65537))
			_ = file.Close()
		}
		if openErr != nil {
			if err = s.discardOrphan(entry.Name(), "manifest_unreadable", at); err != nil {
				return err
			}
			continue
		}
		var f domain.Frame
		if len(b) > 65536 || json.Unmarshal(b, &f) != nil || f.ID != entry.Name() {
			if err = s.discardOrphan(entry.Name(), "manifest_corrupt", at); err != nil {
				return err
			}
			continue
		}
		r, err := s.Registration(f.CameraID)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		if err != nil || r != f.Registration {
			if err = s.discardOrphan(entry.Name(), "assignment_unknown", at); err != nil {
				return err
			}
			continue
		}
		if err = s.Save(f); err != nil {
			return err
		}
	}
	rows, err := s.db.Query("SELECT body FROM frames WHERE state IN ('queued','put_pending','uploaded')")
	if err != nil {
		return err
	}
	frames := []domain.Frame{}
	for rows.Next() {
		var b []byte
		if err = rows.Scan(&b); err != nil {
			break
		}
		var f domain.Frame
		if err = json.Unmarshal(b, &f); err != nil {
			break
		}
		frames = append(frames, f)
	}
	rowErr := rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	if rowErr != nil {
		return rowErr
	}
	for _, f := range frames {
		if _, err = s.ReadImage(f); err != nil {
			_ = f.Discard("image_corrupt")
			if err = s.Save(f); err != nil {
				return err
			}
		}
	}
	return s.Prune(at)
}
func (s *Store) Prune(at time.Time) error {
	if _, err := s.db.Exec("DELETE FROM recovery_losses WHERE occurred<?", at.Add(-24*time.Hour).Unix()); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	rows, err := s.db.Query("SELECT body,lease FROM frames WHERE state IN ('queued','put_pending','uploaded') ORDER BY captured")
	if err != nil {
		return err
	}
	type item struct {
		f     domain.Frame
		lease int64
	}
	all := []item{}
	counts := map[string]int{}
	var total int64
	for rows.Next() {
		var b []byte
		var it item
		if err = rows.Scan(&b, &it.lease); err != nil {
			break
		}
		if err = json.Unmarshal(b, &it.f); err != nil {
			break
		}
		all = append(all, it)
		counts[it.f.CameraID]++
		total += int64(it.f.SizeBytes)
	}
	rowErr := rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	if rowErr != nil {
		return rowErr
	}
	for _, it := range all {
		f := it.f
		expired := at.Sub(f.CapturedAt) > time.Duration(s.config.TTLSeconds)*time.Second
		if it.lease >= at.Unix() {
			continue
		}
		if expired || counts[f.CameraID] > s.config.MaxFrames || total > s.config.MaxBytes {
			reason := "capacity"
			if expired {
				reason = "expired"
			}
			if err = f.Discard(reason); err != nil {
				return err
			}
			if err = s.save(f); err != nil {
				return err
			}
			total -= int64(f.SizeBytes)
			counts[f.CameraID]--
		}
	}
	_, err = s.db.Exec("DELETE FROM frames WHERE state IN ('delivered','discarded') AND captured<?", at.Add(-24*time.Hour).UnixNano())
	return err
}
func (s *Store) CaptureHealth(camera string, at time.Time, success bool, reason string) error {
	if success {
		_, err := s.db.Exec("UPDATE health SET captured=?,capture_count=capture_count+1,error='',capture_detail='' WHERE camera=?", at.UTC().Format(time.RFC3339Nano), camera)
		return err
	}
	_, err := s.db.Exec("UPDATE health SET gaps=gaps+1,error=? WHERE camera=?", reason, camera)
	return err
}
func (s *Store) Health() ([]application.CameraHealth, error) {
	rows, err := s.db.Query(`SELECT h.camera,h.captured,h.submitted,h.dropped,h.gaps,h.capture_count,h.reconnects,CASE WHEN h.gateway_auth!='' THEN 'gateway_auth_'||h.gateway_auth WHEN h.error!='' THEN h.error ELSE h.upload_error END,COALESCE(p.count,0),COALESCE(p.bytes,0),h.gateway_auth,h.capture_detail,(SELECT count(*) FROM recovery_losses WHERE camera IS NULL) FROM health h LEFT JOIN (SELECT camera,count(*) AS count,sum(size) AS bytes FROM frames WHERE state IN ('queued','put_pending','uploaded') GROUP BY camera) p ON p.camera=h.camera ORDER BY h.camera`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	health := []application.CameraHealth{}
	for rows.Next() {
		var h application.CameraHealth
		var capture, submit sql.NullString
		if err = rows.Scan(&h.CameraID, &capture, &submit, &h.Dropped, &h.Gaps, &h.CapturedCount, &h.Reconnects, &h.Error, &h.QueueFrames, &h.QueueBytes, &h.GatewayAuth, &h.CaptureDetail, &h.UnattributedLosses); err != nil {
			return nil, err
		}
		if capture.Valid {
			t, err := time.Parse(time.RFC3339Nano, capture.String)
			if err != nil {
				return nil, err
			}
			h.LastCapture = &t
		}
		if submit.Valid {
			t, err := time.Parse(time.RFC3339Nano, submit.String)
			if err != nil {
				return nil, err
			}
			h.LastSubmit = &t
		}
		health = append(health, h)
	}
	return health, rows.Err()
}
func (s *Store) DropCamera(camera, reason string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	rows, err := s.db.Query("SELECT body FROM frames WHERE camera=? AND state IN ('queued','put_pending','uploaded')", camera)
	if err != nil {
		return err
	}
	frames := []domain.Frame{}
	for rows.Next() {
		var b []byte
		if err = rows.Scan(&b); err != nil {
			break
		}
		var f domain.Frame
		if err = json.Unmarshal(b, &f); err != nil {
			break
		}
		frames = append(frames, f)
	}
	rowErr := rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	if rowErr != nil {
		return rowErr
	}
	sort.Slice(frames, func(i, j int) bool { return frames[i].ID < frames[j].ID })
	for _, f := range frames {
		if err = f.Discard(reason); err != nil {
			return err
		}
		if err = s.save(f); err != nil {
			return err
		}
	}
	return nil
}
func (s *Store) String() string { return fmt.Sprintf("gateway queue at %s", s.root) }

func (s *Store) AddDiagnostics(camera string, gaps int, reconnects int64) error {
	_, err := s.db.Exec("UPDATE health SET gaps=gaps+?,reconnects=reconnects+? WHERE camera=?", gaps, reconnects, camera)
	return err
}

// Corrupt orphan metadata has no trustworthy camera identity. Keep a durable,
// idempotent loss marker before deleting bytes; never invent Ward attribution.
func (s *Store) discardOrphan(id, reason string, at time.Time) error {
	if _, err := s.db.Exec("INSERT OR IGNORE INTO recovery_losses(id,reason,occurred) VALUES(?,?,?)", id, reason, at.Unix()); err != nil {
		return err
	}
	slog.Warn("unattributed frame discarded during recovery", "frame_id", id, "reason", reason)
	return os.RemoveAll(s.bundle(id))
}
func (s *Store) CaptureDiagnostic(camera, detail string) error {
	_, err := s.db.Exec("UPDATE health SET capture_detail=? WHERE camera=?", detail, camera)
	return err
}
func (s *Store) SetGatewayAuth(state string) error {
	_, err := s.db.Exec("UPDATE health SET gateway_auth=?", state)
	return err
}
