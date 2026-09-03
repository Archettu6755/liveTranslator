# AGENTS.md

本文件适用于仓库根目录及其子目录，但不适用于 `Transfer/`。它规定项目的固定架构、开发位置、平台边界、验证要求和交接格式。

## 1. 资料优先级

按以下顺序判断任务：

1. 用户当前请求。
2. 本文件。
3. `LIVE_TRANSLATOR_V2_PLAN.md`。
4. `contracts/`、源码和测试所证明的当前行为。
5. `Transfer/` 中的旧实验记录。

文档与代码冲突时，不要猜测哪一边正确。先查测试和实际运行结果，再修正文档或实现。

## 2. 固定开发和运行拓扑

长期开发环境只有一份源码，必须位于 WSL2 的 Linux 文件系统，例如 `~/src/live-translator`。Codex、Claude Code、Git、uv、Python、编辑器后端和 Docker CLI 都从 WSL shell 启动。不要把活跃 checkout 放在 `/mnt/c`、`/mnt/d` 或其他 Windows 挂载目录，也不要维护 Windows 与 WSL 两份 checkout。

远端尚未建立前，当前 Windows 工作区可以只作为一次性迁移暂存区，用于完成审查、初始 commit 和 push。它不是长期开发 checkout。远端可用后，停止在该目录继续功能开发，并在 WSL Linux 文件系统重新 clone。

目标 Windows 物理机不安装 Python、uv、Conda、编译器或项目源码。Windows 只运行由 Windows CI 构建的便携客户端。客户端使用 PyInstaller onedir ZIP，解压即可运行。

运行时仍然是两个隔离组件：

| 位置 | 组件 | 职责 |
| --- | --- | --- |
| Windows 11 | `LiveTranslator.exe` | WASAPI loopback、重采样、ASR WebSocket client、翻译、状态和 PySide6 字幕窗口 |
| WSL2 的 Docker Desktop backend | ASR 容器 | VAD、Dolphin、CUDA、模型缓存、`/health`、`/ready` 和 WebSocket 服务 |

两侧只通过 `127.0.0.1` 上的 HTTP/WebSocket 通信。音频不得通过共享文件或 bind mount 传递。模型缓存放在 Docker named volume 中。翻译 API key 只留在 Windows 用户目录，不能进入 WSL、Compose 或容器。

不要把“全部在 WSL 开发”误写成“Windows 客户端也在 Linux 运行”。WASAPI 和原生桌面窗口要求客户端在 Windows 进程中运行。

## 3. 产品范围

项目供个人在 Windows 11 上使用，只支持日语语音到简体中文字幕。

| 项目 | 固定选择 |
| --- | --- |
| 源语言 | `ja` |
| 目标语言 | `zh-CN` |
| Windows 客户端 | Python 3.12、PySide6、PyAudioWPatch、soxr |
| 音频来源 | WASAPI loopback |
| ASR 通信 | localhost WebSocket |
| ASR 模型 | `DataoceanAI/dolphin-small` |
| ASR 环境 | Docker Desktop、WSL2、NVIDIA GPU |
| 翻译 | 用户自建的 Anthropic Messages API 兼容接口 |
| 字幕事件 | 只消费 final，不定义或显示 partial |

除非用户先改变范围，不增加多模型切换、CPU ASR、云端 ASR、浏览器扩展、OBS 插件、TTS、说话人分离、人声分离、字幕历史、术语表编辑器、自动更新或安装器。

## 4. 目录和 Git 边界

`windows-client/` 是 Windows 客户端源码。`contracts/` 是 Windows 客户端与未来 ASR 服务共享的协议事实来源。`.github/workflows/ci.yml` 负责 Linux 检查和 Windows 打包。`scripts/` 只放跨仓库检查或开发脚本。

`Transfer/` 是废弃旧仓库，带独立 `.git`。它默认只读，不属于新产品，不是依赖，也不参加根仓库的 Git、测试、格式化、类型检查、安全扫描或代码审查。不要读取其中的 `AGENTS*.md` 来控制新项目。只有用户明确要求处理旧仓库时才进入该目录。

