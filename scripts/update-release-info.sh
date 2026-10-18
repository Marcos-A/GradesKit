#!/bin/sh
# app-build-info v1 · canonical copy lives in the app-build-info skill; update it there and re-copy.
# Write release-info.json from the latest published GitHub release, or "null" if
# there is none or it cannot be verified. Run on each deploy and after publishing
# a release (the app re-reads the file, so no rebuild is needed).
#   update-release-info.sh <output-file> [deployed-sha]
set -eu
out=${1:?usage: update-release-info.sh <output-file> [deployed-sha]}
deployed=${2:-}
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
tmp="$out.tmp"
mkdir -p "$(dirname "$out")"
# gh and git resolve the repository from the checkout this script lives in.
cd "$(dirname "$0")"
commit=""
if tag=$(gh release view --json tagName -q .tagName 2>/dev/null) && [ -n "$tag" ]; then
  git fetch --quiet --tags 2>/dev/null || true
  commit=$(git rev-list -n 1 "$tag" 2>/dev/null || true)
fi
if [ -z "$commit" ]; then
  echo "update-release-info: no published release could be verified; writing null" >&2
  echo null > "$tmp"
# A rollback to a commit older than the release must not claim that release.
elif [ -n "$deployed" ] && ! git merge-base --is-ancestor "$commit" "$deployed" 2>/dev/null; then
  echo null > "$tmp"
else
  printf '{"version":"%s","tag":"%s","commit":"%s"}\n' "${tag#v}" "$tag" "$commit" > "$tmp"
fi
chmod 644 "$tmp"
mv "$tmp" "$out"
