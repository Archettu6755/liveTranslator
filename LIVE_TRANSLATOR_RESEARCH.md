# Live Translator 研究记录

更新时间：2026-09-03

## 1. 这份文档的用途

旧的 V2 实现和配套文档已经移入 `archived/`。其中的 Windows 客户端、协议、测试和打包脚本仍可用于验证工程做法，但不再代表下一版产品方案。`Transfer/` 是更早的独立旧仓库，继续留在根目录并保持只读，也不属于下一版项目。

下一版仍面向个人使用：在 Windows 11 上捕获日语游戏、视频和直播音频，显示低延迟日文字幕，并调用用户自己的 Anthropic Messages API 兼容接口生成简体中文翻译。目标设备有 NVIDIA GPU，但显存只有 8 GB。

当前先研究两个问题：

1. 怎样得到低延迟、稳定、可翻译的流式 ASR 输出。
2. 怎样组织 Windows 客户端、字幕显示、翻译和 WSL2 ASR 服务。

## 2. 已归档方案的问题

归档方案的数据流如下：

```text
audio stream
    -> VAD waits for an utterance to end
    -> Dolphin decodes the complete utterance
    -> transcript.final
    -> translation API
    -> overlay
```

音频通过 WebSocket 连续发送，识别仍在一句话结束后才开始。连续讲话可能让字幕空白数秒。VAD 的静音阈值还会继续增加等待时间。这个方案可以充当离线准确率基线和最小产品实验，无法直接证明流式字幕体验成立。

VAD、识别提交和字幕分段也被绑在同一个边界上。三者回答的问题不同：

```text
VAD                 Is someone speaking?
ASR commit policy   Which prefix is unlikely to change?
subtitle segmenter  Which text is readable and ready for translation?
```

日语句尾、否定、助词和省略会改变前文含义。稳定的 ASR 前缀未必已经适合翻译。因此下一版需要单独的翻译和字幕分段器。

## 3. 流式 ASR 的两条路线

### 3.1 原生流式模型

RNN-T、Transducer、流式 CTC、cached Conformer、Zipformer 和 Streaming Paraformer 会保存编码器或解码器状态。每一块音频只处理一次或只处理有限上下文。这类模型通常有更低且更稳定的计算成本，也更容易控制首字延迟。