执行 Git 命令前先确认当前目录和根目录是否已有 `.git`。不要把 `Transfer/` 的提交、分支、远端或嵌套历史当成新项目状态。根仓库的 `.gitignore` 必须继续排除 `/Transfer/`。

## 5. 平台能力门槛

### 5.1 WSL 开发机

在 WSL 的仓库根目录使用：

```bash
bash scripts/check.sh
```

该命令安装锁定的开发依赖并运行 pytest、Ruff、Pyright 和仓库安全检查。不要为运行这些检查而在 Windows 物理机安装 Python。

WSL 可以开发和测试平台无关的 Python、协议、mock、翻译和控制逻辑。WASAPI、Windows ACL、Qt 桌面交互和 PyInstaller Windows 产物必须在 Windows 环境验证。不要从 Linux 交叉编译或冒充已验证的 Windows EXE。

### 5.2 Windows CI 和目标机

Windows GitHub Actions runner 是发布构建环境。它必须从锁文件安装依赖，重新运行测试、Ruff、Pyright 和安全检查，构建 onedir 包，检查必需 DLL、Qt platform plugin、CA bundle 和敏感文件，再执行冻结 EXE 的 `--self-test`。

目标 Windows 设备只下载 CI 产物、校验 SHA-256、解压、运行 `configure.ps1`、填写本地配置并启动 EXE。目标机没有源码和 Python 环境是正常状态。

### 5.3 GPU 门槛

开始 `asr-service/`、Dolphin、CUDA、VAD 或 GPU Compose 工作前，必须在目标 WSL2 设备确认 Docker 容器能看到 NVIDIA GPU。没有这个条件时，可以继续客户端、合同、文档和 CI 工作，但不要下载模型、创建假的模型适配器、提交空 Dockerfile，或声称 Dolphin、Docker GPU、8GB 显存已经验证。

只有真实运行过相应命令，才能报告以下项目已验证：WSL2 GPU passthrough、Dolphin 加载、模型缓存、RTF、显存、延迟、长时间稳定性和游戏并行运行。

## 6. 音频和 ASR 合同

Windows 客户端发出的音频固定为：

| 字段 | 值 |
| --- | --- |
| sample rate | `16000` |
| channels | `1` |
| encoding | `pcm_s16le` |
| chunk duration | `100 ms` |
| chunk size | `3200 bytes` |
| language | `ja` |

WASAPI 回调只把原始数据放入有界队列。重采样、WebSocket I/O 和日志不得阻塞回调线程。停止采集时必须排空已捕获的原始块和重采样尾帧，再发送 `stream.stop`。

默认地址为 `ws://127.0.0.1:9000/v1/asr` 和 `http://127.0.0.1:9000/ready`。ASR URL 只允许 loopback。共享 JSON Schema 和示例位于 `contracts/`，修改协议时必须同时更新模型、解析器、示例、Schema 和合同测试。

协议规则：

- 客户端先发送 `stream.start`，收到 `stream.ready` 后才发二进制音频帧。
- 每个服务事件都有非空 `session_id`。
- `transcript.final.seq` 在单个 session 内严格递增。
- 客户端忽略其他 session、重复 seq 和倒退 seq。
- 接收协程与发送路径独立，生命周期确认不能被业务事件队列阻塞。
- 不定义 partial。
- `stream.stop` 不等于连接关闭。客户端等待 `stream.stopped` 或明确超时。
- `runtime.overloaded` 和本地队列丢弃必须可观察。
- `error` 使用稳定错误码和可读说明，不把容器 traceback 发给 UI。

## 7. Python 责任边界

本轮重构重新评估后，当前实现继续使用以下薄 Protocol。它们用于隔离硬件、网络和 UI，方便在 WSL 与 CI 中做确定性测试，不是为多 provider 或跨 checkout 设计的插件框架。名称和签名可以重构，但这些责任不能重新耦合：

