#!/bin/sh
# app-build-info v1 · canonical copy lives in the app-build-info skill; update it there and re-copy.
# Print build identification as KEY=value lines for the deploy script to export
# or pass as build args. Runs on the host, where .git exists.
#   set -a; eval "$(path/to/build-env.sh)"; set +a
set -eu
cd "$(dirname "$0")"
sha=${GIT_COMMIT:-$(git rev-parse HEAD 2>/dev/null || true)}
if ! printf '%s' "$sha" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "build-env: invalid or missing commit SHA: '$sha'" >&2
  exit 1
fi
# Untracked files are not built into the image's identity; tracked changes are.
if ! git diff --quiet HEAD 2>/dev/null; then
  echo "build-env: uncommitted changes; $sha does not describe the built source" >&2
  [ "${ALLOW_DIRTY:-}" = 1 ] || exit 1
fi
echo "GIT_COMMIT=$sha"
echo "BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
