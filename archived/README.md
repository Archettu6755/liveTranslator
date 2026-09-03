# Live Translator V2

这是一个自用的 Windows 11 日语实时字幕工具。Windows 便携客户端采集系统音频、调用翻译 API 并显示字幕。Dolphin ASR 将运行在 Docker Desktop 的 WSL2 backend 中。

最重要的架构决定是：开发全部在 WSL2，运行仍分 Windows 和 WSL2 两侧。Windows 物理机不需要 Python、uv、Conda 或源码，只运行 CI 生成的 `LiveTranslator.exe`。WASAPI 和桌面窗口不能放进 Linux 容器，因此 localhost WebSocket 仍是必要边界。

开始新任务前先读 [AGENTS.md](AGENTS.md) 和 [LIVE_TRANSLATOR_V2_PLAN.md](LIVE_TRANSLATOR_V2_PLAN.md)。

## 当前状态

已实现并通过自动化源码检查：

- Python 3.12 Windows 客户端结构和锁文件。
- soxr 重采样、16 kHz 单声道 PCM16、100 ms 分帧和停止尾帧排空。
- ASR WebSocket client、fake ASR、严格事件解析和共享合同。
- Anthropic Messages API 兼容翻译 client。
- PySide6 控制窗、字幕状态和最多两条 final 的 overlay。
- 有界队列、丢帧状态、停止确认、尾帧排空和资源清理。
- `%LOCALAPPDATA%` 配置、严格配置字段、HTTPS 限制和脱敏轮转日志。
- 根目录测试隔离、敏感文件检查、`.gitignore` 和跨平台换行规则。
- Windows PyInstaller onedir 打包、冻结应用自检、运行时文件审计和 SHA-256 生成。
- Windows PowerShell 5.1 配置脚本及 `.env` ACL 创建、复查路径。

2026-07-31 在当前 Windows 迁移暂存机上的验证结果：

- 108 个测试通过，Ruff 检查和格式检查通过，Pyright strict 为 0 个错误。
- 锁文件离线检查、仓库敏感文件检查和源码 `--self-test` 通过。
- 本地便携包构建通过；冻结 EXE 分别使用 offscreen 和 Windows Qt platform 完成 `--self-test`。
- Windows PowerShell 5.1 配置和 ACL 测试通过，ZIP 内容与校验文件通过独立审计。

已实现但仍需 WSL、远程 CI 或干净目标机验证：

- WASAPI loopback 设备枚举与采集。
- 字体、拖动、透明度、置顶和全屏覆盖。
- `bash scripts/check.sh` 在真正的 WSL Linux checkout 中运行。
- GitHub Actions workflow 的首次远程 Linux 检查和 Windows artifact 构建。
- `.env` ACL 和便携包在无 Python 的干净 Windows 11 目标机上运行。

尚未实现或验证：

- Dolphin、VAD、`asr-service/`、Dockerfile 和 Compose。
- WSL2 Docker GPU 探针和真实 ASR 联调。
- 8GB 显存、RTF、延迟、两小时稳定性和游戏并行测试。
- V2 替换分支合并、首次远程 CI 和正式 Windows artifact 下载验证。

`Transfer/` 是废弃方案，只作本机参考。它被根 `.gitignore`、测试、安全扫描和代码审查排除，不应进入新仓库。

## 远端与迁移状态

V2 复用旧仓库 `git@github.com:Archettu6755/Transfer.git` 的历史和远端。`D:\\live-translator` 只用于完成首次替换提交，不是未来的开发 checkout。根目录的 Git 仓库不会跟踪本地 `Transfer/`；该目录仍保留旧代码供本机参考。

V2 替换分支合并到 `main` 后，应停止在 Windows 暂存目录继续开发，并按下一节在 WSL Linux 文件系统重新 clone。首次迁移期间已经检查提交索引，确认其中没有 `Transfer/`、`.env`、本地 `config.toml`、日志、模型、`build/`、`dist/`、`artifacts/` 或秘密值。

长期开发的提交前检查仍然从 WSL checkout 运行：

```bash
bash scripts/check.sh
```

## 新电脑上的开发方式

Windows 侧只安装 WSL2、Docker Desktop、NVIDIA 驱动和你选择的终端。Python 工具链装在 WSL 发行版中。

在 WSL shell 中建立唯一 checkout，不要使用 `/mnt/c` 或 `/mnt/d`：

```bash
mkdir -p ~/src
cd ~/src
git clone git@github.com:Archettu6755/Transfer.git live-translator
cd live-translator
```