```python
class AudioSource(Protocol):
    def start(self) -> None: ...
    def read_chunk(self) -> AudioChunk | None: ...
    def stop(self) -> None: ...
    def snapshot_stats(self) -> AudioSourceStats: ...

class AsrClient(Protocol):
    async def probe_ready(self) -> bool: ...
    async def connect(self) -> None: ...
    async def start_stream(self, request: StartStream) -> None: ...
    async def send_audio(self, chunk: AudioChunk) -> None: ...
    def events(self) -> AsyncIterator[AsrEvent]: ...
    async def stop_stream(self) -> None: ...
    async def close(self) -> None: ...

class TranslatorClient(Protocol):
    async def translate(self, request: TranslationRequest) -> TranslationResult: ...
    async def close(self) -> None: ...

class SubtitleSink(Protocol):
    def set_state(self, state: SubtitleState) -> None: ...
    def clear(self) -> None: ...
```

`AsrClient` 不得导入 Dolphin、Torch、Docker SDK 或 WSL 模块。会话控制器只依赖职责接口和配置对象。GUI 线程不执行音频处理、WebSocket I/O 或 HTTP 请求。不要提前增加 provider 插件或模型 backend 抽象。

## 8. 翻译和密钥安全

翻译使用完整可配置 endpoint，契约为 Anthropic Messages API：

```http
content-type: application/json
x-api-key: {api_key}
anthropic-version: 2023-06-01
```

请求体使用顶层 `system` 和 `messages`，响应拼接所有 `type == "text"` 的 content block。不使用 OpenAI Chat Completions，不做 token streaming，不为修复格式自动重试。

远程翻译 endpoint 必须使用 HTTPS。HTTP 只允许 loopback mock。禁止重定向和环境代理。翻译失败时保留日文 final，并继续处理后续 ASR 事件。

API key 的唯一持久位置是 `%LOCALAPPDATA%\LiveTranslator\.env`。`configure.ps1` 必须收紧该文件 ACL。真实 key 不得进入 Git、TOML、命令行、WSL、Compose、容器、构建产物、日志、异常文本或字幕。日志写入 `%LOCALAPPDATA%\LiveTranslator\logs`，使用轮转和密钥遮蔽，不记录请求 header 或 body。

示例 endpoint、模型名和 `replace-me` key 必须在发出请求前被配置加载器拒绝。

## 9. 发布和 CI

Windows 客户端只能在 Windows runner 上打包。固定产物是 `LiveTranslator-windows-x64.zip` 和对应 `.sha256` 文件。不要提交 `dist/`、`artifacts/`、虚拟环境或构建缓存。

发布检查至少包括：

- `LiveTranslator.exe`、`qwindows.dll`、PyAudioWPatch、soxr 和 certifi CA bundle 存在。
- 产物不含 `.env`、`config.toml`、私钥、证书私钥或模型文件。
- CA bundle 是唯一允许的 PEM，且只含证书。
- 冻结 EXE 的 `--self-test` 通过。
- GitHub Actions 使用完整 commit SHA 固定第三方 action，并禁用 checkout 凭据持久化。

## 10. 编码和审查

- 主产品只使用 Python。
- 使用类型标注、dataclass 或小型不可变模型表达协议和状态。
- 队列必须有界，满队列时产生可观察状态。
- 超时、取消、断线、重复 stop 和资源清理必须有确定行为。
- UI 只显示稳定消息。技术 traceback 只进脱敏诊断日志。
- 外部服务和硬件路径必须有确定性的 fake、合同测试和失败路径测试。
- 测试不得需要真实 API key 或外部网络。
- 修改应小而明确，不为了目录完整度加入未验证框架。

完成大型改造或准备推送前，逐个审查 `Transfer/` 之外的源码、测试、脚本、workflow 和配置。检查安全边界、停止路径、资源释放、线程边界、队列满、协议拒绝路径、平台条件和文档真实性。审查结论必须进入完成报告。

## 11. 验证和报告

WSL 基线命令是：

```bash
bash scripts/check.sh
```

Windows CI 还必须运行 `windows-client/packaging/build.ps1`。PowerShell 脚本改动后至少做语法解析；只有 Windows 构建和冻结 self-test 实际通过，才能报告发布包已验证。

每次完成报告使用：

```text
Changed:
- files or areas

Verified:
- exact command and result

Reviewed:
- reviewed scope and findings

Not verified here:
- platform, GPU, Docker, real API, or interactive checks not actually run

Next:
- remaining in-scope work
```

没有真实证据时，不使用“ASR 已验证”“Docker 可运行”“8GB 显存达标”“Windows 发布包可用”等表述。
