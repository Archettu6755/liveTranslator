# Transfer 实时字幕产品讨论总结

> 范围：仅总结产品与工程实践，不包含科研 / 发 paper 相关讨论。

## 1. 产品目标

Transfer 的目标应从“句子结束后尽快得到日文与中文字幕”，调整为：

> **对连续系统音频进行低延迟增量日语识别，在说话过程中持续提供稳定的日文结果，并利用强 LLM API 对稳定内容进行保守纠错、上下文消歧和中文翻译。**

目标场景主要是：

- 日语 VTuber / 游戏直播；
- 游戏、视频等连续系统音频；
- Windows 11 桌面字幕覆盖；
- 本地或服务器 ASR 均可；
- LLM 使用高性能 API，不要求本地部署。

Windows 采集 / GUI、WSL2 / Docker、localhost WebSocket、日志、安全、打包等 V2 工程结构基本可以保留，真正需要重构的是 **ASR → 上下文 → LLM → 字幕** 这一条算法链。

## 2. V2 当前最主要的设计缺陷

### 2.1 目前并不是真正的 streaming ASR

V2 实际是：

```text
音频流
  ↓
VAD 等待一句结束
  ↓
Dolphin 对整句离线解码
  ↓
transcript.final
  ↓
LLM 翻译
```

虽然音频通过 WebSocket 流式发送，但识别仍以完整语句为单位。

主要问题：

- 连续讲话 8–12 秒时，用户可能一直看不到字幕；
- 700 ms 静音端点进一步增加延迟；
- “说话结束 → final”的延迟指标会掩盖真实的感知等待时间；
- VAD 停顿边界并不等于语言句子或适合翻译的字幕边界。

因此下一版应改为真正的增量识别：

```text
audio
  ↓
Streaming ASR
  ├─ partial
  ├─ stable / committed prefix
  └─ final
```

### 2.2 ASR 协议信息过少

当前主要只有：

```text
text
audio_start_ms
audio_end_ms
decode_ms
```

后续至少应考虑支持：

```text
partial
stable_prefix / committed text
word timestamps
confidence（若 backend 能提供）
N-best / alternatives（若 backend 能提供）
revision / segment id
```

其中最重要的是：

> **mutable partial + immutable committed prefix**

因为 streaming 字幕必须允许前端文字变化，但不能频繁倒退、跳动。

### 2.3 VAD 不应直接决定字幕和翻译单位

应拆成三个概念：

```text
VAD / speech gating
        ↓
ASR incremental decoding
        ↓
Translation / Subtitle Segmenter
```

VAD 只回答“现在有没有人在说话 / 是否可能到达 endpoint”。它不能可靠判断“这一段日语现在是否已经形成一个可以独立翻译的语义单元”。

尤其日语的句尾、否定、助词等可能改变前文含义，因此：

```text
ASR stable prefix ≠ translation-ready prefix
```

需要一个单独的字幕 / 翻译分段策略。

## 3. ASR 的目标不应是“做到近乎完美”

动漫、VTuber、游戏直播属于较困难的 ASR 场景：

```text
语音
+ BGM
+ 游戏音效
+ 喊叫 / 笑声 / 喘息
+ 非标准口语
+ 游戏专有名词
+ 网络简称 / 黑话
```

因此不应把产品成立的前提设成“先把 ASR CER 压到非常低，再开始翻译”。更合理的思路是：

> **把 ASR 视为有噪声的语言观测，然后尽量阻止 ASR 错误传播成最终翻译错误。**

产品真正关心的是：

```text
audio
  ↓
reasonable streaming ASR
  ↓
error recovery
  ↓
correct semantics
```

而不只是 CER 本身。

## 4. LLM 应从“翻译器”升级为 Language Processor

V2 当前基本是：

```text
Japanese final
  ↓
LLM translation
  ↓
Chinese
```

更合理的是一次 API 请求同时完成：

```text
raw ASR
+ recent Japanese context
+ game / session glossary
+ entity information
(+ N-best / confidence)
        ↓
强 LLM API
        ↓
corrected Japanese
+ Chinese translation
```

