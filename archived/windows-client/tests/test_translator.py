from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

from live_translator.models import (
    TranslationContext,
    TranslationRequest,
)
from live_translator.translator import (
    AnthropicTranslator,
    AnthropicTranslatorConfig,
    MockTranslator,
    TranslationError,
)


def make_config(api_key: str = "private-test-key") -> AnthropicTranslatorConfig:
    return AnthropicTranslatorConfig(
        endpoint="https://translator.invalid/v1/messages",
        api_key=api_key,
        model="my-model",
    )


async def test_anthropic_request_and_text_block_response() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = cast(object, json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": " 第一行 "},
                    {"type": "tool_use", "id": "ignored"},
                    {"type": "text", "text": "第二行"},
                ]
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = AnthropicTranslator(make_config(), http_client=http_client)

    result = await translator.translate(
        TranslationRequest(
            source_text="今日は配信します。",
            context=(
                TranslationContext(
                    source_text="こんにちは。",
                    translated_text="大家好。",
                ),
            ),
        )
    )
    await translator.close()
    await http_client.aclose()

    assert result.translated_text == "第一行\n第二行"
    headers = cast(dict[str, str], captured["headers"])
    assert headers["x-api-key"] == "private-test-key"
    assert headers["anthropic-version"] == "2023-06-01"

    body = cast(dict[str, object], captured["body"])
    assert body["model"] == "my-model"
    assert body["max_tokens"] == 256
    assert isinstance(body["system"], str)
    messages = cast(list[dict[str, str]], body["messages"])
    assert messages[0]["role"] == "user"
    assert "日文：こんにちは。" in messages[0]["content"]
    assert "当前句：\n今日は配信します。" in messages[0]["content"]
    assert all(message["role"] != "system" for message in messages)


async def test_http_error_does_not_expose_api_key() -> None:
    api_key = "must-not-leak"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = AnthropicTranslator(make_config(api_key), http_client=http_client)

    with pytest.raises(TranslationError) as caught:
        await translator.translate(TranslationRequest(source_text="失敗"))

    await http_client.aclose()
    assert "HTTP 401" in str(caught.value)
    assert api_key not in str(caught.value)


@pytest.mark.parametrize(
    "response_json",
    [
        {},
        {"content": "wrong"},
        {"content": []},
        {"content": [{"type": "tool_use"}]},
        {"content": [{"type": "text", "text": "  "}]},
    ],
)
async def test_malformed_response_is_rejected(response_json: object) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = AnthropicTranslator(make_config(), http_client=http_client)

    with pytest.raises(TranslationError):
        await translator.translate(TranslationRequest(source_text="失敗"))

    await http_client.aclose()


async def test_timeout_is_readable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = AnthropicTranslator(make_config(), http_client=http_client)

    with pytest.raises(TranslationError, match="timed out"):
        await translator.translate(TranslationRequest(source_text="遅い"))

    await http_client.aclose()


async def test_mock_translator_has_no_network_dependency() -> None:
    translator = MockTranslator({"テスト": "测试"})

    result = await translator.translate(TranslationRequest(source_text="テスト"))
    await translator.close()

    assert result.translated_text == "测试"
