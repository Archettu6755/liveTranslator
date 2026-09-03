from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from pathlib import Path

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".pyright",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "Transfer",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
}
FORBIDDEN_EXACT_NAMES = {".env", "config.toml", "credentials.json"}
FORBIDDEN_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".engine",
    ".gguf",
    ".key",
    ".log",
    ".onnx",
    ".p12",
    ".pem",
    ".pfx",
    ".pt",
    ".pth",
    ".safetensors",
}
ALLOWED_DOT_ENV_NAMES = {".env.example"}
EXPECTED_ENV_TEMPLATE = """\
# configure.ps1 copies this file to %LOCALAPPDATA%\\LiveTranslator\\.env.
# Replace the placeholder there. Never add a real key to this template.
LIVE_TRANSLATOR_API_KEY=replace-me
"""
EXPECTED_CONFIG_TEMPLATE = """\
# configure.ps1 copies this template to %LOCALAPPDATA%\\LiveTranslator\\config.toml.
# Keep production configuration and API credentials out of the source checkout.
[asr]
# The Windows client accepts loopback ASR endpoints only.
ws_url = "ws://127.0.0.1:9000/v1/asr"
ready_url = "http://127.0.0.1:9000/ready"
connect_timeout_s = 5.0
stop_timeout_s = 5.0

[translation]
# Replace both placeholders. Remote endpoints must use HTTPS.
endpoint = "https://provider.invalid/v1/messages"
model = "replace-with-your-model"
anthropic_version = "2023-06-01"
max_tokens = 256
timeout_s = 4.0

[audio]
# Leave device_index commented to use the default WASAPI loopback device.
# device_index = 0
"""
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".spec",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = {
    "private key": re.compile(
        r"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
}


def iter_repository_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
            continue
        yield path


def check_repository(root: Path) -> list[str]:
    problems: list[str] = []
    for path in iter_repository_files(root):
        relative = path.relative_to(root)
        name = path.name
        normalized_name = name.casefold()
        if normalized_name in FORBIDDEN_EXACT_NAMES:
            problems.append(f"forbidden local file: {relative}")
        if (
            normalized_name.startswith(".env.")
            and normalized_name not in ALLOWED_DOT_ENV_NAMES
        ):
            problems.append(f"forbidden environment file: {relative}")
        if normalized_name in ALLOWED_DOT_ENV_NAMES:
            try:
                template_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                problems.append(f"unreadable environment template: {relative}")
            else:
                if template_text != EXPECTED_ENV_TEMPLATE:
                    problems.append(f"unsafe environment template: {relative}")
        if normalized_name == "config.example.toml":
            try:
                template_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                problems.append(f"unreadable configuration template: {relative}")
            else:
                if template_text != EXPECTED_CONFIG_TEMPLATE:
                    problems.append(f"unsafe configuration template: {relative}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            problems.append(f"forbidden credential, log, or model file: {relative}")
        if re.search(r"(?i)\.log\.\d+$", normalized_name):
            problems.append(f"forbidden rotated log file: {relative}")
        if (
            path.suffix.casefold() not in TEXT_SUFFIXES
            or path.stat().st_size > 2_000_000
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"possible {label}: {relative}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check repository files for local secrets."
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()

    problems = check_repository(root)
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print(f"Repository guard passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
