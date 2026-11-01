// Package domain owns evidence identity and delivery invariants, without IO.
package domain

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"time"
)

type State string

const (
	Queued        State = "queued"
	PutPending    State = "put_pending"
	Uploaded      State = "uploaded"
	Delivered     State = "delivered"
	Discarded     State = "discarded"
	MaxFrameBytes       = 1024 * 1024
)

type Registration struct {
	GatewayID string `json:"gateway_id"`
	DeviceID  string `json:"device_id"`
	WardID    string `json:"ward_id"`
	Revision  int    `json:"assignment_revision"`
}

type Frame struct {
	ID       string `json:"frame_id"`
	CameraID string `json:"camera_id"`
	Registration
	CapturedAt time.Time `json:"captured_at"`
	SHA256     string    `json:"sha256"`
	SizeBytes  int       `json:"size_bytes"`
	State      State     `json:"state"`
	ObjectKey  string    `json:"oss_key"`
	AcceptedID string    `json:"accepted_frame_id,omitempty"`
	Reason     string    `json:"reason,omitempty"`
}

func UUID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("system random source unavailable")
	}
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
}
func NewFrame(camera string, r Registration, at time.Time, data []byte) (Frame, error) {
	if camera == "" || r.GatewayID == "" || r.DeviceID == "" || r.WardID == "" || r.Revision < 1 || at.IsZero() || len(data) == 0 || len(data) > MaxFrameBytes {
		return Frame{}, errors.New("invalid evidence")
	}
	digest := sha256.Sum256(data)
	return Frame{ID: UUID(), CameraID: camera, Registration: r, CapturedAt: at.UTC(), SHA256: hex.EncodeToString(digest[:]), SizeBytes: len(data), State: Queued}, nil
}
func (f *Frame) AssignTarget(key string) error {
	if key == "" || (f.State != Queued && f.State != PutPending) || (f.ObjectKey != "" && f.ObjectKey != key) {
		return errors.New("upload target cannot change")
	}
	f.ObjectKey = key
	f.State = PutPending
	return nil
}
func (f *Frame) MarkUploaded() error {
	if f.State != PutPending || f.ObjectKey == "" {
		return errors.New("upload requires reserved target")
	}
	f.State = Uploaded
	return nil
}
func (f *Frame) Acknowledge(id string) error {
	if f.State != Uploaded || id == "" {
		return errors.New("delivery requires uploaded evidence and server receipt")
	}
	f.AcceptedID = id
	f.State = Delivered
	return nil
}
func (f *Frame) Discard(reason string) error {
	if f.Terminal() || reason == "" {
		return errors.New("invalid discard")
	}
	f.State = Discarded
	f.Reason = reason
	return nil
}
func (f Frame) Terminal() bool { return f.State == Delivered || f.State == Discarded }

// FrameDeliveryRepository is the write port for the local delivery aggregate.
type FrameDeliveryRepository interface{ Save(Frame) error }
