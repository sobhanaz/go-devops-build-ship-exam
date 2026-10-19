# syntax=docker/dockerfile:1

# ---- build stage: full Go toolchain (~250 MB), thrown away afterwards ----
# The builder must be at least the `go` version in go.mod (1.22 here); newer
# is fine. Official images set GOTOOLCHAIN=local, so an OLDER one would fail.
FROM golang:1.25-alpine AS build
WORKDIR /src

# Dependencies first: this layer is cached until go.mod/go.sum change,
# so editing a .go file does not re-download modules.
COPY go.mod go.sum ./
RUN go mod download

COPY . .
# CGO_ENABLED=0 → fully static binary that runs on scratch (no libc).
# -s -w strips the symbol table and DWARF info → much smaller binary.
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/snaplink ./cmd/snaplink

# ---- runtime stage: just the binary (~10 MB image, 10.2 MB measured) ----
# scratch has no shell, no CA bundle and no tzdata. SnapLink makes no outbound
# TLS calls and only uses UTC, so it needs none of them.
FROM scratch
COPY --from=build /out/snaplink /snaplink
# Numeric UID:GID so Kubernetes runAsNonRoot can verify it.
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 CMD ["/snaplink", "-healthcheck"]
ENTRYPOINT ["/snaplink"]
