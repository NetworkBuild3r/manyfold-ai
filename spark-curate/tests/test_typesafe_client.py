"""TypeSafe System One client — fake urlopen, no live calls (INIT-001/SPEC-007)."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _isolation import setUpModule, tearDownModule  # noqa: E402, F401 — no live TypeSafe calls
from spark_curate import typesafe_client  # noqa: E402
from spark_curate.clients import HttpError  # noqa: E402
from spark_curate.config import CurateConfig  # noqa: E402

KEY = "ts-secret-key-123"


def _response(body: bytes) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return resp


def _call(**kwargs: object) -> dict:
    return typesafe_client.system_one(
        api_key=kwargs.pop("api_key", KEY),
        state={"folder_a": "A"},
        questions={"q": {"type": "noul", "instructions": "?"}},
        base_url="https://ts.example/",
        **kwargs,  # type: ignore[arg-type]
    )


class SystemOneTests(unittest.TestCase):
    def test_success_posts_payload_and_returns_body(self) -> None:
        body = json.dumps({"answers": {"q": {"noul": 0.9}}}).encode()
        with patch.object(typesafe_client._OPENER, "open", return_value=_response(body)) as urlopen:
            out = _call(model="jev-x", timeout=5.0)

        self.assertEqual(out["answers"]["q"]["noul"], 0.9)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://ts.example/v1/systemone")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), f"Bearer {KEY}")
        sent = json.loads(req.data)
        self.assertEqual(sent["model"], "jev-x")
        self.assertEqual(sent["state"], {"folder_a": "A"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5.0)

    def test_empty_key_raises_before_any_request(self) -> None:
        with patch.object(typesafe_client._OPENER, "open") as urlopen:
            with self.assertRaises(HttpError):
                _call(api_key="")
        urlopen.assert_not_called()

    def test_http_error_is_truncated_and_never_contains_the_key(self) -> None:
        body = (f"invalid key {KEY} " + "x" * 1000).encode()
        err = urllib.error.HTTPError(
            "https://ts.example/v1/systemone", 401, "Unauthorized", None, io.BytesIO(body)
        )
        with patch.object(typesafe_client._OPENER, "open", side_effect=err):
            with self.assertRaises(HttpError) as ctx:
                _call()

        msg = str(ctx.exception)
        self.assertIn("HTTP 401", msg)
        self.assertNotIn(KEY, msg)
        self.assertIn("[redacted]", msg)
        self.assertLess(len(msg), 400)

    def test_connection_failure_maps_to_http_error(self) -> None:
        with patch.object(typesafe_client._OPENER, "open", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(HttpError) as ctx:
                _call()
        self.assertIn("connection failed", str(ctx.exception))
        self.assertNotIn(KEY, str(ctx.exception))

    def test_non_json_body(self) -> None:
        with patch.object(typesafe_client._OPENER, "open", return_value=_response(b"<html>oops</html>")):
            with self.assertRaises(HttpError) as ctx:
                _call()
        self.assertIn("non-JSON", str(ctx.exception))

    def test_body_without_answers(self) -> None:
        with patch.object(typesafe_client._OPENER, "open", return_value=_response(b'{"error": "quota"}')):
            with self.assertRaises(HttpError) as ctx:
                _call()
        self.assertIn("Unexpected TypeSafe response", str(ctx.exception))


class ApiKeyFromTests(unittest.TestCase):
    def test_env_wins_over_config(self) -> None:
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}):
            self.assertEqual(
                typesafe_client.api_key_from(CurateConfig(typesafe_api_key="stale-cfg-key")), "env-key"
            )

    def test_config_used_when_env_blank(self) -> None:
        self.assertEqual(
            typesafe_client.api_key_from(CurateConfig(typesafe_api_key=" cfg-key ")), "cfg-key"
        )

    def test_blank_everywhere_means_unconfigured(self) -> None:
        self.assertEqual(typesafe_client.api_key_from(CurateConfig()), "")
        self.assertEqual(typesafe_client.api_key_from(None), "")


class TransportSafetyTests(unittest.TestCase):
    def test_redirects_are_refused_so_the_token_is_never_resent(self) -> None:
        handler = typesafe_client._NoRedirect()
        with self.assertRaises(HttpError) as ctx:
            handler.redirect_request(None, None, 302, "Found", {}, "http://evil.example/")
        self.assertIn("redirect refused", str(ctx.exception))

    def test_non_https_base_url_is_refused_before_any_request(self) -> None:
        with patch.object(typesafe_client._OPENER, "open") as opener:
            with self.assertRaises(HttpError) as ctx:
                typesafe_client.system_one(
                    api_key=KEY, state={}, questions={}, base_url="http://api.typesafe.ai"
                )
        self.assertIn("https", str(ctx.exception))
        opener.assert_not_called()

    def test_plain_http_is_allowed_for_localhost_only(self) -> None:
        body = json.dumps({"answers": {}}).encode()
        for base in ("http://localhost:8080", "http://127.0.0.1:9"):
            with self.subTest(base), patch.object(
                typesafe_client._OPENER, "open", return_value=_response(body)
            ):
                typesafe_client.system_one(api_key=KEY, state={}, questions={}, base_url=base)

    def test_vendor_error_text_has_no_control_characters_and_is_capped(self) -> None:
        err = urllib.error.HTTPError(
            "https://ts.example/v1/systemone", 422, "Unprocessable", None,
            io.BytesIO(("bad\r\nINJECTED\x1b[31m " + "y" * 500).encode()),
        )
        with patch.object(typesafe_client._OPENER, "open", side_effect=err):
            with self.assertRaises(HttpError) as ctx:
                _call()
        msg = str(ctx.exception)
        self.assertNotRegex(msg, r"[\x00-\x1f]")
        self.assertLess(len(msg), 200)

    def test_unexpected_response_reports_keys_not_content(self) -> None:
        body = b'{"error": "quota", "detail": "secret-ish text"}'
        with patch.object(typesafe_client._OPENER, "open", return_value=_response(body)):
            with self.assertRaises(HttpError) as ctx:
                _call()
        self.assertIn("keys:", str(ctx.exception))
        self.assertNotIn("secret-ish", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
