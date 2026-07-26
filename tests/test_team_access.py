from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app.web.server import create_server
from app.web.team_access import (
    ResearchCapacityGate,
    TestAccessCapacityError,
    TestAccessSessionRegistry,
    UserResearchAppPool,
)


class TestAccessSessionRegistryTest(unittest.TestCase):
    def test_password_is_required_but_never_persisted_in_session(self) -> None:
        now = [1000.0]
        registry = TestAccessSessionRegistry(
            3,
            60,
            600,
            clock=lambda: now[0],
            token_factory=lambda: "session-token",
        )

        session = registry.login("Researcher 01", "do-not-store-this", remember=False)

        self.assertEqual(session.token, "session-token")
        self.assertEqual(session.display_name, "Researcher 01")
        self.assertNotIn("do-not-store-this", repr(session))
        self.assertEqual(registry.resolve("session-token"), session)
        now[0] = 1061.0
        self.assertIsNone(registry.resolve("session-token"))

    def test_active_user_limit_counts_aliases_not_browser_sessions(self) -> None:
        tokens = iter(("a-1", "a-2", "b-1", "c-1", "d-1"))
        registry = TestAccessSessionRegistry(
            3,
            60,
            600,
            token_factory=lambda: next(tokens),
        )
        registry.login("alpha", "x")
        registry.login("alpha", "x")
        registry.login("beta", "x")
        registry.login("gamma", "x")

        self.assertEqual(registry.active_user_count(), 3)
        with self.assertRaisesRegex(TestAccessCapacityError, "测试席位已满"):
            registry.login("delta", "x")


class ResearchCapacityGateTest(unittest.TestCase):
    def test_gate_rejects_unbounded_research_and_tracks_real_jobs(self) -> None:
        gate = ResearchCapacityGate(1)

        with gate.slot("analysis"):
            with self.assertRaisesRegex(TestAccessCapacityError, "重研判任务已达上限"):
                with gate.slot("analysis"):
                    pass
        gate.record_model_explanation()

        metrics = gate.metrics()
        self.assertEqual(metrics["active_jobs"], 0)
        self.assertEqual(metrics["analysis_jobs"], 1)
        self.assertEqual(metrics["completed_jobs"], 1)
        self.assertEqual(metrics["model_explanations"], 1)


class UserResearchAppPoolTest(unittest.TestCase):
    def test_pool_assigns_a_distinct_directory_to_each_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pool = UserResearchAppPool(tmpdir, lambda path: path)

            first = pool.get("first")
            second = pool.get("second")

            self.assertEqual(first, Path(tmpdir) / "users" / "first")
            self.assertEqual(second, Path(tmpdir) / "users" / "second")
            self.assertNotEqual(first, second)
            self.assertIs(first, pool.get("first"))


class SmallTeamHttpFlowTest(unittest.TestCase):
    def test_login_is_unverified_but_api_and_memory_are_session_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, tmpdir, "production")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            first = build_opener(HTTPCookieProcessor(CookieJar()))
            second = build_opener(HTTPCookieProcessor(CookieJar()))
            try:
                with self.assertRaises(HTTPError) as unauthorized:
                    first.open(f"{base_url}/api/profile")
                self.assertEqual(unauthorized.exception.code, 401)

                first_login = _post_json(
                    first,
                    f"{base_url}/api/session/login",
                    {"account": "alpha", "password": "ignored-secret"},
                )
                self.assertTrue(first_login["authenticated"])
                self.assertFalse(first_login["credential_validation"])
                self.assertNotIn("ignored-secret", json.dumps(first_login, ensure_ascii=False))
                self.assertGreaterEqual(len(first_login["login_visual"]["back_messages"]), 8)
                self.assertGreaterEqual(len(first_login["login_visual"]["back_message_palette"]), 4)

                _post_json(first, f"{base_url}/api/watchlist", {"symbol": "600519"})
                _post_json(
                    second,
                    f"{base_url}/api/session/login",
                    {"account": "beta", "password": "another-secret"},
                )
                second_watchlist = _get_json(second, f"{base_url}/api/watchlist")
                self.assertEqual(second_watchlist["items"], [])
                _post_json(second, f"{base_url}/api/watchlist", {"symbol": "000725"})

                self.assertEqual(
                    _get_json(first, f"{base_url}/api/watchlist")["items"][0]["symbol"],
                    "600519.SH",
                )
                self.assertEqual(
                    _get_json(second, f"{base_url}/api/watchlist")["items"][0]["symbol"],
                    "000725.SZ",
                )

                with self.assertRaises(HTTPError) as model_config:
                    _post_json(
                        first,
                        f"{base_url}/api/models/configure",
                        {"provider_id": "deepseek", "api_key": "not-accepted"},
                    )
                self.assertEqual(model_config.exception.code, 403)

                _post_json(first, f"{base_url}/api/session/logout", {})
                with self.assertRaises(HTTPError) as logged_out:
                    first.open(f"{base_url}/api/watchlist")
                self.assertEqual(logged_out.exception.code, 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_login_route_accepts_trailing_slash_and_query_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, tmpdir, "production")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            client = build_opener(HTTPCookieProcessor(CookieJar()))
            try:
                payload = _post_json(
                    client,
                    f"{base_url}/api/session/login/?source=login-page",
                    {"account": "slash-user", "password": "test-only"},
                )
                self.assertTrue(payload["authenticated"])
                self.assertEqual(payload["user"]["display_name"], "slash-user")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


def _post_json(opener, url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(opener, url: str) -> dict[str, object]:
    with opener.open(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
