"""Tests for build identification: /build-info.json and the page footer."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from gradeskit import build_info

SHA = "05f2e39a83f21c92d4e0a1b2c3d4e5f607182930"
RELEASE_SHA = "a83f21c92d4e0a1b2c3d4e5f60718293005f2e39"
REPO = "https://github.com/Marcos-A/GradesKit"


class BuildInfoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.release_file = Path(self.tmp.name) / "release-info.json"
        self.env = {
            "GIT_COMMIT": SHA,
            "BUILD_TIME": "2026-10-18T14:30:00Z",
            "APP_ENV": "production",
            "REPO_URL": REPO,
            "REPO_VISIBILITY": "public",
            "RELEASE_INFO_FILE": str(self.release_file),
        }
        self.reset()

    def tearDown(self):
        self.tmp.cleanup()
        self.reset()

    def reset(self):
        build_info._build.cache_clear()
        build_info._release_cache = None

    def write_release(self, tag="v1.0.0", version="1.0.0", commit=RELEASE_SHA):
        self.release_file.write_text(json.dumps({"version": version, "tag": tag, "commit": commit}))

    def footer_text(self, **overrides):
        with mock.patch.dict(os.environ, {**self.env, **overrides}):
            self.reset()
            data = build_info.footer()
        return data and data["separator"].join(text for text, _ in data["parts"])

    def test_schema_with_release(self):
        self.write_release()
        with mock.patch.dict(os.environ, self.env):
            info = build_info.get_build_info()
        self.assertEqual(info["schemaVersion"], 1)
        self.assertEqual(info["app"], "gradeskit")
        self.assertEqual(info["environment"], "production")
        self.assertEqual(info["build"], {"sha": SHA, "shortSha": "05f2e39", "builtAt": "2026-10-18T14:30:00Z"})
        self.assertEqual(info["release"], {"version": "1.0.0", "tag": "v1.0.0", "commit": RELEASE_SHA})

    def test_footer_variants(self):
        self.write_release()
        self.assertEqual(self.footer_text(), "v1.0.0 · 05f2e39")
        self.assertEqual(self.footer_text(APP_ENV="preview"), "Preview · 05f2e39")
        self.assertEqual(self.footer_text(REPO_VISIBILITY="private"), "v1.0.0")
        self.assertEqual(self.footer_text(GIT_COMMIT="nope"), "Build unknown")
        self.release_file.unlink()
        self.assertEqual(self.footer_text(), "Build 05f2e39")
        self.assertIsNone(self.footer_text(REPO_VISIBILITY="private"))

    def test_invalid_release_is_ignored(self):
        self.write_release(tag="v1.0.0+2", version="1.0.0")
        with mock.patch.dict(os.environ, self.env):
            self.assertIsNone(build_info.get_build_info()["release"])

    def test_links_use_full_sha(self):
        self.write_release()
        with mock.patch.dict(os.environ, self.env):
            html = build_info.footer_html()
        self.assertIn(f'href="{REPO}/commit/{SHA}"', html)
        self.assertIn(f'href="{REPO}/releases/tag/v1.0.0"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_endpoint_and_page(self):
        self.write_release()
        with mock.patch.dict(os.environ, self.env):
            status, headers, body = call(app.application, "/build-info.json")
            self.assertEqual(status, "200 OK")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(json.loads(body)["build"]["sha"], SHA)
            _, _, page = call(app.application, "/")
        self.assertIn('class="build-info"', page.decode("utf-8"))


def call(application, path):
    captured = {}

    def start_response(status, headers):
        captured["status"], captured["headers"] = status, dict(headers)

    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "wsgi.input": io.BytesIO()}
    body = b"".join(application(environ, start_response))
    return captured["status"], captured["headers"], body


if __name__ == "__main__":
    unittest.main()
