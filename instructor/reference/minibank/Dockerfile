# syntax=docker/dockerfile:1

# ---- build stage: full Go toolchain (~250 MB), thrown away afterwards ----
# The builder must be at least the "go" version in go.mod (1.22 here);
# any newer golang image works.
FROM golang:1.25-alpine AS build
WORKDIR /src

# Dependencies first: this layer is cached until go.mod/go.sum change, so
# editing a .go file does not re-download modules.
COPY go.mod go.sum ./
RUN go mod download

COPY . .
# CGO_ENABLED=0 → static binary that runs on an image without libc.
# -s -w strips the symbol table and DWARF info (smaller image).
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/minibank ./cmd/minibank

# ---- runtime stage: scratch = empty image, just our static binary ----
# (scratch instead of distroless: gcr.io images are often blocked in Iran.)
FROM scratch
COPY --from=build /out/minibank /minibank
# Never run as root. scratch has no /etc/passwd, so use a numeric uid:gid.
USER 65532:65532
ENV PORT=8080
EXPOSE 8080
# No curl in the image, so the binary checks itself.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 CMD ["/minibank", "-healthcheck"]
ENTRYPOINT ["/minibank"]
