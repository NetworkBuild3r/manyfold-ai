"""Model auto-resolve: FORGE_LLM_MODEL is optional, checked against GET /models, and a 404 chat
reply re-resolves once. No database; a local fake OpenAI-compatible HTTP server.

The loopback ban of ``LlmEndpoint.from_env`` is kept: the resolver tests call
``LlmEndpoint.resolve`` (URL already validated) against the loopback fake. INIT-032/SPEC-016
"""

from __future__ import annotations

import json
import logging

import pytest

from forge.packs import llm
from forge.packs.llm import LlmCallError, LlmConfigError, LlmEndpoint, post_json, resolve_model

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def chat(endpoint: LlmEndpoint) -> str:
    body = llm.request_body(endpoint, system="s", user="u", schema=SCHEMA, schema_name="t")
    return post_json(endpoint, body)


def models_of(fake) -> list[str]:
    return [r["body"]["model"] for r in fake.requests]


# --------------------------------------------------------------------------- resolve_model


def test_set_and_served_is_used_verbatim(fake_llm):
    fake_llm.models = ["Qwen/Qwen3.6-35B-A3B", "other"]
    assert resolve_model(fake_llm.url, "Qwen/Qwen3.6-35B-A3B") == (
        "Qwen/Qwen3.6-35B-A3B",
        "explicit",
    )


def test_set_but_not_served_with_one_served_substitutes_and_warns(fake_llm, caplog, monkeypatch):
    # alembic's fileConfig (any migrated_db fixture run earlier) disables pre-existing loggers
    monkeypatch.setattr(llm._log, "disabled", False)
    fake_llm.models = ["Qwen/Qwen3.6-35B-A3B"]
    with caplog.at_level(logging.WARNING, logger="forge.llm"):
        model, how = resolve_model(fake_llm.url, "Qwen/Qwen3.8-Flash-Next")
    assert (model, how) == ("Qwen/Qwen3.6-35B-A3B", "substituted")
    warned = " ".join(r.getMessage() for r in caplog.records)
    assert "Qwen/Qwen3.8-Flash-Next" in warned and "Qwen/Qwen3.6-35B-A3B" in warned


def test_set_but_not_served_with_several_served_fails_listing_them(fake_llm):
    fake_llm.models = ["b-model", "a-model"]
    with pytest.raises(LlmConfigError) as exc:
        resolve_model(fake_llm.url, "gone")
    assert "a-model, b-model" in str(exc.value) and "'gone'" in str(exc.value)


@pytest.mark.parametrize("requested", [None, "", "  ", "auto", "AUTO"])
def test_unset_or_auto_uses_the_single_served_model(fake_llm, requested):
    fake_llm.models = ["Qwen/Qwen3.6-35B-A3B"]
    assert resolve_model(fake_llm.url, requested) == ("Qwen/Qwen3.6-35B-A3B", "auto")


@pytest.mark.parametrize("served", [["m-two", "m-one"], []])
def test_unset_with_zero_or_many_served_fails_listing_ids(fake_llm, served):
    fake_llm.models = served
    with pytest.raises(LlmConfigError) as exc:
        resolve_model(fake_llm.url, None)
    msg = str(exc.value)
    assert ("m-one, m-two" in msg) if served else ("(none)" in msg)


def test_models_unreachable_with_explicit_model_uses_it_unverified(fake_llm):
    fake_llm.models = None  # HTTP 503
    assert resolve_model(fake_llm.url, "pinned") == ("pinned", "explicit_unverified")


def test_models_unreachable_without_model_is_a_config_error(fake_llm):
    fake_llm.models = None
    with pytest.raises(LlmConfigError, match="unreachable"):
        resolve_model(fake_llm.url, "auto")


def test_connection_refused_counts_as_unreachable(fake_llm):
    url = fake_llm.url
    fake_llm.close()
    assert llm.list_served_models(url, timeout=1.0) is None
    assert resolve_model(url, "pinned")[1] == "explicit_unverified"
    with pytest.raises(LlmConfigError):
        resolve_model(url, None)


def test_models_answer_of_the_wrong_shape_is_unreachable(fake_llm, monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"models": ["x"]}'

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: Resp())
    assert llm.list_served_models("http://192.168.11.161:1/v1") is None


# --------------------------------------------------------------------------------- from_env


def env(monkeypatch, url, model):
    for name, value in (("FORGE_LLM_URL", url), ("FORGE_LLM_MODEL", model)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "url",
    [None, " ", "http://localhost:11434/v1", "http://127.0.0.1:1/v1", "ftp://192.168.11.161/v1"],
)
def test_from_env_url_stays_mandatory_and_loopback_banned(fake_llm, monkeypatch, url):
    env(monkeypatch, url, "m")
    monkeypatch.setattr(llm, "list_served_models", lambda *a, **k: pytest.fail("no network"))
    with pytest.raises(LlmConfigError):
        LlmEndpoint.from_env()


