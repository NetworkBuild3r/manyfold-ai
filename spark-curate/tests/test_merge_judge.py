"""Pluggable merge judge: provider selection, the OpenAI-compatible provider, no default egress."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _isolation import setUpModule, tearDownModule  # noqa: E402, F401 — no live provider calls
from spark_curate import merge_judge, safe_http  # noqa: E402
from spark_curate.candidates import MergeCandidate  # noqa: E402
from spark_curate.clients import HttpError  # noqa: E402
from spark_curate.config import CurateConfig, SparkConfig, load_config  # noqa: E402
from spark_curate.decide_merge import MERGE_JUDGE_QUESTIONS, decide_merge_pair  # noqa: E402
from spark_curate.walk import ModelFolder  # noqa: E402

QUESTIONS = {"link_state": {"type": "score"}, "same_printable_product": {"type": "noul"}}


def _openai_cfg(**kw: object) -> CurateConfig:
    base = dict(
        merge_judge="openai",
        judge_base_url="https://llm.example/v1",
        judge_model="some-model",
        judge_api_key="cfg-key",
    )
    base.update(kw)
    return CurateConfig(**base)  # type: ignore[arg-type]


def _chat(content: str) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    resp.__enter__.return_value = resp
    return resp


class ProviderSelectionTests(unittest.TestCase):
    def test_default_is_local_and_returns_no_judge(self) -> None:
        self.assertEqual(CurateConfig().merge_judge, "local")
        self.assertIsNone(merge_judge.judge_for(CurateConfig()))

    def test_an_exported_typesafe_key_alone_enables_nothing(self) -> None:
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "exported-key"}):
            self.assertIsNone(merge_judge.judge_for(CurateConfig()))

    def test_unknown_provider_fails_loud(self) -> None:
        with self.assertRaises(merge_judge.MergeJudgeConfigError) as ctx:
            merge_judge.validate(CurateConfig(merge_judge="gpt-everything"))
        self.assertIn("local, typesafe, openai", str(ctx.exception))

    def test_typesafe_requires_a_key(self) -> None:
        with self.assertRaises(merge_judge.MergeJudgeConfigError):
            merge_judge.validate(CurateConfig(merge_judge="typesafe"))

    def test_openai_requires_url_and_model(self) -> None:
        with self.assertRaises(merge_judge.MergeJudgeConfigError) as ctx:
            merge_judge.validate(CurateConfig(merge_judge="openai"))
        self.assertIn("JUDGE_BASE_URL and JUDGE_MODEL", str(ctx.exception))

    def test_config_load_rejects_a_bad_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"curate": {"merge_judge": "nope"}}), encoding="utf-8")
            with self.assertRaises(merge_judge.MergeJudgeConfigError):
                load_config(path)

    def test_builds_each_provider(self) -> None:
        ts = merge_judge.judge_for(CurateConfig(merge_judge="typesafe", typesafe_api_key="k"))
        self.assertEqual(ts.name, "typesafe")
        self.assertEqual(merge_judge.judge_for(_openai_cfg()).name, "openai")


class OpenAICompatibleJudgeTests(unittest.TestCase):
    def test_success_sends_bearer_and_returns_only_asked_dict_answers(self) -> None:
        content = json.dumps(
            {
                "link_state": {"score": 1.9, "confidence": 0.9},
                "same_printable_product": {"noul": 0.95},
                "unasked": {"x": 1},
                "garbage": "not a dict",
            }
        )
        judge = merge_judge.judge_for(_openai_cfg())
        with patch.object(safe_http.OPENER, "open", return_value=_chat(content)) as opener:
            out = judge.answers({"folder_a": "A"}, QUESTIONS)

        self.assertEqual(set(out), {"link_state", "same_printable_product"})
        req = opener.call_args.args[0]
        self.assertEqual(req.full_url, "https://llm.example/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer cfg-key")
        sent = json.loads(req.data)
        self.assertEqual(sent["model"], "some-model")
        self.assertEqual(sent["temperature"], 0)
        self.assertIn("untrusted", sent["messages"][0]["content"])

    def test_no_authorization_header_when_no_key(self) -> None:
        judge = merge_judge.judge_for(_openai_cfg(judge_api_key=""))
        with patch.object(safe_http.OPENER, "open", return_value=_chat("{}")) as opener:
            judge.answers("s", QUESTIONS)
        self.assertIsNone(opener.call_args.args[0].get_header("Authorization"))

    def test_env_key_wins_over_config(self) -> None:
        with patch.dict(os.environ, {"JUDGE_API_KEY": "env-key"}):
            judge = merge_judge.judge_for(_openai_cfg())
        with patch.object(safe_http.OPENER, "open", return_value=_chat("{}")) as opener:
            judge.answers("s", QUESTIONS)
        self.assertEqual(opener.call_args.args[0].get_header("Authorization"), "Bearer env-key")

    def test_fenced_json_is_accepted(self) -> None:
        judge = merge_judge.judge_for(_openai_cfg())
        fenced = '```json\n{"same_printable_product": {"noul": 0.4}}\n```'
        with patch.object(safe_http.OPENER, "open", return_value=_chat(fenced)):
            self.assertEqual(judge.answers("s", QUESTIONS), {"same_printable_product": {"noul": 0.4}})

    def test_http_error_is_short_and_redacts_the_key(self) -> None:
        err = urllib.error.HTTPError(
            "https://llm.example/v1/chat/completions", 401, "Unauthorized", None,
            io.BytesIO(b"bad key cfg-key\r\nINJECTED " + b"z" * 500),
        )
        judge = merge_judge.judge_for(_openai_cfg())
        with patch.object(safe_http.OPENER, "open", side_effect=err):
            with self.assertRaises(HttpError) as ctx:
                judge.answers("s", QUESTIONS)
        msg = str(ctx.exception)
        self.assertNotIn("cfg-key", msg)
        self.assertNotRegex(msg, r"[\x00-\x1f]")
        self.assertLess(len(msg), 200)

    def test_bad_responses_raise_http_error(self) -> None:
        judge = merge_judge.judge_for(_openai_cfg())
        for name, resp in (("non-json", MagicMock()), ("no choices", _chat("")), ("prose", _chat("sure thing"))):
            with self.subTest(name):
                if name == "non-json":
                    resp.read.return_value = b"<html>"
                    resp.__enter__.return_value = resp
                with patch.object(safe_http.OPENER, "open", return_value=resp):
                    with self.assertRaises(HttpError):
                        judge.answers("s", QUESTIONS)

    def test_plain_http_is_refused_except_for_a_private_lan_ip(self) -> None:
        remote = merge_judge.judge_for(_openai_cfg(judge_base_url="http://llm.example/v1"))
        with patch.object(safe_http.OPENER, "open") as opener:
            with self.assertRaises(HttpError):
                remote.answers("s", QUESTIONS)
        opener.assert_not_called()
        local = merge_judge.judge_for(_openai_cfg(judge_base_url="http://192.168.11.161:8000/v1"))
        with patch.object(safe_http.OPENER, "open", return_value=_chat("{}")):
            self.assertEqual(local.answers("s", QUESTIONS), {})


def _pair(tmp: Path, signals: list[str]) -> MergeCandidate:
    a = tmp / "DC" / "Pack"
    b = tmp / "DC" / "Pack (2)"
    for d, data in ((a, b"a"), (b, b"b")):
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.stl").write_bytes(data)
    return MergeCandidate(
        a=ModelFolder(path=a, category="DC", name="Pack"),
        b=ModelFolder(path=b, category="DC", name="Pack (2)"),
        signals=list(signals),
    )


class DecisionWithOpenAIJudgeTests(unittest.TestCase):
    """Swapping the provider does not change the approval rules."""

    def _decide(self, answers: str, signals: list[str]):
        cfg = _openai_cfg(min_merge_confidence=0.80)
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(Path(tmp), signals)
            with (
                patch("spark_curate.decide_merge._preview_jpeg", return_value=b"\xff\xd8fakejpeg"),
                patch("spark_curate.decide_merge.clients.gemma_vision", return_value="same pack"),
                patch.object(safe_http.OPENER, "open", return_value=_chat(answers)),
                patch("spark_curate.decide_merge.clients.curator_json") as qwen,
            ):
                d = decide_merge_pair(cand, SparkConfig(), cfg, Path(tmp) / ".thumbs")
            qwen.assert_not_called()
            return d

    def test_consistent_confident_answers_are_approved(self) -> None:
        answers = json.dumps(
            {
                "link_state": {"score": 1.9, "confidence": 0.9},
                "same_printable_product": {"noul": 0.9},
                "character_or_franchise_only": {"noul": 0.1},
                "keep_target": {"choice": "b"},
            }
        )
        d = self._decide(answers, ["name_near_dupe"])
        self.assertEqual((d.decision, d.target, d.judge_outcome), ("merge", "b", "merge"))
        self.assertTrue(d.approved_for_apply)

    def test_contradicting_answers_are_not_approved(self) -> None:
        answers = json.dumps(
            {
                "link_state": {"score": 1.9, "confidence": 0.9},
                "same_printable_product": {"noul": 0.9},
                "character_or_franchise_only": {"noul": 0.95},
                "keep_target": {"choice": "a"},
            }
        )
        d = self._decide(answers, ["name_near_dupe"])
        self.assertEqual(d.decision, "merge")
        self.assertFalse(d.approved_for_apply)
        self.assertIn("contradicts: character_only", d.reason)

    def test_missing_answers_fail_closed(self) -> None:
        d = self._decide(json.dumps({"link_state": {"score": 1.9, "confidence": 0.9}}), ["name_near_dupe"])
        self.assertFalse(d.approved_for_apply)

    def test_questions_are_provider_neutral(self) -> None:
        self.assertEqual(
            set(MERGE_JUDGE_QUESTIONS),
            {"link_state", "same_printable_product", "character_or_franchise_only", "keep_target"},
        )


if __name__ == "__main__":
    unittest.main()
