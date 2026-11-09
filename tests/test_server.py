"""Tests for the web server's behaviour under a slow or stalled client."""

import socket
import threading
import unittest
import urllib.request

from app import create_server


class StalledClientTest(unittest.TestCase):
    def setUp(self):
        self.server = create_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_a_stalled_upload_does_not_block_other_requests(self):
        # Announces a body it never sends, which is what a very slow upload looks like.
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as stalled:
            stalled.sendall(
                b"POST /merge HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Type: multipart/form-data; boundary=x\r\nContent-Length: 100000\r\n\r\n"
            )
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as response:
                self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