def test_from_env_loopback_fake_is_refused_even_when_it_serves_a_model(fake_llm, monkeypatch):
    env(monkeypatch, fake_llm.url, None)  # 127.0.0.1 — the ban is not weakened for tests
    with pytest.raises(LlmConfigError, match="loopback"):
        LlmEndpoint.from_env()
    assert fake_llm.model_gets == 0


def test_from_env_model_unset_follows_the_served_model(monkeypatch):
    env(monkeypatch, "http://192.168.11.161:11434/v1/", None)
    monkeypatch.setattr(llm, "list_served_models", lambda url, **k: ["Qwen/Qwen3.6-35B-A3B"])
    ep = LlmEndpoint.from_env()
    assert ep.model == "Qwen/Qwen3.6-35B-A3B" and ep.requested is None and ep.how == "auto"
    assert ep.completions_url == "http://192.168.11.161:11434/v1/chat/completions"


def test_from_env_auto_and_stale_name_and_unreachable(monkeypatch):
    served = {"v": ["new-model"]}
    monkeypatch.setattr(llm, "list_served_models", lambda url, **k: served["v"])
    env(monkeypatch, "http://192.168.11.161:11434/v1", "auto")
    assert LlmEndpoint.from_env().model == "new-model"
    env(monkeypatch, "http://192.168.11.161:11434/v1", "old-model")
    ep = LlmEndpoint.from_env()
    assert (ep.model, ep.requested, ep.how) == ("new-model", "old-model", "substituted")
    served["v"] = None
    assert LlmEndpoint.from_env().model == "old-model"  # explicit + unreachable: no guess
    env(monkeypatch, "http://192.168.11.161:11434/v1", None)
    with pytest.raises(LlmConfigError):
        LlmEndpoint.from_env()


# ------------------------------------------------------------------------- 404 re-resolve


def test_404_re_resolves_once_and_retries_with_the_served_model(fake_llm):
    fake_llm.models = ["m-old"]
    fake_llm.responder = lambda body: "{}"
    ep = LlmEndpoint.resolve(fake_llm.url, None)
    assert ep.model == "m-old"
    fake_llm.models = ["m-new"]  # the operator swapped the served model
    fake_llm.serves = {"m-new"}
    assert chat(ep) == "{}"
    assert models_of(fake_llm) == ["m-old", "m-new"]
    assert ep.model == "m-new" and ep.how == "auto"
    assert fake_llm.model_gets == 2
    chat(ep)  # later calls keep the new model with no more /models lookups
    assert models_of(fake_llm)[-1] == "m-new" and fake_llm.model_gets == 2


def test_404_with_nothing_better_served_raises_http_404_without_looping(fake_llm):
    fake_llm.models = ["m-one"]
    ep = LlmEndpoint.resolve(fake_llm.url, None)
    fake_llm.serves = set()  # every chat is a 404, /models still says m-one
    with pytest.raises(LlmCallError, match="http 404"):
        chat(ep)
    assert models_of(fake_llm) == ["m-one"]


def test_404_re_resolves_at_most_once_per_call(fake_llm):
    fake_llm.models = ["m-one"]
    ep = LlmEndpoint.resolve(fake_llm.url, None)
    fake_llm.models = ["m-two"]
    fake_llm.serves = set()
    with pytest.raises(LlmCallError, match="http 404"):
        chat(ep)
    assert models_of(fake_llm) == ["m-one", "m-two"]
    assert fake_llm.model_gets == 2


def test_404_with_an_explicit_name_that_is_still_served_does_not_retry(fake_llm):
    fake_llm.models = ["pinned"]
    ep = LlmEndpoint.resolve(fake_llm.url, "pinned")
    fake_llm.serves = set()
    with pytest.raises(LlmCallError, match="http 404"):
        chat(ep)
    assert models_of(fake_llm) == ["pinned"]


def test_404_when_resolution_is_ambiguous_raises_http_404(fake_llm):
    fake_llm.models = ["m-one"]
    ep = LlmEndpoint.resolve(fake_llm.url, None)
    fake_llm.models = ["m-two", "m-three"]  # now two models: auto cannot choose
    fake_llm.serves = {"m-two"}
    with pytest.raises(LlmCallError, match="http 404"):
        chat(ep)
    assert models_of(fake_llm) == ["m-one"]


def test_other_http_errors_do_not_re_resolve(fake_llm):
    fake_llm.models = ["m-one"]
    ep = LlmEndpoint.resolve(fake_llm.url, None)
    fake_llm.responder = lambda body: (400, json.dumps({"error": "bad"}))
    with pytest.raises(LlmCallError, match="http 400"):
        chat(ep)
    assert fake_llm.model_gets == 1  # only the initial resolve
