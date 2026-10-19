// Command snaplink runs the SnapLink URL shortener HTTP service.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"

	"snaplink/internal/api"
	"snaplink/internal/store"
)

const shutdownTimeout = 10 * time.Second

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	cfg, err := loadConfig(os.Getenv)
	if err != nil {
		logger.Error("invalid configuration", "err", err)
		os.Exit(1)
	}
	if err := run(cfg, logger); err != nil {
		logger.Error("server stopped with error", "err", err)
		os.Exit(1)
	}
}

func run(cfg config, logger *slog.Logger) error {
	// ctx is cancelled on SIGINT (Ctrl+C) and SIGTERM (docker stop, kubectl).
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	st := openStore(ctx, cfg, logger)
	defer closeStore(st, logger)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           api.New(st, cfg.BaseURL, logger).Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		logger.Info("listening", "addr", srv.Addr, "store", cfg.Store, "base_url", cfg.BaseURL)
		errCh <- srv.ListenAndServe()
	}()

	select {
	case err := <-errCh: // e.g. port already in use
		return err
	case <-ctx.Done():
	}

	logger.Info("shutdown signal received, draining connections", "timeout", shutdownTimeout.String())
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("graceful shutdown: %w", err)
	}
	if err := <-errCh; err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	logger.Info("http server stopped")
	return nil
}

func openStore(ctx context.Context, cfg config, logger *slog.Logger) store.Store {
	if cfg.Store == "memory" {
		logger.Warn("using in-memory store: data is lost on restart and NOT shared between replicas")
		return store.NewMemory()
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:         cfg.RedisAddr,
		Password:     cfg.RedisPassword,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	st := store.NewRedis(rdb)

	// Not fatal on purpose: in compose/k8s Redis may come up after us.
	// /readyz answers 503 until Redis responds, so no traffic is routed here.
	pingCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	if err := st.Ping(pingCtx); err != nil {
		logger.Warn("redis not reachable yet, /readyz will report 503", "addr", cfg.RedisAddr, "err", err)
	} else {
		logger.Info("connected to redis", "addr", cfg.RedisAddr)
	}
	return st
}

func closeStore(st store.Store, logger *slog.Logger) {
	c, ok := st.(io.Closer)
	if !ok {
		return
	}
	if err := c.Close(); err != nil {
		logger.Error("closing store", "err", err)
		return
	}
	logger.Info("store closed")
}
