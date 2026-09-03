from __future__ import annotations

import pytest

from live_translator.asr import AsrClientConfig
from live_translator.translator import AnthropicTranslatorConfig


@pytest.mark.parametrize(
    ("ws_url", "ready_url"),
    [
        ("ws://127.0.0.1:9000/v1/asr", "http://127.0.0.1:9000/ready"),
        ("ws://localhost:9000/v1/asr", "http://localhost:9000/ready"),
        ("wss://[::1]:9000/v1/asr", "https://[::1]:9000/ready"),
    ],
)
def test_asr_endpoints_accept_only_loopback_hosts(ws_url: str, ready_url: str) -> None:
    config = AsrClientConfig(ws_url=ws_url, ready_url=ready_url)

    assert config.ws_url == ws_url
    assert config.ready_url == ready_url


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ws_url", "ws://192.168.1.10:9000/v1/asr"),
        ("ready_url", "http://example.com/ready"),
        ("ws_url", "ws://user:secret@127.0.0.1:9000/v1/asr"),
    ],
)
def test_asr_endpoints_reject_non_loopback_or_credential_urls(field: str, value: str) -> None:
    values = {field: value}

    with pytest.raises(ValueError):
        AsrClientConfig(**values)  # type: ignore[arg-type]


def test_translation_endpoint_allows_remote_https() -> None:
    config = AnthropicTranslatorConfig(
        endpoint="https://translator.example/v1/messages",
        api_key="secret",
        model="model",
    )

    assert config.endpoint == "https://translator.example/v1/messages"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://translator.example/v1/messages",
        "https://user:secret@translator.example/v1/messages",
        "https://translator.example/v1/messages#fragment",
    ],
)
def test_translation_endpoint_rejects_cleartext_remote_or_credential_urls(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError):
        AnthropicTranslatorConfig(
            endpoint=endpoint,
            api_key="secret",
            model="model",
        )


def test_translation_config_repr_hides_api_key() -> None:
    api_key = "must-not-appear"
    config = AnthropicTranslatorConfig(
        endpoint="https://translator.example/v1/messages",
        api_key=api_key,
        model="model",
    )

    assert api_key not in repr(config)
