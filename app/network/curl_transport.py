from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping

from app.config.runtime import load_runtime_settings


def fetch_text_with_curl(
    url: str,
    headers: Mapping[str, str],
    *,
    encoding: str = "utf-8",
) -> str:
    """Run curl without locale-dependent text decoding.

    Windows may decode ``subprocess.run(text=True)`` output with the active
    ANSI code page. Provider or curl output that uses another encoding can
    then kill the reader thread and leave ``stdout`` as ``None``. Reading
    bytes first keeps transport failures deterministic and recoverable.
    """
    curl = shutil.which("curl")
    if not curl:
        raise OSError("curl is unavailable")
    curl_headers = [
        argument
        for name, value in headers.items()
        for argument in ("-H", f"{name}: {value}")
    ]
    try:
        completed = subprocess.run(
            [curl, "--http1.1", "-sS", *curl_headers, url],
            capture_output=True,
            check=False,
            timeout=load_runtime_settings().get("runtime", "network_timeout_seconds"),
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"curl timed out after {exc.timeout} seconds") from exc

    stdout = completed.stdout if isinstance(completed.stdout, bytes) else b""
    stderr = completed.stderr if isinstance(completed.stderr, bytes) else b""
    if completed.returncode != 0 or not stdout.strip():
        message = stderr.decode("utf-8", errors="replace").strip() or "curl returned no data"
        raise OSError(message)
    return stdout.decode(encoding, errors="replace")
