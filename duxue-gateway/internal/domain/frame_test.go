package domain

import (
	"testing"
	"time"
)

func TestDeliveryOnlyAcknowledgesUploadedEvidence(t *testing.T) {
	f, err := NewFrame("camera-01", Registration{GatewayID: "home", DeviceID: "device", WardID: "ward", Revision: 1}, time.Now().UTC(), []byte("jpeg"))
	if err != nil {
		t.Fatal(err)
	}
	if err = f.Acknowledge("accepted"); err == nil {
		t.Fatal("unuploaded frame was acknowledged")
	}
	if err = f.AssignTarget("ward/key.jpg"); err != nil {
		t.Fatal(err)
	}
	if err = f.AssignTarget("other/key.jpg"); err == nil {
		t.Fatal("retry changed object identity")
	}
	if err = f.MarkUploaded(); err != nil {
		t.Fatal(err)
	}
	if err = f.Acknowledge("accepted"); err != nil {
		t.Fatal(err)
	}
	if f.State != Delivered {
		t.Fatal(f.State)
	}
	if err = f.Discard("capacity"); err == nil {
		t.Fatal("delivered evidence discarded")
	}
}
