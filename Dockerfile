# syntax=docker/dockerfile:1

# ---- build stage: full Go toolchain (~250 MB), thrown away afterwards ----
# Keep the tag in step with the "go" line in go.mod.
FROM golang:1.22-alpine AS build
WORKDIR /src

# Dependencies first: this layer is cached until go.mod/go.sum change, so
# editing a .go file does not re-download modules.
COPY go.mod go.sum ./
RUN go mod download

COPY . .
# CGO_ENABLED=0 → static binary that runs on an image without libc.
# -s -w strips the symbol table and DWARF info (smaller image).
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/minibank ./cmd/minibank

# ---- runtime stage: distroless static (CA certs + tzdata, no shell) ----
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/minibank /minibank
# Never run as root: 65532 is the "nonroot" user of distroless.
USER 65532:65532
ENV PORT=8080
EXPOSE 8080
# No curl in the image, so the binary checks itself.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 CMD ["/minibank", "-healthcheck"]
ENTRYPOINT ["/minibank"]
