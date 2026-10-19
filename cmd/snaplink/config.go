package main

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

// config is everything the service reads from the environment.
type config struct {
	Port          string
	Store         string // "redis" or "memory"
	RedisAddr     string
	RedisPassword string
	BaseURL       string
}

// loadConfig reads the env (getenv is injected so tests need no t.Setenv
// juggling) and fails fast on values that cannot work.
func loadConfig(getenv func(string) string) (config, error) {
	cfg := config{
		Port:          envOr(getenv, "PORT", "8080"),
		Store:         strings.ToLower(envOr(getenv, "STORE", "redis")),
		RedisAddr:     envOr(getenv, "REDIS_ADDR", "localhost:6379"),
		RedisPassword: getenv("REDIS_PASSWORD"), // empty = no AUTH
		BaseURL:       strings.TrimRight(envOr(getenv, "BASE_URL", "http://localhost:8080"), "/"),
	}

	if p, err := strconv.Atoi(cfg.Port); err != nil || p < 1 || p > 65535 {
		return config{}, fmt.Errorf("PORT must be a number between 1 and 65535, got %q", cfg.Port)
	}
	switch cfg.Store {
	case "redis", "memory":
	default:
		return config{}, fmt.Errorf(`STORE must be "redis" or "memory", got %q`, cfg.Store)
	}
	if u, err := url.Parse(cfg.BaseURL); err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return config{}, fmt.Errorf("BASE_URL must be an absolute http(s) URL, got %q", cfg.BaseURL)
	}
	return cfg, nil
}

func envOr(getenv func(string) string, key, def string) string {
	if v := strings.TrimSpace(getenv(key)); v != "" {
		return v
	}
	return def
}
