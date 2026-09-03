from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import pytest

from live_translator.config import ConfigError, load_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def write_config(path: Path) -> None:
    path.write_text(
        """
[asr]
ws_url = "ws://127.0.0.1:9000/v1/asr"
ready_url = "http://127.0.0.1:9000/ready"

[translation]
endpoint = "https://translator.invalid/v1/messages"
model = "private-model"

[audio]
device_index = 7
""".strip(),
        encoding="utf-8",
    )


def environment(tmp_path: Path, **values: str) -> dict[str, str]:
    return {"LOCALAPPDATA": str(tmp_path), **values}


def write_local_api_key(tmp_path: Path, value: str) -> None:
    config_directory = tmp_path / "LiveTranslator"
    config_directory.mkdir()
    (config_directory / ".env").write_text(
        f"LIVE_TRANSLATOR_API_KEY={value}\n",
        encoding="utf-8",
    )


def test_load_config_reads_api_key_from_local_app_data(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    write_local_api_key(tmp_path, "from-file")

    config = load_config(config_path, environ=environment(tmp_path))

    assert config.asr.ws_url == "ws://127.0.0.1:9000/v1/asr"
    assert config.translator.api_key == "from-file"
    assert config.translator.model == "private-model"
    assert config.audio.device_index == 7


def test_process_environment_overrides_dot_env(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    write_local_api_key(tmp_path, "from-file")

    config = load_config(
        config_path,
        environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="from-process"),
    )

    assert config.translator.api_key == "from-process"


def test_missing_api_key_is_readable(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    with pytest.raises(ConfigError, match="LIVE_TRANSLATOR_API_KEY"):
        load_config(config_path, environ=environment(tmp_path))


def test_custom_config_does_not_read_an_adjacent_dot_env(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    (tmp_path / ".env").write_text(
        "LIVE_TRANSLATOR_API_KEY=wrong-location\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="LIVE_TRANSLATOR_API_KEY"):
        load_config(config_path, environ=environment(tmp_path))


def test_invalid_toml_does_not_fall_back_silently(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[asr", encoding="utf-8")

    with pytest.raises(ConfigError, match="Could not read"):
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="key"),
        )


def test_example_api_key_is_rejected_before_any_request(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    with pytest.raises(ConfigError, match="Replace the example LIVE_TRANSLATOR_API_KEY"):
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="replace-me"),
        )


def test_api_key_with_surrounding_whitespace_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    with pytest.raises(ConfigError, match="surrounding whitespace"):
        load_config(
            config_path,
            environ=environment(
                tmp_path,
                LIVE_TRANSLATOR_API_KEY=" configured-key ",
            ),
        )


def test_example_endpoint_is_rejected_before_any_request(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    text = config_path.read_text(encoding="utf-8").replace(
        "https://translator.invalid/v1/messages",
        "https://provider.invalid/v1/messages",
    )
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="Replace the example translation endpoint"):
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="configured-key"),
        )


def test_example_model_is_rejected_before_any_request(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    text = config_path.read_text(encoding="utf-8").replace(
        'model = "private-model"',
        'model = "replace-with-your-model"',
    )
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="Replace the example translation model"):
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="configured-key"),
        )


def test_translation_table_rejects_api_key_and_does_not_echo_its_value(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    text = config_path.read_text(encoding="utf-8").replace(
        "[translation]",
        '[translation]\napi_key = "must-not-leak"',
    )
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown key: api_key") as caught:
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="configured-key"),
        )

    assert "must-not-leak" not in str(caught.value)


def test_configuration_rejects_misspelled_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    with config_path.open("a", encoding="utf-8") as file:
        file.write("\ntimeot_s = 10\n")

    with pytest.raises(ConfigError, match="unknown key: timeot_s"):
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="configured-key"),
        )


def test_configuration_rejects_non_finite_timeouts(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    text = config_path.read_text(encoding="utf-8").replace(
        "\n[audio]",
        "\ntimeout_s = nan\n\n[audio]",
    )
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="timeout_s must be finite"):
        load_config(
            config_path,
            environ=environment(tmp_path, LIVE_TRANSLATOR_API_KEY="configured-key"),
        )


def test_shipped_config_uses_the_guarded_placeholder_values() -> None:
    path = REPOSITORY_ROOT / "windows-client" / "config.example.toml"
    decoded = cast(object, tomllib.loads(path.read_text(encoding="utf-8")))
    assert isinstance(decoded, dict)
    root = cast(dict[str, object], decoded)
    translation = root.get("translation")
    assert isinstance(translation, dict)

    assert cast(dict[str, object], translation) == {
        "endpoint": "https://provider.invalid/v1/messages",
        "model": "replace-with-your-model",
        "anthropic_version": "2023-06-01",
        "max_tokens": 256,
        "timeout_s": 4.0,
    }
