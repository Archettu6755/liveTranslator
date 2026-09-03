# Live Translator Windows 客户端

这个目录的发布产物是自包含的 Windows 11 客户端。它采集 WASAPI loopback 音频，连接本机 ASR WebSocket，调用 Anthropic Messages API 兼容翻译服务，并用 PySide6 显示字幕。

发布包不包含 ASR 模型、CUDA、Docker 或 Python 开发环境。目标 Windows 设备不需要安装 Python、uv 或 Conda。

## 首次使用

从 GitHub Actions 下载名为 `LiveTranslator-windows-x64-package` 的 artifact。浏览器得到的是外层 ZIP，解开后才会看到应用 ZIP 和 `.sha256` 文件。校验内部应用 ZIP 的 SHA-256，再解压并进入 `LiveTranslator` 目录。

运行配置脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure.ps1
```

当前 EXE 没有代码签名。首次下载可能触发 Windows SmartScreen。先确认 artifact 来自预期 commit 并校验 SHA-256，再决定是否放行。不要对来源不明的 ZIP 绕过警告。

脚本创建：

```text
%LOCALAPPDATA%\LiveTranslator\config.toml
%LOCALAPPDATA%\LiveTranslator\.env
```

它还会把 `.env` 的 ACL 限制为当前 Windows 用户。已有文件默认不会覆盖。只有确定要恢复模板时才使用 `configure.ps1 -Force`。

编辑 `config.toml`：

```toml
[asr]
ws_url = "ws://127.0.0.1:9000/v1/asr"
ready_url = "http://127.0.0.1:9000/ready"
connect_timeout_s = 5.0
stop_timeout_s = 5.0

[translation]
endpoint = "https://provider.invalid/v1/messages"
model = "replace-with-your-model"
anthropic_version = "2023-06-01"
max_tokens = 256
timeout_s = 4.0

[audio]
# device_index = 0
```

再编辑 `.env`：

```text
LIVE_TRANSLATOR_API_KEY=replace-me
```

把等号右侧的 `replace-me` 换成真实 key。还必须替换 `.invalid` endpoint 和占位模型名。客户端会在网络请求前拒绝原始占位值。

## 启动前检查

在 PowerShell 运行冻结环境 self-test：

```powershell
& .\LiveTranslator.exe --self-test
if ($LASTEXITCODE -ne 0) { throw "Self-test failed: $LASTEXITCODE" }
```

该检查加载 Qt、PyAudioWPatch、soxr、NumPy 和 HTTPS CA bundle，并做一次离屏窗口和重采样 smoke test。它不连接 ASR 或翻译 API。

没有 ASR 服务时可以检查界面：

```powershell
.\LiveTranslator.exe --demo
```

点击 Start 后应显示一条日文和中文 mock 字幕。Demo 不连接网络，也不能证明 WASAPI、Dolphin 或真实翻译可用。

## 正常运行

先从 WSL shell 启动未来的 ASR 容器，并确认：

```text
http://127.0.0.1:9000/ready
```

返回 ready 后，在 Windows 启动：

```powershell
.\LiveTranslator.exe
```

选择 loopback 设备并点击 Start。客户端发送固定的 16 kHz、单声道、PCM16、100 ms 二进制帧，只显示 `transcript.final`。

当前源码仓库还没有 ASR 服务。只有客户端发布包和 demo 时，正常模式会显示 ASR not ready，这是预期结果。

## 网络和密钥边界

- ASR WebSocket 和 ready URL 只允许 loopback。
- 远程翻译 endpoint 必须是 HTTPS。HTTP 只允许 loopback mock。
- HTTP client 不跟随重定向，也不读取系统代理环境变量。
- API key 只放在 Windows 用户目录的 `.env` 或进程环境变量中。
- 不要把 key 放进 `config.toml`、WSL、Docker、Compose、命令行或截图。
- 配置表出现未知字段会被拒绝，避免拼写错误或把 key 放错文件。

诊断日志位于：

```text
%LOCALAPPDATA%\LiveTranslator\logs\live-translator.log
```

日志按大小轮转并遮蔽已知 key。它不记录翻译请求 header、body 或字幕正文。不要分享完整日志；排障时只提供经过人工检查的最小脱敏片段。日志中出现 key 或字幕正文应视为缺陷。

## 字幕行为

字幕窗口最多保留当前 final 和上一条 final。日文先出现，中文在翻译完成后更新同一个 segment。翻译超时或失败不会停止后续日文字幕。

控制窗可以选择音频设备、锁定字幕位置和调整背景透明度。字幕窗口支持拖动并保存位置，长时间没有更新时会自动隐藏。

源码开发说明位于仓库根 README。发布目录不包含开发脚本，目标 Windows 设备也不需要 uv。
