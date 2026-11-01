package infrastructure

// A local RTSP/RTP fixture exercises the production FFmpeg arguments. It is not
// a camera compatibility claim and never contacts the household network.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"net"
	"net/textproto"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/johanchow/duxue/duxue-gateway/internal/application"
)

func annexBNALs(data []byte) [][]byte {
	result := [][]byte{}
	start := -1
	for i := 0; i < len(data); {
		width := 0
		if bytes.HasPrefix(data[i:], []byte{0, 0, 0, 1}) {
			width = 4
		} else if bytes.HasPrefix(data[i:], []byte{0, 0, 1}) {
			width = 3
		}
		if width > 0 {
			if start >= 0 && i > start {
				result = append(result, bytes.Clone(data[start:i]))
			}
			start = i + width
			i += width
		} else {
			i++
		}
	}
	if start >= 0 && start < len(data) {
		result = append(result, bytes.Clone(data[start:]))
	}
	return result
}
func syntheticRTSP(ctx context.Context, listener net.Listener, nals [][]byte, wg *sync.WaitGroup) {
	for {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		wg.Add(1)
		go func() { defer wg.Done(); serveSyntheticRTSP(ctx, conn, nals) }()
	}
}
func serveSyntheticRTSP(parent context.Context, conn net.Conn, nals [][]byte) {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	defer conn.Close()
	go func() { <-ctx.Done(); conn.Close() }()
	reader := textproto.NewReader(bufio.NewReader(conn))
	var writer sync.Mutex
	base := "rtsp://" + conn.LocalAddr().String() + "/stream/"
	var sps, pps []byte
	for _, nal := range nals {
		if nal[0]&31 == 7 {
			sps = nal
		}
		if nal[0]&31 == 8 {
			pps = nal
		}
	}
	sdp := fmt.Sprintf("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=duxue-synthetic\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\na=control:*\r\nm=video 0 RTP/AVP 96\r\na=rtpmap:96 H264/90000\r\na=fmtp:96 packetization-mode=1;sprop-parameter-sets=%s,%s\r\na=control:trackID=0\r\n", base64.StdEncoding.EncodeToString(sps), base64.StdEncoding.EncodeToString(pps))
	for {
		line, err := reader.ReadLine()
		if err != nil {
			return
		}
		headers, err := reader.ReadMIMEHeader()
		if err != nil {
			return
		}
		method, _, _ := strings.Cut(line, " ")
		body := ""
		extra := ""
		switch method {
		case "OPTIONS":
			extra = "Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN\r\n"
		case "DESCRIBE":
			body = sdp
			extra = "Content-Type: application/sdp\r\nContent-Base: " + base + "\r\n"
		case "SETUP":
			extra = "Session: 12345678;timeout=60\r\nTransport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n"
		case "PLAY":
			extra = "Session: 12345678\r\nRTP-Info: url=" + base + "trackID=0;seq=1;rtptime=0\r\n"
		case "TEARDOWN":
			return
		default:
			return
		}
		writer.Lock()
		_, err = fmt.Fprintf(conn, "RTSP/1.0 200 OK\r\nCSeq: %s\r\n%sContent-Length: %d\r\n\r\n%s", headers.Get("Cseq"), extra, len(body), body)
		writer.Unlock()
		if err != nil {
			return
		}
		if method == "PLAY" {
			go sendSyntheticRTP(ctx, conn, &writer, nals)
		}
	}
}
func sendSyntheticRTP(ctx context.Context, conn net.Conn, writer *sync.Mutex, nals [][]byte) {
	seq := uint16(1)
	timestamp := uint32(0)
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	for ctx.Err() == nil {
		for _, nal := range nals {
			if len(nal) == 0 || len(nal) > 60000 {
				return
			}
			packet := make([]byte, 12+len(nal))
			packet[0] = 0x80
			packet[1] = 96
			picture := nal[0]&31 == 5 || nal[0]&31 == 1
			if picture {
				packet[1] |= 0x80
			}
			binary.BigEndian.PutUint16(packet[2:4], seq)
			seq++
			binary.BigEndian.PutUint32(packet[4:8], timestamp)
			binary.BigEndian.PutUint32(packet[8:12], 1234)
			copy(packet[12:], nal)
			frame := make([]byte, 4+len(packet))
			frame[0] = '$'
			frame[1] = 0
			binary.BigEndian.PutUint16(frame[2:4], uint16(len(packet)))
			copy(frame[4:], packet)
			writer.Lock()
			_, err := conn.Write(frame)
			writer.Unlock()
			if err != nil {
				return
			}
			if picture {
				timestamp += 22500
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
				}
			}
		}
	}
}
func TestRTSPProductionAdapterDecodesSyntheticH264(t *testing.T) {
	ffmpeg, err := exec.LookPath("ffmpeg")
	if err != nil {
		t.Skip("FFmpeg required")
	}
	video, err := exec.Command(ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=4", "-frames:v", "2", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "1", "-threads", "1", "-f", "h264", "pipe:1").Output()
	if err != nil {
		t.Fatal("cannot generate H.264 fixture", err)
	}
	nals := annexBNALs(video)
	if len(nals) < 4 {
		t.Fatal("missing H.264 parameter sets")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 9*time.Second)
	defer cancel()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	var sessions sync.WaitGroup
	acceptDone := make(chan struct{})
	go func() { defer close(acceptDone); syntheticRTSP(ctx, listener, nals, &sessions) }()
	defer func() { cancel(); listener.Close(); <-acceptDone; sessions.Wait() }()
	source, err := SourceFactory(ffmpeg)(ctx, application.CameraConfig{Source: application.SourceConfig{Kind: "rtsp", URL: "rtsp://" + listener.Addr().String() + "/stream"}})
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	for ctx.Err() == nil {
		image, at, err := source.Latest(ctx)
		if err == nil {
			if len(image) < 4 || image[0] != 255 || image[1] != 216 || time.Since(at) > time.Second {
				t.Fatal("invalid RTSP JPEG")
			}
			return
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatal("production RTSP adapter produced no fresh JPEG")
}
