package main

import "testing"

func TestLoadConfig(t *testing.T) {
	tests := []struct {
		name    string
		env     map[string]string
		want    config
		wantErr bool
	}{
		{
			name: "memory with defaults",
			env:  map[string]string{"STORE": "memory"},
			want: config{Port: "8080", Store: "memory"},
		},
		{
			name: "postgres with url",
			env:  map[string]string{"PORT": "9090", "DATABASE_URL": "postgres://u:p@db/x"},
			want: config{Port: "9090", Store: "postgres", DatabaseURL: "postgres://u:p@db/x"},
		},
		{name: "postgres is the default and needs a url", env: map[string]string{}, wantErr: true},
		{name: "unknown store", env: map[string]string{"STORE": "redis"}, wantErr: true},
		{name: "port not a number", env: map[string]string{"STORE": "memory", "PORT": "http"}, wantErr: true},
		{name: "port out of range", env: map[string]string{"STORE": "memory", "PORT": "70000"}, wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := loadConfig(func(k string) string { return tt.env[k] })
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
			if !tt.wantErr && got != tt.want {
				t.Fatalf("config = %+v, want %+v", got, tt.want)
			}
		})
	}
}