建议内部始终保留三层结果：

```text
raw_asr
corrected_asr
translation
```

这样出错后可以判断究竟是：

- ASR 听错；
- LLM 纠错纠坏；
- 翻译错误。

不建议：

```text
ASR
→ 纠错 LLM
→ 翻译 LLM
```

因为会多一次完整网络调用和推理延迟。

建议：

```text
ASR
→ 一次 LLM：纠错 + 上下文消歧 + 翻译
```

这样相较原 V2，本质上仍只有一次必须等待的 LLM API。

## 5. LLM 必须异步，不能阻塞 ASR

推荐数据流：

```text
                     ┌─ partial Japanese → UI
audio → Streaming ASR
                     └─ stable Japanese
                              ↓
                    Translation Segmenter
                              ↓
                     LLM async job #N
                              ↓
                   corrected JA + ZH
                              ↓
                    attach to segment #N
```

关键原则：

- ASR 永远继续运行；
- LLM 慢不能阻塞识别；
- LLM 允许少量并发，例如 2–3 个 in-flight；
- 每个请求绑定 segment id；
- 晚到结果只能更新对应 segment；
- 已经过时的翻译应直接丢弃，而不是补刷旧字幕。

实时字幕更适合：

> **freshness-first，而不是保证历史每一句最终全部翻译完成。**

## 6. 上下文不能再只保留两条字幕

当前“两条可见字幕”适合作为 UI 状态，但不应等同于语言上下文。

建议拆成：

```text
Overlay history:
    最近 2 条

Recent transcript context:
    最近约 30–120 秒日文

Session / entity memory:
    当前主播
    当前游戏
    人物
    地名
    Boss
    技能
    装备
    已确认术语
```

优先让 LLM 使用原始 / 修正后的日语上下文，而不是依赖前一句中文翻译，以减少翻译失败后的错误级联。

## 7. 游戏专有名词应成为系统一级能力

对 VTuber 场景，游戏术语通常比泛动漫词汇更重要。

应增加 **Game / Session Profile**，例如：

```yaml
game: Elden Ring

entities:
  - ja: ラダーン
    reading: ラダーン
    zh_cn: 拉塔恩
    category: character
    priority: high
```

同一份 glossary 同时服务：

```text
Game Profile
   ├─→ ASR contextual biasing / hotwords
   └─→ LLM correction + translation
```

即形成两层防线：

1. 尽量让 ASR 一开始就识别正确；
2. 即使 ASR 有轻微错误，LLM 仍可根据术语表和上下文恢复正确语义。

但不应把整个游戏 Wiki 全部永久塞进 hotword list，因为会造成 over-biasing。更适合分层：

```text
Global
Game
Recent
Active
```

只把当前高相关实体放入 ASR bias list。

## 8. ASR backend 不应再固定为 Dolphin-small

Dolphin 可以保留为候选，但应从“架构固定选择”降级为：

> **可替换 ASR backend 之一。**

后续应优先测试：

- 原生 streaming RNN-T / Transducer；
- cached / chunked Conformer / FastConformer；
- Zipformer；
- Whisper 的 streaming adaptation；
- Dolphin / Anime-Whisper 等强日语离线模型作为 accuracy baseline；
- 服务器或远程 ASR。

产品接口应抽象成：

```text
ASRBackend
  ↓
partial / stable / final
```

未来可以自由替换本地、服务器或云端模型，而不改变上层字幕与 LLM 逻辑。

## 9. 评测指标需要重写

原 V2 的：

```text
RTF P95
说话结束 → final
VRAM
```

仍可保留，但不能作为主要用户体验指标。

更应该测：

### ASR 质量

```text
raw CER
corrected CER
漏句率
专有名词正确率
关键语义错误率
```

### Streaming 体验

```text
first useful text latency
token / character emission delay
stable latency
revision / churn rate
final latency
```

### 翻译体验