[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 提供 Online Transducer、Online Paraformer、Streaming Zipformer2 CTC 等运行接口，也有日语 Zipformer Transducer 的模拟流式示例。工程接口和状态管理值得参考。可用日语模型的领域匹配、准确率和热词能力仍要逐个验证。

[FunASR](https://github.com/modelscope/FunASR) 的 Streaming Paraformer 按 chunk 处理音频，通过 cache 保存跨 chunk 状态，并返回每个 chunk 的增量结果。它是研究缓存、lookback 和 endpoint 设计的直接材料。公开模型对动漫、VTuber 和游戏日语的效果不能从中文或普通语音结果推断。

原生流式模型适合长期产品路线。主要风险是日语模型选择少，动漫和游戏域的准确率可能低于强离线模型。

### 3.2 把离线模型改造成流式 pipeline

Whisper、Dolphin 和 Anime-Whisper 一类模型更擅长完整上下文。工程上可以维护滚动音频窗口，反复解码重叠音频，再决定哪些前缀可以提交。

[Whisper-Streaming](https://github.com/ufal/whisper_streaming) 使用 LocalAgreement。连续若干次解码得到相同前缀时，该前缀才成为不可变结果。对应论文报告了未切分长音频上的实时转录实验：[Turning Whisper into Real-Time Transcription System](https://aclanthology.org/2023.ijcnlp-demo.3/)。

[SimulStreaming](https://github.com/ufal/SimulStreaming) 在 LocalAgreement 之外加入 AlignAtt。AlignAtt 根据注意力位置限制当前可提交的内容，减少在音频末尾尚未说完整时生成错误词的机会。该项目还展示了如何把稳定源文本交给同时翻译模块。

[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) 把这些策略做成可运行服务。其前端协议区分已提交行和仍会变化的 buffer，并处理序号、重连、长会话 DOM 上限和停止后的最终排空。它适合作为 pipeline 和协议参考，不能直接证明其中某个模型适合 8 GB 显存和日语游戏音频。

离线模型流式化可以较快复用强日语模型，但会重复计算重叠窗口。窗口、步长、稳定策略和缓冲裁剪需要共同调节。短 chunk 容易切断词和上下文，长 chunk 又会增加延迟。

### 3.3 Dolphin 当前的位置

[Dolphin](https://github.com/DataoceanAI/Dolphin) 继续作为日语准确率候选。公开的 `dolphin-small` 是多语言模型，架构沿用 E-Branchformer 编码器和 Transformer 解码器。官方仓库目前公开的 streaming checkpoint 属于 Dolphin-CN-Dialect 系列，不能把它当作 `dolphin-small` 的日语流式版本。

因此 Dolphin 有两个用途：

- 对完整语句或较长窗口做日语准确率基线。
- 参加滚动重解码和稳定前缀实验。

是否把它用于最终产品，要看目标 GPU 上的首字延迟、重复解码成本、显存和专名准确率。

## 4. 建议的 ASR 事件模型

研究版协议应表达可变内容和不可变内容。建议先使用下面的概念，不急着固定 JSON 字段：

```text
session.started
hypothesis.updated     mutable text for immediate Japanese display
prefix.committed       append-only Japanese prefix
segment.committed      immutable translation unit
runtime.overloaded
session.stopped
error
```

每个事件至少携带：

- `session_id`
- 单调递增的 `seq` 或 `revision`
- `segment_id`
- 音频开始和结束时间
- 文本
- 是否允许后续修改

前端可以显示 mutable hypothesis，但只能把 committed segment 交给翻译。迟到结果按 `session_id + segment_id` 更新原位置。已经退出可见窗口的翻译结果直接丢弃。

如果 MVP 暂时只消费 final，服务内部仍应保留 hypothesis、stable prefix 和 segmenter 的概念。否则将来增加流式显示时会再次修改整个协议。

## 5. 翻译、上下文和术语

翻译请求不能阻塞 ASR。建议用有界队列和少量并发任务。队列拥塞时优先保留新字幕，并把丢弃情况显示为可观察状态。

一次 API 请求可以同时完成保守的日文纠错和中文翻译。内部保留三个字段：

```text
raw_asr
corrected_ja
translated_zh_cn
```

这样可以判断错误来自识别、纠错还是翻译。提示词必须要求模型只修复有上下文证据的识别错误，不补写音频中没有的内容。

可见字幕历史和语言上下文要分开保存。覆盖层只需两条字幕，翻译上下文可以保留最近 30 至 120 秒的日文。上下文应有时间和字符预算，不能无限增长。

术语表适合先服务翻译和纠错，再按 ASR backend 的能力提供热词。术语记录至少包含日文写法、读音、简体中文译名、类别和优先级。热词只传当前游戏和当前场景中高相关的少量词，避免过度 bias。大部分情况下无需先做专名微调。只有在固定测试集证明 prompt、hotword 和 LLM 纠错仍无法解决重复错误时，再评估 LoRA 或完整微调。

## 6. ASR 评测方式

单看整句 CER 会漏掉实时体验问题。研究数据应同时记录：

| 类别 | 指标 |
| --- | --- |
| 准确率 | raw CER、纠错后 CER、漏句率、专名正确率、关键语义错误率 |
| 流式体验 | first useful text latency、commit latency、revision rate、字符抖动率、final latency |
| 翻译 | committed JA 到 ZH 延迟、错误传播率、过度纠错率、迟到结果丢弃数 |
| 资源 | RTF、峰值显存、CPU、内存、两小时增长趋势、与游戏并行时的帧率影响 |

测试集需要包含干净短句、连续长语音、带 BGM 和音效的游戏片段、喊叫或笑声、专有名词密集片段和真实直播片段。Anime-Whisper 使用过的数据不能作为它自己的公平 held-out test。

8 GB 显存不能全部分给 ASR。游戏也要使用 GPU。研究阶段应先把 ASR 峰值目标设在约 4 至 4.5 GB，再用真实游戏并行测试修正。这个数字只是预算，当前没有实测证据。

## 7. 非 ASR 工程参考

### 7.1 Windows 覆盖层

[LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator) 与目标产品最接近。可借鉴的功能包括透明置顶窗口、点击穿透、拖动缩放、字体和背景设置、原文与译文顺序切换、描边和可配置显示句数。它的发布记录还说明了译文位置、描边和自动扩展窗口对减少字幕跳动的作用。下一版仍使用 Python 和 PySide6，只参考交互和视觉行为。

### 7.2 浏览器覆盖层和滚动策略

[Caption.Ninja](https://github.com/steveseguin/captionninja) 把采集或发布页面与覆盖层分开，通过 WebSocket 传递字幕。其覆盖层提供 `maxlines`、`maxage`、`showtime`、双语显示、CSS 样式和片尾式连续滚动。

游戏字幕适合固定窗口滚动。画面保留上一条和当前条。新 segment 到达时，当前条短距离上移并降低亮度，新字幕进入固定位置。连续像素滚动会让读者追着文字移动，更适合片尾字幕或提词器。

建议的第一版显示规则：

- 最多显示两条 segment。
- 中文译文在上，日文原文在下且字号较小。
- 当前条全亮，上一条降低亮度。
- 窗口底部锚定，内容增长时向上扩展。
- 从日文出现开始预留译文区域，翻译返回时不重新排布整块字幕。
- 使用 150 至 200 ms 的短动画，只在 segment 切换时执行。
- 6 至 8 秒没有新内容后自动隐藏。

Caption.Ninja 允许把 provider key 放在 URL 参数中。下一版不能复制这一做法。密钥不能进入浏览器地址、字幕事件或 WSL2。

### 7.3 字幕排版规则

[Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit) 的设置和自动断行代码适合作为排版参考。它支持按像素宽度断行、句末和逗号优先、禁止特定词后断行、下行略长、最大行数和阅读速度限制。

实时日中字幕应使用 `QFontMetrics` 测量实际宽度，不能只按 UTF-8 字节数截断。还要避免让 `、。，！？）》】` 等标点出现在行首。译文超过两行时，字幕分段器应该缩短 segment；渲染器只负责排版，不应擅自删除文字。

[libass](https://github.com/libass/libass) 提供了一套成熟的样式词汇，包括字体、字号、颜色、描边、阴影、对齐和安全边距。下一版可以定义一个较小的 `SubtitleStyle` 数据类来表达这些字段，无需嵌入 libass。

### 7.4 应用核心与界面交互

[fmadore/Live-translation 的架构文档](https://github.com/fmadore/Live-translation/blob/main/docs/architecture.md) 展示了一个有用的桌面应用边界。核心产生 caption、status 和 level 事件，控制窗口与字幕窗口消费同一套事件。确定性 demo 也走完全相同的显示路径。密钥留在核心，渲染窗口只获得完成显示所需的权限。

下一版可以在 Python 中采用同样的责任分配：

```text
AudioSource / demo source
        -> SessionController
        -> SubtitleReducer
        -> immutable SubtitleState
             -> ControlWindow
             -> SubtitleOverlay
```

控制窗和字幕窗先通过 Qt Signal 接收状态。这里不需要本地 HTTP 服务。字幕窗口只能调整位置、透明度、锁定和点击穿透，不能读取 API key，也不能直接启动翻译请求。

确定性 demo 很重要。它应发送预先写好的日文 final、延迟到达的译文、超长文本、翻译错误、断线和过载事件。这样可以在 ASR 服务尚未完成时检查真实字幕窗口和冻结 EXE。

如果以后需要 OBS browser source，可以在 Windows 核心增加一个可选的只读 WebSocket 输出器。它只监听 `127.0.0.1`，使用每次启动生成的随机令牌，并只发送经过长度限制的纯文本事件。浏览器端使用 `textContent` 渲染，禁止把字幕拼进 `innerHTML`。翻译密钥和控制命令不进入这个接口。

[LiveKit transcription-frontend](https://github.com/livekit-examples/transcription-frontend) 和 [live-translated-captioning](https://github.com/livekit-examples/live-translated-captioning) 可以用于研究浏览器组件如何消费 segment 事件。LiveKit 的房间、令牌和服务端依赖对当前单机产品过重，不列入实现计划。

## 8. Windows 与 WSL2 的边界

### 8.1 开发位置

长期开发 checkout 放在 WSL2 的 Linux 文件系统，例如 `~/src/live-translator`。Git、uv、Python、Codex、Claude Code 和 Docker CLI 都从 WSL shell 启动。不要把活跃 checkout 放在 `/mnt/c` 或 `/mnt/d`，也不要维护 Windows 和 WSL 两份源码。

这条规则解决开发环境一致性和 Windows 挂载目录的文件性能问题。它不要求最终进程全部运行在 Linux。

### 8.2 运行位置

推荐的运行结构如下。Docker 官方说明 [Windows GPU 容器只支持 WSL2 backend](https://docs.docker.com/desktop/features/gpu/)，因此模型容器放在这里符合平台能力边界。

```text
Windows 11
  LiveTranslator.exe
    - WASAPI loopback capture
    - resampling and bounded audio queues
    - ASR WebSocket client
    - translation API and API key
    - control window and subtitle overlay
             |
             | 127.0.0.1 WebSocket, PCM16 and ASR events
             v
WSL2 Docker backend
  ASR service
    - VAD or speech gating
    - streaming ASR pipeline
    - model and CUDA runtime
    - model cache in a Docker named volume
```

音频通过 localhost WebSocket 在内存中传输，不经过共享目录，也不使用 Windows bind mount。Windows 与 WSL2 的文件交换性能不会进入音频热路径。

目标 Windows 机器不需要安装 Python、uv 或 Conda。GitHub Actions 的 Windows runner 把客户端构建为 PyInstaller onedir ZIP，包内自带 Python 运行时和依赖。用户只需解压和运行 Windows 程序。

### 8.3 为什么不把运行时全部放进 WSL2

Windows 游戏和播放器的系统音频由 [WASAPI loopback](https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording) 捕获。该接口直接从 Windows render endpoint 取得系统混音。[WSLg](https://github.com/microsoft/wslg) 提供的是由 Weston、FreeRDP 和 PulseAudio 组成的 Linux GUI 与音频集成层，不能替代这条原生 Core Audio 捕获路径。

字幕窗口还需要稳定的 Windows 置顶、无焦点显示、点击穿透、多显示器、DPI 和全屏游戏交互。原生 PySide6 Windows 进程可以直接使用这些窗口能力。WSLg 窗口经过 Linux compositor 和 RDP/Weston 集成，增加了无法控制的窗口层级和输入行为。

翻译 API key 的持久位置也在 Windows 用户目录，并由 Windows ACL 保护。把翻译客户端移进 WSL2 会改变已经选定的密钥边界，还会让配置、日志和凭据跨系统流动。

全部运行在 WSL2 只有在音频源也来自 Linux、字幕通过普通浏览器页面显示、并且接受把密钥放入 Linux 环境时才合理。当前产品的音频源和覆盖层都属于 Windows，因此没有这项收益。

## 9. 当前结论

开发全部在 WSL2。运行时只把 ASR 和模型部署到 WSL2 Docker，音频采集、翻译和 GUI 留在 Windows 便携客户端。

接下来先做 ASR 研究，不恢复归档方案的功能开发。推荐顺序如下：

1. 在目标设备确认 Docker 容器能看到 NVIDIA GPU，并记录空载显存。
2. 建立一小套真实日语游戏和 VTuber 连续音频测试集。
3. 测试一个原生流式日语模型和一个离线模型流式化 pipeline。
4. 统一输出 hypothesis、committed prefix 和 segment，并测字符抖动与提交延迟。
5. 用确定性事件实现独立 SubtitleReducer 和覆盖层 demo。
6. ASR 路线有测量结果后，再决定模型、协议字段和翻译 segmenter。

## 10. 尚未验证

以下项目目前没有真实运行证据：

- 目标设备的 WSL2 GPU passthrough。
- Dolphin、FunASR、sherpa-onnx 或 Whisper 流式 pipeline 在该设备上的可运行性。
- 8 GB 显存下与实际游戏并行运行的资源占用。
- 日语动漫、VTuber 和游戏音频上的准确率、延迟和稳定性。
- Windows 便携客户端与未来 ASR 服务的端到端链路。

任何模型选择都应等基准结果出来后再固定。
