# Security

Live Translator is a personal desktop tool, not a multi-user service. Its main security boundary is keeping the translation API key on the Windows side and keeping every ASR endpoint on loopback.

## API key

Store the key only in:

```text
%LOCALAPPDATA%\LiveTranslator\.env
```

`configure.ps1` creates the file and replaces inherited ACL rules with one allow rule for the current Windows user. Whenever the file exists, the client checks that ACL at startup and reports a warning when it cannot prove the file is private.

The process environment variable `LIVE_TRANSLATOR_API_KEY` can override the file. Do not put the key in `config.toml`, WSL environment files, shell history, Docker Compose, container variables, source code, test fixtures, command-line arguments or screenshots.

The shipped `replace-me` value, placeholder model and `.invalid` endpoint are rejected before any HTTP request. Configuration tables reject unknown fields, including `translation.api_key`.

## Network boundaries

ASR WebSocket and readiness URLs accept loopback hosts only. The intended service is `127.0.0.1:9000`, published by Docker Desktop from WSL2.

Remote translation endpoints require HTTPS. Plain HTTP is accepted only for loopback tests. The translation client disables redirects and ignores proxy environment variables so a configured key is not forwarded to an unexpected origin.

The ASR container never receives the translation key. It should publish port 9000 only on `127.0.0.1`.

## Logs

Diagnostic logs are written to:

```text
%LOCALAPPDATA%\LiveTranslator\logs\live-translator.log
```

Logs rotate by size. The formatter replaces the configured key and recognized API key header values. Application code must not log HTTP request headers, request bodies, full configuration objects or subtitle payloads.

Redaction is a last line of defense. Do not share a complete log. For troubleshooting, provide only the smallest useful excerpt after checking it manually because endpoints, file locations and unexpected third-party exception text can still identify the machine or service. Subtitle text or request content in a log is a defect.

## Repository and artifacts

`.gitignore` excludes local configuration, credentials, model weights, caches, build output and `Transfer/`. `scripts/check_repository.py` rejects known secret files, private-key markers, common API key forms and model artifacts. Run it through `bash scripts/check.sh` before every push.

The Windows packaging script rejects `.env`, `config.toml`, private-key files, extra PEM files and model weights. The only permitted PEM is certifi's certificate-only CA bundle. GitHub Actions dependencies are pinned to full commit SHAs.

Do not rely on `.gitignore` after a secret has been staged or committed. Inspect the index and artifact contents before publishing.

## If a key leaks

1. Revoke or rotate the key at the translation provider immediately.
2. Remove it from the working tree, Git index, CI logs and published artifacts.
3. Treat Git history as exposed until it has been cleaned and every remote copy has been handled.
4. Run the repository guard again and inspect the Windows artifact.
5. Add a regression test for the path that allowed the leak.

Do not paste the leaked value into an issue or commit message while documenting the incident.
