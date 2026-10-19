package main

import (
	"fmt"
	"net/http"
	"os"
	"time"
)

// probe implements `snaplink -healthcheck`. The final image is FROM scratch:
// there is no shell, curl or wget, so the binary checks itself. Used by the
// Dockerfile HEALTHCHECK and the compose healthcheck. Returns the exit code.
func probe(port string) int {
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://127.0.0.1:" + port + "/healthz")
	if err != nil {
		fmt.Fprintln(os.Stderr, "healthcheck:", err)
		return 1
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		fmt.Fprintln(os.Stderr, "healthcheck: status", resp.StatusCode)
		return 1
	}
	return 0
}
