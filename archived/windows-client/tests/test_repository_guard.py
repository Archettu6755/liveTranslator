from __future__ import annotations

from pathlib import Path

from scripts.check_repository import check_repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_guard_rejects_case_variants_keys_and_model_files(tmp_path: Path) -> None:
    (tmp_path / ".ENV").write_text("secret=value", encoding="utf-8")
    (tmp_path / "model.ONNX").write_bytes(b"model")
    (tmp_path / "runtime.log.1").write_text("diagnostics", encoding="utf-8")
    (tmp_path / "weights.GGUF").write_bytes(b"model")
    private_key_marker = "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----"
    (tmp_path / "secret.txt").write_text(
        private_key_marker,
        encoding="utf-8",
    )

    problems = check_repository(tmp_path)

    assert any("forbidden local file: .ENV" in problem for problem in problems)
    assert any("model.ONNX" in problem for problem in problems)
    assert any("runtime.log.1" in problem for problem in problems)
    assert any("weights.GGUF" in problem for problem in problems)
    assert any("possible private key: secret.txt" in problem for problem in problems)


def test_repository_guard_allows_templates_and_excludes_transfer(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        (REPOSITORY_ROOT / "windows-client" / ".env.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "config.example.toml").write_text(
        (REPOSITORY_ROOT / "windows-client" / "config.example.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    transfer = tmp_path / "Transfer"
    transfer.mkdir()
    (transfer / ".env").write_text("secret=value", encoding="utf-8")

    assert check_repository(tmp_path) == []


def test_repository_guard_rejects_a_secret_hidden_in_a_template_comment(
    tmp_path: Path,
) -> None:
    template = (REPOSITORY_ROOT / "windows-client" / ".env.example").read_text(encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        f"# LIVE_TRANSLATOR_API_KEY=custom-provider-secret\n{template}",
        encoding="utf-8",
    )

    problems = check_repository(tmp_path)

    assert problems == ["unsafe environment template: .env.example"]


def test_repository_guard_rejects_a_non_placeholder_environment_template(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.example").write_text(
        "LIVE_TRANSLATOR_API_KEY=custom-provider-secret\n",
        encoding="utf-8",
    )

    problems = check_repository(tmp_path)

    assert problems == ["unsafe environment template: .env.example"]


def test_repository_guard_rejects_a_modified_configuration_template(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.example.toml").write_text(
        '[translation]\nendpoint = "https://real.example/v1/messages"\n'
        'api_key = "custom-provider-secret"\n',
        encoding="utf-8",
    )

    problems = check_repository(tmp_path)

    assert problems == ["unsafe configuration template: config.example.toml"]
