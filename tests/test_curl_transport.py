from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.network.curl_transport import fetch_text_with_curl


class CurlTransportTest(unittest.TestCase):
    @patch("app.network.curl_transport.subprocess.run")
    @patch("app.network.curl_transport.shutil.which", return_value="curl.exe")
    def test_reads_bytes_without_using_windows_locale(
        self,
        _which,
        run,
    ) -> None:
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=b'{"message":"' + bytes([0xFF]) + b'"}',
            stderr=b"",
        )

        result = fetch_text_with_curl("https://example.test/data", {"Accept": "application/json"})

        self.assertIn("\ufffd", result)
        self.assertNotIn("text", run.call_args.kwargs)

    @patch("app.network.curl_transport.subprocess.run")
    @patch("app.network.curl_transport.shutil.which", return_value="curl.exe")
    def test_missing_reader_output_becomes_os_error_instead_of_attribute_error(
        self,
        _which,
        run,
    ) -> None:
        run.return_value = SimpleNamespace(returncode=7, stdout=None, stderr=None)

        with self.assertRaisesRegex(OSError, "curl returned no data"):
            fetch_text_with_curl("https://example.test/data", {})

    @patch("app.network.curl_transport.subprocess.run")
    @patch("app.network.curl_transport.shutil.which", return_value="curl.exe")
    def test_timeout_is_normalized_to_os_error(self, _which, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(["curl"], 8)

        with self.assertRaisesRegex(OSError, "timed out"):
            fetch_text_with_curl("https://example.test/data", {})


if __name__ == "__main__":
    unittest.main()
