// Command minibank runs the MiniBank ledger HTTP API.
//
//	STORE=memory go run ./cmd/minibank
//	STORE=postgres DATABASE_URL=postgres://... go run ./cmd/minibank
//	minibank -healthcheck   # exit 0 if http://127.0.0.1:$PORT/healthz is 200
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"minibank/internal/api"
	"minibank/internal/store"
)

const shutdownTimeout = 10 * time.Second

func main() {
	healthcheck := flag.Bool("healthcheck", false,
		"probe http://127.0.0.1:$PORT/healthz and exit 0 if healthy (Docker HEALTHCHECK on an image without curl)")
	flag.Parse()

	if *healthcheck {
		os.Exit(runHealthcheck(envOr(os.Getenv, "PORT", "8080")))
	}

	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := loadConfig(os.Getenv)
	if err != nil {
		// Fail fast with one clear line instead of starting half-configured.
		logger.Error("invalid configuration", "error", err)
		os.Exit(1)
	}
	if err := run(cfg, logger); err != nil {
		logger.Error("minibank stopped with an error", "error", err)
		os.Exit(1)
	}
	logger.Info("shutdown complete")
}

func run(cfg config, logger *slog.Logger) error {
	// ctx is cancelled on SIGINT (Ctrl+C) or SIGTERM (docker stop, Kubernetes).
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	st, err := openStore(ctx, cfg, logger)
	if err != nil {
		return err
	}
	defer func() {
		st.Close()
		logger.Info("store closed")
	}()

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           api.New(st, logger),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
		ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelWarn),
	}

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("minibank listening", "addr", srv.Addr, "store", cfg.Store)
		serveErr <- srv.ListenAndServe()
	}()

	select {
	case err := <-serveErr: // e.g. "address already in use"
		return fmt.Errorf("http server: %w", err)
	case <-ctx.Done():
	}
	stop() // a second Ctrl+C now kills the process immediately

	// Stop accepting new connections and let in-flight requests (for example
	// a transfer in the middle of its SQL transaction) finish.
	logger.Info("shutdown signal received, draining requests", "timeout", shutdownTimeout.String())
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("graceful shutdown: %w", err)
	}
	logger.Info("http server stopped")
	return nil
}

// openStore picks the Store from STORE. For Postgres it retries for about a
// minute: with `kubectl apply -f k8s/` the app and the database start at the
// same time and the database is usually not ready yet.
func openStore(ctx context.Context, cfg config, logger *slog.Logger) (store.Store, error) {
	if cfg.Store == "memory" {
		logger.Warn("using the in-memory store: data is lost on restart and not shared between replicas")
		return store.NewMemory(), nil
	}
	const attempts = 30
	for i := 1; ; i++ {
		attemptCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		pg, err := store.NewPostgres(attemptCtx, cfg.DatabaseURL)
		cancel()
		if err == nil {
			logger.Info("connected to postgres, schema ready")
			return pg, nil
		}
		if i == attempts || ctx.Err() != nil {
			return nil, fmt.Errorf("connect to postgres (%d attempts): %w", i, err)
		}
		logger.Warn("postgres not ready, retrying", "attempt", i, "error", err)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

// runHealthcheck lets the binary check itself: scratch/distroless images have
// no curl or wget for a Docker/Compose HEALTHCHECK.
func runHealthcheck(port string) int {
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://127.0.0.1:" + port + "/healthz")
	if err != nil {
		fmt.Fprintln(os.Stderr, "healthcheck:", err)
		return 1
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		fmt.Fprintln(os.Stderr, "healthcheck: status", resp.StatusCode)
		return 1
	}
	return 0
}
