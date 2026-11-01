package application

import (
	"testing"
	"time"
)

func TestRetryBackoffIsBoundedEvenAfterManyFailures(t *testing.T) {
	for _, attempt := range []int{0, 1, 2, 10, 1000000000} {
		for range 100 {
			delay := retryBackoff(attempt)
			if delay < time.Second || delay > 60*time.Second {
				t.Fatalf("retry busy loop or excessive delay: attempt=%d delay=%s", attempt, delay)
			}
			if attempt <= 1 && delay > 1250*time.Millisecond {
				t.Fatal("first failure did not start at one second")
			}
		}
	}
}
