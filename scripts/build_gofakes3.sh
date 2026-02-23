#!/bin/bash
# Build gofakes3 (lightweight Go-based S3 server) from source.
# Used for S3 integration tests without requiring minio or moto.
#
# Prerequisites: Go 1.22+
# Usage: ./scripts/build_gofakes3.sh [output_path]
#        Default output: /tmp/gofakes3

set -euo pipefail

OUTPUT="${1:-/tmp/gofakes3}"
WORKDIR=$(mktemp -d)

cleanup() {
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

cat > "$WORKDIR/main.go" << 'GOEOF'
package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"

	"github.com/johannesboyne/gofakes3"
	"github.com/johannesboyne/gofakes3/backend/s3mem"
)

func main() {
	port := flag.Int("port", 9000, "port to listen on")
	flag.Parse()

	backend := s3mem.New()
	faker := gofakes3.New(backend)

	addr := fmt.Sprintf(":%d", *port)
	log.Printf("Starting fake S3 server on %s", addr)
	log.Fatal(http.ListenAndServe(addr, faker.Server()))
}
GOEOF

cat > "$WORKDIR/go.mod" << 'MODEOF'
module gofakes3-server

go 1.22
MODEOF

cd "$WORKDIR"
go get github.com/johannesboyne/gofakes3@latest
go get github.com/johannesboyne/gofakes3/backend/s3mem@latest
go build -o "$OUTPUT" .

echo "Built gofakes3 at: $OUTPUT"