```text
stable Japanese → Chinese latency
ASR error → translation error 的传播率
LLM over-correction rate
```

### 系统

```text
RTF
GPU / VRAM
长时间稳定性
与游戏同时运行时的资源竞争
```

## 10. Anime-Whisper 数据集的合理用途

`Galgame_Speech_ASR_16kHz` 数据很大，没有必要整体下载或训练。

更适合从中构造固定的小型 evaluation suite，例如：

```text
isolated:
    ~2000 utterances / 约 3 h

pseudo-stream:
    ~1 h

hard-stream:
    ~30 min

noisy pseudo-stream:
    ~30–60 min

real continuous VTuber / game:
    ~1–2 h
```

用途：

- 比较不同 ASR backend；
- 测日语动漫 / 游戏式语音识别；
- 测长短句；
- 测 streaming endpoint / stable output；
- 测 BGM / SFX 干扰；
- 测整体产品链。

注意 Anime-Whisper 本身在该大数据集上训练过，因此该数据子集不能作为 Anime-Whisper 的公平 held-out test。

最终仍需要少量真正连续的 VTuber / 游戏素材作为产品级验收数据。

## 11. 值得参考的开源项目

### LiveTranslate

与 Transfer 产品形态非常接近：

```text
Windows system audio
→ VAD
→ 多种 ASR
→ LLM
→ overlay
```

尤其值得参考实际产品功能、远程 GPU ASR、Anime-Whisper 接入、LLM 翻译等工程选择。

### WhisperLiveKit

更值得参考真正 streaming 的处理逻辑：

- partial；
- stable / LocalAgreement；
- continuous decoding；
- simultaneous translation；
- 字幕稳定策略。

### SimulStreaming

更接近先进的：

```text
streaming ASR
→ stable source
→ context-aware LLM simultaneous translation
```

适合参考“什么时候 commit ASR”“什么时候开始翻译”。

### sherpa-onnx / FunASR 等

适合作为原生 streaming ASR backend 和工程接口参考。

## 12. 对个人开发最现实的目标

不应追求：

> “做一个任意语言、任意直播、效果达到大厂会议软件级别的通用实时翻译平台。”

更现实的目标是：

> **在自己常看的日语 VTuber / 游戏直播中，字幕准确、延迟和稳定性达到每天愿意长期使用的程度。**

可以通过主动提供上下文降低问题难度：

```text
当前 VTuber
当前游戏
当前语言
Game Profile
术语表
近期对话
```

因此系统实际解决的是：

```text
P(text | audio, game, streamer, context)
```

而不是完全盲目的：

```text
P(text | arbitrary audio)
```

## 13. 建议的新目标架构

```text
                         Game / Session Profile
                        /          |           \
                       /           |            \
                      ↓            ↓             ↓
Windows Audio → Streaming ASR → Context Manager
                      │             │
                      │             ├─ recent transcript
                      │             ├─ entities
                      │             └─ glossary
                      │                    │
                      ├─ partial → JP UI    │
                      │                    ▼
                      └─ stable → Translation Segmenter
                                           │
                                           ▼
                                      Strong LLM API
                                  correction + translation
                                           │
                                           ▼
                                 corrected JA + Chinese
                                           │
                                           ▼
                                    Subtitle Committer
                                           │
                                           ▼
                                         Overlay
```

核心原则可以浓缩为四点：

1. **真正的 streaming ASR，而不是 VAD 后整句离线 ASR。**
2. **游戏专名 / contextual biasing 是一级能力。**
3. **LLM 一次完成保守纠错 + 上下文消歧 + 翻译。**
4. **整个系统异步、freshness-first，绝不能让 LLM 阻塞 ASR。**

Windows / WSL2 / Docker / PySide6 / localhost WebSocket / CI / 打包 / 安全等 V2 已有工程结构原则上继续保留。

下一次修改 `LIVE_TRANSLATOR_V2_PLAN.md`，重点应围绕上述四点重写，而不是继续在现有 Dolphin + VAD + final-only 架构上追加功能。
