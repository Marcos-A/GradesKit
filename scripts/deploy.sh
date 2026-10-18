#!/usr/bin/env bash
# Build and (re)start GradesKit with its compose file, identifying the build.
#   scripts/deploy.sh
# COMPOSE_FILE and BUILD_META_DIR can be overridden (see README).
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-/srv/compose/gradeskit/compose.yml}"
# Bake the commit into the image; refuses an unknown commit or uncommitted changes.
build_env=$(scripts/build-env.sh)
set -a; eval "$build_env"; set +a
# The latest published release, read by the app at runtime.
export BUILD_META_DIR="${BUILD_META_DIR:-$PWD/build-meta}"
scripts/update-release-info.sh "$BUILD_META_DIR/release-info.json" "$GIT_COMMIT"
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
docker compose -f "$COMPOSE_FILE" ps
