# Path: tests/test_summarizer_providers.py
# File: test_summarizer_providers.py
# Created: 2026-06-25
# Purpose: Backend tests for the DWBG-017/018/019 summarizer provider abstraction —
#          the get_provider() factory (env selection, default-to-ollama, unknown
#          fallback), OllamaProvider.complete (mocked HTTP: success + connection
#          error -> None), and AnthropicProvider.complete (no-key / SDK-error / SDK
#          success best-effort behavior). No live Ollama and no real Claude API.
# Caller: pytest
# Callees: app.services.summarizer_providers (get_provider, NarrativeProvider),
#          app.services.summarizer_providers.ollama (OllamaProvider),
#          app.services.summarizer_providers.anthropic_provider (AnthropicProvider),
#          app.services.summarizer_providers.mlx (MLXProvider)
# Data In: monkeypatched env + monkeypatched requests.post / anthropic SDK
# Data Out: assertions on provider selection and complete() return values
# Last Modified: 2026-06-25

"""DWBG-017/018/019 — summarizer provider interface, factory, and backends."""

import requests

from app.services import summarizer_providers as sp
from app.services.summarizer_providers import NarrativeProvider, get_provider
from app.services.summarizer_providers.anthropic_provider import AnthropicProvider
from app.services.summarizer_providers.mlx import MLXProvider
from app.services.summarizer_providers.ollama import OllamaProvider

_PROVIDER_ENV = "DWB_SUMMARIZER_PROVIDER"


# ---------------------------------------------------------------------------
# DWBG-017 — factory: env selection, default, unknown fallback
# ---------------------------------------------------------------------------


class TestGetProvider:
    def test_defaults_to_ollama_when_unset(self, monkeypatch):
        monkeypatch.delenv(_PROVIDER_ENV, raising=False)
        assert isinstance(get_provider(), OllamaProvider)

    def test_selects_ollama_explicitly(self, monkeypatch):
        monkeypatch.setenv(_PROVIDER_ENV, "ollama")
        assert isinstance(get_provider(), OllamaProvider)

    def test_selects_anthropic(self, monkeypatch):
        monkeypatch.setenv(_PROVIDER_ENV, "anthropic")
        assert isinstance(get_provider(), AnthropicProvider)

    def test_selects_mlx_stub(self, monkeypatch):
        monkeypatch.setenv(_PROVIDER_ENV, "mlx")
        assert isinstance(get_provider(), MLXProvider)

    def test_case_insensitive_and_trimmed(self, monkeypatch):
        monkeypatch.setenv(_PROVIDER_ENV, "  Anthropic  ")
        assert isinstance(get_provider(), AnthropicProvider)

    def test_unknown_value_falls_back_to_ollama(self, monkeypatch):
        monkeypatch.setenv(_PROVIDER_ENV, "gpt-9000")
        assert isinstance(get_provider(), OllamaProvider)

    def test_empty_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(_PROVIDER_ENV, "")
        assert isinstance(get_provider(), OllamaProvider)

    def test_providers_satisfy_protocol(self):
        for p in (OllamaProvider(), AnthropicProvider(), MLXProvider()):
            assert isinstance(p, NarrativeProvider)


# ---------------------------------------------------------------------------
# DWBG-018 — OllamaProvider (HTTP mocked; no live daemon)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class TestOllamaProvider:
    def test_success_returns_text(self, monkeypatch):
        captured = {}

        def _fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResp({"message": {"role": "assistant", "content": "the story"}})

        monkeypatch.setattr(requests, "post", _fake_post)
        out = OllamaProvider().complete(system="S", user="U", max_tokens=8000)
        assert out == "the story"
        assert captured["url"].endswith("/api/chat")
        assert captured["json"]["stream"] is False
        assert captured["json"]["options"]["num_predict"] == 8000
        roles = [m["role"] for m in captured["json"]["messages"]]
        assert roles == ["system", "user"]

    def test_connection_error_returns_none(self, monkeypatch):
        def _boom(*a, **k):
            raise requests.ConnectionError("daemon down")

        monkeypatch.setattr(requests, "post", _boom)
        assert OllamaProvider().complete(system="S", user="U", max_tokens=100) is None

    def test_http_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            requests, "post", lambda *a, **k: _FakeResp({}, status=500)
        )
        assert OllamaProvider().complete(system="S", user="U", max_tokens=100) is None

    def test_bad_json_returns_none(self, monkeypatch):
        class _BadJson(_FakeResp):
            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(requests, "post", lambda *a, **k: _BadJson({}))
        assert OllamaProvider().complete(system="S", user="U", max_tokens=100) is None

    def test_missing_content_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            requests, "post", lambda *a, **k: _FakeResp({"message": {}})
        )
        assert OllamaProvider().complete(system="S", user="U", max_tokens=100) is None

    def test_blank_content_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            requests, "post",
            lambda *a, **k: _FakeResp({"message": {"content": "   "}}),
        )
        assert OllamaProvider().complete(system="S", user="U", max_tokens=100) is None

    def test_honors_base_url_and_model_env(self, monkeypatch):
        captured = {}

        def _fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["model"] = json["model"]
            return _FakeResp({"message": {"content": "ok"}})

        monkeypatch.setenv("OLLAMA_BASE_URL", "http://box:9999/")
        monkeypatch.setenv("DWB_SUMMARIZER_MODEL", "llama3.1")
        monkeypatch.setattr(requests, "post", _fake_post)
        OllamaProvider().complete(system="S", user="U", max_tokens=10)
        assert captured["url"] == "http://box:9999/api/chat"
        assert captured["model"] == "llama3.1"


# ---------------------------------------------------------------------------
# DWBG-019 — AnthropicProvider (behavior-preserving; SDK skips/errors -> None)
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    def test_no_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert AnthropicProvider().complete(system="S", user="U", max_tokens=1) is None

    def test_api_error_returns_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        class _BoomClient:
            def __init__(self, *a, **k):
                self.messages = self

            def create(self, *a, **k):
                raise RuntimeError("boom")

        import anthropic
        monkeypatch.setattr(anthropic, "Anthropic", _BoomClient)
        assert AnthropicProvider().complete(system="S", user="U", max_tokens=1) is None

    def test_success_preserves_params_and_returns_text(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DWB_SUMMARIZER_MODEL", "claude-sonnet-4-6")
        captured = {}

        class _Block:
            type = "text"
            text = "the story"

        class _Msg:
            content = [_Block()]

        class _OkClient:
            def __init__(self, *a, **k):
                self.messages = self

            def create(self, **k):
                captured.update(k)
                return _Msg()

        import anthropic
        monkeypatch.setattr(anthropic, "Anthropic", _OkClient)
        out = AnthropicProvider().complete(system="S", user="U", max_tokens=8000)
        assert out == "the story"
        # Behavior-preserving: adaptive thinking, model default, token passthrough.
        assert captured["thinking"] == {"type": "adaptive"}
        assert captured["model"] == "claude-sonnet-4-6"
        assert captured["max_tokens"] == 8000
        assert captured["system"] == "S"
        assert captured["messages"] == [{"role": "user", "content": "U"}]


# ---------------------------------------------------------------------------
# DWBG-019 — MLXProvider stub (deferred; always None)
# ---------------------------------------------------------------------------


class TestMLXProvider:
    def test_stub_returns_none(self):
        assert MLXProvider().complete(system="S", user="U", max_tokens=100) is None


def test_module_exports():
    assert hasattr(sp, "get_provider")
    assert hasattr(sp, "NarrativeProvider")
