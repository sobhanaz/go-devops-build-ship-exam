package main

import (
	"errors"
	"fmt"
	"strconv"
)

// config is read from environment variables only (12-factor). Secrets such
// as the database password arrive inside DATABASE_URL and are never logged.
type config struct {
	Port        string // PORT, default 8080
	Store       string // STORE: "postgres" (default) or "memory"
	DatabaseURL string // DATABASE_URL, required when STORE=postgres
}

// loadConfig takes getenv as a parameter so tests do not touch the real
// environment.
func loadConfig(getenv func(string) string) (config, error) {
	cfg := config{
		Port:        envOr(getenv, "PORT", "8080"),
		Store:       envOr(getenv, "STORE", "postgres"),
		DatabaseURL: getenv("DATABASE_URL"),
	}
	if n, err := strconv.Atoi(cfg.Port); err != nil || n < 1 || n > 65535 {
		return cfg, fmt.Errorf("PORT must be a number between 1 and 65535, got %q", cfg.Port)
	}
	switch cfg.Store {
	case "memory":
	case "postgres":
		if cfg.DatabaseURL == "" {
			return cfg, errors.New("DATABASE_URL is required when STORE=postgres")
		}
	default:
		return cfg, fmt.Errorf(`STORE must be "memory" or "postgres", got %q`, cfg.Store)
	}
	return cfg, nil
}

func envOr(getenv func(string) string, key, fallback string) string {
	if v := getenv(key); v != "" {
		return v
	}
	return fallback
}
