package main

import (
	"strings"
	"testing"
)

func TestLoadConfig(t *testing.T) {
	tests := []struct {
		name    string
		env     map[string]string
		want    config
		wantErr string // substring; "" = no error
	}{
		{
			name: "defaults",
			env:  map[string]string{},
			want: config{Port: "8080", Store: "redis", RedisAddr: "localhost:6379", BaseURL: "http://localhost:8080"},
		},
		{
			name: "everything set, trailing slash trimmed",
			env: map[string]string{"PORT": "9000", "STORE": "MEMORY", "REDIS_ADDR": "redis:6379",
				"REDIS_PASSWORD": "s3cret", "BASE_URL": "https://sl.example/"},
			want: config{Port: "9000", Store: "memory", RedisAddr: "redis:6379", RedisPassword: "s3cret", BaseURL: "https://sl.example"},
		},
		{name: "bad port", env: map[string]string{"PORT": "eighty"}, wantErr: "PORT"},
		{name: "port out of range", env: map[string]string{"PORT": "70000"}, wantErr: "PORT"},
		{name: "unknown store", env: map[string]string{"STORE": "postgres"}, wantErr: "STORE"},
		{name: "relative base url", env: map[string]string{"BASE_URL": "localhost:8080"}, wantErr: "BASE_URL"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := loadConfig(func(k string) string { return tt.env[k] })
			if tt.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tt.wantErr) {
					t.Fatalf("err = %v, want it to mention %s", err, tt.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Fatalf("config = %+v, want %+v", got, tt.want)
			}
		})
	}
}
