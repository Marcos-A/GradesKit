"""Which commit is running and the latest published release.

The commit and build time are baked into the image by `scripts/build-env.sh`;
the release comes from `release-info.json`, written on the host by
`scripts/update-release-info.sh` and re-read here when it changes, so
publishing a release needs no rebuild. Nothing here runs git or calls GitHub.
"""

from __future__ import annotations

import json
import os
import re
from functools import cache
from html import escape
from pathlib import Path

APP_ID = "gradeskit"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
ENVIRONMENT_LABELS = {"production": "Producció", "preview": "Preview", "development": "Desenvolupament"}

_release_cache: tuple[float, dict | None] | None = None


@cache
def _build() -> dict:
    sha = os.getenv("GIT_COMMIT", "").strip().lower()
    build = {"sha": sha, "shortSha": sha[:7]} if _SHA.match(sha) else {"sha": "unknown", "shortSha": "unknown"}
    if built_at := os.getenv("BUILD_TIME", "").strip():
        build["builtAt"] = built_at
    return build


def _release() -> dict | None:
    """The published release from release-info.json; anything unexpected means none."""

    global _release_cache
    path = Path(os.getenv("RELEASE_INFO_FILE", "build-meta/release-info.json"))
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _release_cache and _release_cache[0] == mtime:
        return _release_cache[1]
    release = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        match = _TAG.match(data.get("tag", "")) if isinstance(data, dict) else None
        if match and data.get("version") == match.group(1) and _SHA.match(data.get("commit", "")):
            release = {"version": data["version"], "tag": data["tag"], "commit": data["commit"]}
    except (OSError, ValueError):
        release = None
    _release_cache = (mtime, release)
    return release


def environment() -> str:
    return os.getenv("APP_ENV", "").strip() or "development"


def get_build_info() -> dict:
    return {"schemaVersion": 1, "app": APP_ID, "environment": environment(), "build": _build(), "release": _release()}


def footer() -> dict | None:
    """What the footer shows: parts are (text, url or None); None hides it.

    GradesKit has no accounts, so visibility depends only on REPO_VISIBILITY:
    with a private repository, production shows just the release.
    """

    info = get_build_info()
    build, release, env = info["build"], info["release"], info["environment"]
    repo = os.getenv("REPO_URL", "").strip().rstrip("/")
    technical = os.getenv("REPO_VISIBILITY", "").strip().lower() == "public"
    known = build["sha"] != "unknown"
    links = bool(repo) and technical
    commit = (build["shortSha"], f"{repo}/commit/{build['sha']}" if links and known else None)

    if not known:
        parts = [("Build unknown", None)]
    elif env != "production":
        parts = [(ENVIRONMENT_LABELS.get(env, env.capitalize()), None), commit]
    elif not technical:
        if not release:
            return None
        parts = [(release["tag"], None)]
    elif release:
        parts = [(release["tag"], f"{repo}/releases/tag/{release['tag']}" if links else None), commit]
    else:
        parts = [("Build", None), commit]
    details = []
    if technical or env != "production":
        details = [f"Darrera versió: {release['tag'] if release else 'cap'}",
                   f"Commit desplegat: {build['sha']}",
                   f"Entorn: {ENVIRONMENT_LABELS.get(env, env)}"]
    # "Build 05f2e39" reads as one identifier, the rest are separated by " · ".
    separator = " " if parts[0][0] == "Build" else " · "
    return {"parts": parts, "separator": separator, "details": " · ".join(details)}


def footer_html() -> str:
    """The footer as escaped HTML for `string.Template`, or "" when hidden."""

    data = footer()
    if not data:
        return ""
    items = []
    for text, url in data["parts"]:
        if url:
            items.append(f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(text)}</a>')
        else:
            items.append(escape(text))
    title = f' title="{escape(data["details"])}"' if data["details"] else ""
    return f'<footer class="build-info"{title}>{data["separator"].join(items)}</footer>'