Codex 或 Claude Code 也从这个 WSL shell 启动。不要让 Windows agent 和 WSL agent 同时编辑两份源码。

安装 uv 后运行统一检查：

```bash
bash scripts/check.sh
```

脚本会按 `windows-client/uv.lock` 建立 WSL 开发环境，并运行 pytest、Ruff、Pyright 和仓库敏感文件检查。它不下载模型，也不需要 GPU、Docker、真实 API key 或外部翻译服务。

不要在 `Transfer/` 内执行新项目的 commit 或 push。

## 发布 Windows 客户端

WSL 不负责生成 Windows EXE。推送后由 `.github/workflows/ci.yml` 的 Windows runner 打包。Actions 页面提供名为 `LiveTranslator-windows-x64-package` 的外层 artifact ZIP。先解开外层 ZIP，里面才是：

```text
LiveTranslator-windows-x64.zip
LiveTranslator-windows-x64.zip.sha256
```

Windows 目标机先解开 Actions 外层 artifact，再校验内部应用 ZIP：

```powershell
Expand-Archive .\LiveTranslator-windows-x64-package.zip -DestinationPath .\download -Force
Set-Location .\download
$expected = (Get-Content .\LiveTranslator-windows-x64.zip.sha256).Split()[0]
$actual = (Get-FileHash .\LiveTranslator-windows-x64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'SHA-256 mismatch' }
Expand-Archive .\LiveTranslator-windows-x64.zip -DestinationPath .\app -Force
Set-Location .\app\LiveTranslator
```

当前 EXE 没有代码签名，首次下载可能触发 Mark-of-the-Web 或 SmartScreen。只在哈希和 workflow 来源都正确时放行，不要把警告当成已完成的签名验证。

进入解压出的 `LiveTranslator` 目录并创建本地配置：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\configure.ps1
notepad $env:LOCALAPPDATA\LiveTranslator\config.toml
notepad $env:LOCALAPPDATA\LiveTranslator\.env
```

必须替换示例 endpoint、模型名和 `replace-me` key。应用会在发出网络请求前拒绝这些占位值。

检查便携包后启动：

```powershell
.\LiveTranslator.exe --self-test
.\LiveTranslator.exe
```

目标机不运行 `uv sync`，也不需要源码 checkout。

## 运行时

未来 ASR 服务完成后，从 WSL checkout 启动容器：

```bash
docker compose up -d asr
```

Windows 客户端连接：

```text
http://127.0.0.1:9000/ready
ws://127.0.0.1:9000/v1/asr
```

Docker named volume 保存模型。音频通过 WebSocket 发送，不通过 Windows 和 WSL 共享目录。翻译 API key 不得放进 WSL、Compose 或容器。

ASR 服务目前尚不存在，所以上述 Compose 命令是后续目标，不是当前可运行命令。

## 配置和安全

Windows 本地状态位于：

```text
%LOCALAPPDATA%\LiveTranslator\config.toml
%LOCALAPPDATA%\LiveTranslator\.env
%LOCALAPPDATA%\LiveTranslator\logs\live-translator.log
```

远程翻译 endpoint 必须是 HTTPS。HTTP 只允许 loopback mock。ASR URL 只允许 loopback。HTTP client 禁用自动重定向和环境代理。

`configure.ps1` 把 `.env` ACL 限制为当前用户。只要该文件存在，应用启动时就会复查权限。日志按大小轮转，并遮蔽已知 API key 和 key header。不要分享完整日志；排障时只提供经过人工检查的最小脱敏片段。日志中出现请求 header、body、key 或字幕正文应视为缺陷。

仓库安全规则见 [SECURITY.md](SECURITY.md)。

## 目录

```text
live-translator/
├── .github/workflows/ci.yml       Linux 检查和 Windows 发布包
├── contracts/                     ASR v1 JSON Schema 与示例
├── scripts/                       WSL 检查和仓库安全检查
├── windows-client/                Windows 客户端源码、测试和打包脚本
├── AGENTS.md                      agent 工作规则
├── LIVE_TRANSLATOR_V2_PLAN.md     架构、阶段和验收条件
├── SECURITY.md                    密钥与发布安全
└── Transfer/                      废弃旧仓库，排除在 V2 外
```

## 下一步

先审核并合并 V2 替换分支，让 Linux 和 Windows CI 都通过。然后在目标设备的 WSL Linux 文件系统重新 clone，运行 `bash scripts/check.sh`，下载并检查第一份远程 Windows artifact。完成这些步骤后再做 Docker GPU 探针。探针通过前不要创建假的 ASR 服务骨架，也不要声称 Dolphin 或 8GB 显存已经验证。
