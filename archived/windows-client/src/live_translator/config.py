from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import cast

from .asr import AsrClientConfig
from .security import private_file_acl_warning
from .translator import AnthropicTranslatorConfig

API_KEY_ENV_NAME = "LIVE_TRANSLATOR_API_KEY"
PLACEHOLDER_API_KEY = "replace-me"
PLACEHOLDER_ENDPOINT = "https://provider.invalid/v1/messages"
PLACEHOLDER_MODEL = "replace-with-your-model"
_ROOT_KEYS = {"asr", "translation", "audio"}
_ASR_KEYS = {
    "ws_url",
    "ready_url",
    "connect_timeout_s",
    "stop_timeout_s",
}
_TRANSLATION_KEYS = {
    "endpoint",
    "model",
    "anthropic_version",
    "max_tokens",
    "timeout_s",
}
_AUDIO_KEYS = {"device_index"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AudioConfig:
    device_index: int | None = None

    def __post_init__(self) -> None:
        if self.device_index is not None and self.device_index < 0:
            raise ValueError("device_index must be non-negative")


@dataclass(frozen=True, slots=True)
class AppConfig:
    asr: AsrClientConfig
    translator: AnthropicTranslatorConfig
    audio: AudioConfig = AudioConfig()
    security_warnings: tuple[str, ...] = ()


def default_config_dir(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    local_app_data = values.get("LOCALAPPDATA")
    if not local_app_data:
        raise ConfigError("LOCALAPPDATA is not set.")
    return Path(local_app_data) / "LiveTranslator"


def load_config(
    config_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    environment = dict(os.environ if environ is None else environ)
    config_directory = default_config_dir(environment)
    path = config_path or config_directory / "config.toml"
    if not path.is_file():
        raise ConfigError(f"Configuration file does not exist: {path}")

    try:
        with path.open("rb") as file:
            decoded = cast(object, tomllib.load(file))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read configuration file: {path}") from exc
    if not isinstance(decoded, Mapping):
        raise ConfigError("Configuration root must be a TOML table.")
    root = cast(Mapping[str, object], decoded)
    _reject_unknown_keys(root, _ROOT_KEYS, "configuration root")

    dot_env_path = config_directory / ".env"
    dot_env = _read_dot_env(dot_env_path)
    environment_api_key = environment.get(API_KEY_ENV_NAME)
    file_api_key = dot_env.get(API_KEY_ENV_NAME)
    api_key = environment_api_key or file_api_key
    if not api_key or not api_key.strip():
        raise ConfigError(f"{API_KEY_ENV_NAME} is not configured.")
    if api_key != api_key.strip():
        raise ConfigError(f"{API_KEY_ENV_NAME} must not contain surrounding whitespace.")
    if api_key == PLACEHOLDER_API_KEY:
        raise ConfigError(f"Replace the example {API_KEY_ENV_NAME} value before starting.")

    security_warnings: tuple[str, ...] = ()
    if dot_env_path.is_file():
        warning = private_file_acl_warning(dot_env_path)
        if warning:
            security_warnings = (warning,)

    asr_table = _required_table(root, "asr")
    translator_table = _required_table(root, "translation")
    audio_table = _optional_table(root, "audio")
    _reject_unknown_keys(asr_table, _ASR_KEYS, "asr")
    _reject_unknown_keys(translator_table, _TRANSLATION_KEYS, "translation")
    _reject_unknown_keys(audio_table, _AUDIO_KEYS, "audio")
    translation_endpoint = _required_str(translator_table, "endpoint")
    translation_model = _required_str(translator_table, "model")
    if translation_endpoint == PLACEHOLDER_ENDPOINT:
        raise ConfigError("Replace the example translation endpoint before starting.")
    if translation_model == PLACEHOLDER_MODEL:
        raise ConfigError("Replace the example translation model before starting.")

    try:
        return AppConfig(
            asr=AsrClientConfig(
                ws_url=_required_str(asr_table, "ws_url"),
                ready_url=_required_str(asr_table, "ready_url"),
                connect_timeout_s=_optional_float(asr_table, "connect_timeout_s", 5.0),
                stop_timeout_s=_optional_float(asr_table, "stop_timeout_s", 5.0),
            ),
            translator=AnthropicTranslatorConfig(
                endpoint=translation_endpoint,
                api_key=api_key,
                model=translation_model,
                anthropic_version=_optional_str(
                    translator_table,
                    "anthropic_version",
                    "2023-06-01",
                ),
                max_tokens=_optional_int(translator_table, "max_tokens", 256),
                timeout_s=_optional_float(translator_table, "timeout_s", 4.0),
            ),
            audio=AudioConfig(
                device_index=_optional_nullable_int(audio_table, "device_index"),
            ),
            security_warnings=security_warnings,
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _read_dot_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"Could not read environment file: {path}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"Invalid .env entry at line {line_number}.")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _required_table(root: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = root.get(key)
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} must be a TOML table.")
    return cast(Mapping[str, object], value)


def _reject_unknown_keys(
    table: Mapping[str, object],
    allowed: set[str],
    table_name: str,
) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{table_name} contains unknown key: {unknown[0]}")


def _optional_table(root: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = root.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} must be a TOML table.")
    return cast(Mapping[str, object], value)


def _required_str(table: Mapping[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string.")
    if value != value.strip():
        raise ConfigError(f"{key} must not contain surrounding whitespace.")
    return value


def _optional_str(table: Mapping[str, object], key: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string.")
    if value != value.strip():
        raise ConfigError(f"{key} must not contain surrounding whitespace.")
    return value


def _optional_int(table: Mapping[str, object], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer.")
    return value


def _optional_nullable_int(table: Mapping[str, object], key: str) -> int | None:
    value = table.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer.")
    return value


def _optional_float(table: Mapping[str, object], key: str, default: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number.")
    converted = float(value)
    if not isfinite(converted):
        raise ConfigError(f"{key} must be finite.")
    return converted
