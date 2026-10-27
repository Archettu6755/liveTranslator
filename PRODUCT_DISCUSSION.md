# 日语 VTuber 直播翻译：产品讨论与行为方案

更新日期：2026-10-27

本文是新方案的唯一维护文档，统一保存产品边界、技术选择、明确行为、参考源和未决问题。后续讨论直接更新本文，不再拆分同类文档。

[LIVE_TRANSLATOR_RESEARCH.md](archived/LIVE_TRANSLATOR_RESEARCH.md) 已于 2026-09-09 原文归档，内容保持不变；其中的旧产品范围、技术栈和部署决定不自动成为新方案要求。`archived/` 与 `Transfer/` 同样保持历史资料定位。归档研究中的旧目录称呼按其写作时的仓库布局理解，不作为当前路径或执行指令。

当前讨论已归并记录，但本文不是已经验证完毕的实施规格：

- 2026-10-27 补齐近期讨论：优先本地 ASR＋低价云端翻译，云端 ASR 仅作可选路线；补录云端 ASR 费用、Index 公共 API、Hy-SimulMT 的适用边界。第 21 节提供同步清单与整体计划索引；模型和供应商仍未最终选定，未进行真实接入。

- 第 1 至 6 节记录产品边界、当前模型/翻译基线及成本假设；模型和翻译路线现允许重新评估，尚未因此切换。
- 第 7 至 13 节把已讨论机制展开为明确的实施建议，并逐项标注参考源；这些行为尚未全部实现或验证，当前原型与模块实施状态见第 17、18 节。
- 2026-09-08 已确认采用第 11 节的轻量直播字幕方案：桌面独立悬浮字幕作为首版原型方向，前一条＋当前条、语义短句先译、有限修正、主字幕优先跟上直播、中文优先。用户接受方案不等于效果已经验证。
- 2026-09-09 的历史选择为 Windows 客户端与 WSL2 ASR 分开运行、Python 为主。Windows 11 首发、应用采集优先、简单预选和 WSL2 开发入口继续保留；桌面技术和普通用户部署目标已按第 19 节重新评估，模型和翻译候选见第 20 节。只读环境历史快照保留在第 15 节。
- LLM 保守纠错是新增能力建议，是否默认启用仍需验证。
- 引用只支持注明的前人机制；本项目的修改不冒充参考项目已有实现。
- 第 14 节集中保留未决问题。日语边界规则、数值阈值和硬件实测结果没有被伪装成已确定结论。
- 第 16 节记录 Luna Max 首轮盘点后的主代理源码复核：明确提取单位、改造边界及证据；尚未迁移代码或运行旧测试。
- 2026-09-23 已按后续授权完成模拟字幕体验原型；这不代表 ASR、翻译 API、Windows 客户端或产品整体完成，实测边界见第 17 节。
- 2026-09-23 已新增稳定日语源文本整理器；其输入边界、未实测阈值和质量状态限制见第 18 节。
- 2026-10-25 推荐 Electron＋React＋TypeScript 桌面外壳、Python 字幕核心及独立 ASR 工作进程作为后续实施基线；这不是逐项确认的最终决定，也未实现。该轮曾将 Windows 原生 ASR 作为免 WSL 发布门槛；2026-10-27 用户已明确改为自用优先、WSL 推荐、纯 Windows TODO；细节、对比、验收条件和模型路线重评范围见第 19 节。

## 1. 项目起点与边界

- 产品灵感和核心需求：帮助用户看懂日语 VTuber 直播。
- 目标体验以用户完全不懂日语为前提，提供中文字幕。
- 用户本人略懂日语，主要希望通过这个点子做出一个产品；不能据此推导出已验证的付费需求或商业模式。
- 不扩展为通用视频翻译或游戏翻译产品。直播中出现这些话题，不意味着需要支持相应的独立产品场景。
- 旧仓库方案不再作为新产品规划的依据。
- `archived/` 中的代码可以在后续实现阶段检查是否可复用，但复用不应反向决定新产品需求。
- 初期仅开展产品讨论；2026-09-09 用户已明确要求编写根目录 `AGENTS.md`，用于约束后续协作。该文档编写不自动授权修复环境或实施功能，后续按用户具体任务推进。

## 2. 已确定的技术路线

当前采用：

**直播音频 → 本地流式 ASR → 语义片段组织 → LLM API 翻译及修正 → 中文字幕**

上面的流程是当前基线的概念关系；采集与部署方向见第 4、15、19 节。ASR WebSocket v1 已建立，其余组件选型与宿主 IPC 尚未全部完成。

当前 ASR 与翻译基线仍是本地流式 ASR＋云端 LLM API，但用户已授权重新比较 Nola、Voxt、sglang-omni 相关 ASR/流式方式，以及翻译 LLM/API/本地路线。授权评估不等于已更换模型或部署本地翻译模型；研究结果和候选排序见第 20 节，最终默认组合待验证。

- ASR 在本地运行，要求支持流式识别。
- 翻译优先低价云端 LLM/专用翻译 API；建议 Index 公共 API 与一家低价付费 API 对照。小型本地专用翻译降为后续备选，正式机翻 API 保留比较；供应商未最终确定，见第 21 节。
- 曾讨论全本地、全 API 和混合部署；本轮重评优先比较本地 ASR 配不同翻译后端，不据其他项目支持云端 ASR 就默认上传音频。
- Dolphin 已按本轮的流式要求排除，不再围绕它规划。
- 成本、识别准确率、翻译忠实度、延迟和本地资源占用需要综合考虑。

### 本地硬件与模型候选

- 已知用户显卡为 RTX 4060；具体显存、可用资源和实测吞吐尚未核验。
- 不把 1B 参数量设为硬性上限。权重能否装入显存与能否持续实时推理是不同问题。
- Qwen3-ASR-0.6B 是优先候选，1.7B 保留为更高规格候选，尚未最终选型或测试。
- 用户已初步选择 Qwen 本地 ASR 路线；先不为流式接口缺少词级时间戳额外部署 ForcedAligner。
- 记录音频时间轴、停顿和结果到达时间，但不把到达时间冒充语音起止时间。
- 官方当前流式代码会累计音频并重新解码；不能假定单个状态可无限运行且开销恒定。运行窗口与重置边界需在接入前明确，具体行为见第 7 节。
- 不把服务器上的吞吐宣传值当作本机直播延迟保证。

## 3. 字幕策略：语义短句先译，当前段落可修正，结束后定稿

### 决策演进

最初倾向于等待完整说话后翻译整句，暂缓增量字幕。

后续讨论调整为：以相对完整意思的短句或语义片段为单位先翻译，保留原文和上下文，再根据后续内容修正当前段落的译文。

**当前以调整后的策略为准，不再把“所有增量字幕都留到以后”当作约束。** 但仍不追求逐字翻译或每次 ASR 文本变化都调用翻译。

### 当前共识

- ASR 持续接收音频，提供识别文本。
- 在识别结果足够稳定、形成相对完整的意思时，触发一次翻译。
- 短句翻译后不立即丢弃其原文与上下文。
- 后续片段到来时，结合原文重新判断，并修正当前尚未定稿的译文。
- 保留上下文的范围可以大于允许修改字幕的范围，两者需要分开设计。
- 当前翻译段落允许重新理解，但屏幕上默认只修改当前字幕条；前一条及更早字幕锁定。关键错误有新证据时用独立“更正”条补救，不偷偷改历史。定稿内容仍可作为后续上下文。
- 优先修正否定、指代、人物关系、漏译等意义问题，不为了措辞润色而频繁刷新字幕。
- 最后一次片段翻译可以同时完成整段定稿，不必固定增加一次独立的“整句修正”请求。

### 概念示例

| 时机 | 本次翻译依据 | 字幕行为 |
| --- | --- | --- |
| A 形成相对完整意思 | A 及必要历史上下文 | 显示 A 的初译 |
| B 到来且达到翻译条件 | A＋B 及必要历史上下文 | 显示新内容；A 仍在当前条时可修正，已锁定时按更正规则处理 |
| C 到来并判定当前段落结束 | A＋B＋C 及必要历史上下文 | 完成当前段落定稿，不把整段译文重新播放一遍 |

该示例的行为在第 8 至 11 节展开。翻译上下文与显示条不是同一单位：返回可更新区域的完整结果，不采用任意文本补丁，也不把不断增长的整段中文直接替换到一个字幕框。具体结构化接口仍待实现前确定。

### 已补充的行为与仍待确定的参数

第 7 至 12 节按“明确行为＋参考源”记录时间管理、字幕状态、触发条件、请求合并、迟到结果处理、显示和保守纠错。

仍待确定：日语规则覆盖、时间和长度阈值、Qwen 状态重置与跨窗口去重细节、上下文和术语预算、界面视觉参数。LLM 保守纠错的范围及接口也已提出具体建议，但效果尚未验证。

ASR 的 final 标记不等同于语义完整，也不自动等同于字幕定稿。“完整意思”同样可能被后续转折、否定或引用关系改变，需要允许有限修订。

## 4. 播放器与平台边界

- 不假定能够控制、暂停或延迟用户的直播播放器。
- 首版原型方向采用桌面独立悬浮字幕，不依赖改造 YouTube 网页；手机 App 不默认纳入首版支持。
- 此前讨论的“缓冲直播音画以等待翻译”没有被选定为产品方案。
- 当前只描述“获取直播音频、显示中文字幕”的需求，不据此假定任意平台的音频都能直接采集。
- 首发优先支持 Windows 11，默认采集指定应用，输出设备混音作为手动备用。具体浏览器兼容性仍需验证；悬浮窗方向不代表已经解决置顶、鼠标穿透或独占全屏兼容。

### A1：应用采集优先，不静默扩大采集范围

- 使用 Windows 应用回环能力采集所选进程树；音频会话发现与实际采集目标映射分开处理，不直接把枚举得到的任意 PID 当成完整应用根进程。
- 应用不等于浏览器标签页：同一浏览器其他发声页面可能混入，不承诺选择窗口即可隔离标签页。首版提示直播所在浏览器尽量仅有一个发声页面。
- 备用模式采集所选输出设备的混音，不冒充所有输出设备声音的总和。用户主动选择并看到可能混入其他应用声音的提示；应用采集失败不自动切换到混音。
- 不默认采集麦克风、保存录音或重新播放捕获音频。音频在本地识别，识别出的文本可能发往翻译 API，因此误采集也有隐私影响。
- 来源始终可见，并提供停止按钮；应用退出、耳机断开或设备切换时明确提示及处理连接生命周期，不擅自更换目标。
- 浏览器扩展标签页采集与虚拟声卡只作后续候选，不作为首版安装要求。采集隔离不能分离直播内部已经混合的主播、嘉宾和背景音乐。

参考事实：微软应用回环支持指定进程及其子进程，且不绑定单一物理输出设备；设备回环获取指定输出端点的混音，不要求启用硬件“立体声混音”。[应用回环示例](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)、[WASAPI 回环](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)。标签页 API 需用户触发且需处理本地播放；虚拟声卡需额外路由配置。[Chrome tabCapture](https://developer.chrome.com/docs/extensions/reference/api/tabCapture)、[VB-CABLE](https://vb-audio.com/Cable/)

### A2：首版提供候选列表和简单预选，不做智能猜源

| 情况 | 明确行为 |
| --- | --- |
| 一个符合条件的活动应用 | 预填候选，用户点击“开始翻译”后才启动识别和翻译 |
| 多个活动应用 | 活动应用优先排列，由用户选择，不按音量或浏览器名称随意决定 |
| 没有活动应用 | 提示先播放直播，提供刷新和手动选择入口，不只显示空白列表 |
| 用户已选择但暂时沉默 | 保持选择，不清空或自动切换 |
| 应用退出 | 提示来源断开，等待重新选择，不扩大到其他应用或系统混音 |

列表显示名称、图标和音频活动状态，不要求用户输入 PID。按相关输出设备枚举会话并处理新会话通知；可确认属于同一采集目标时归组，不按同名强行合并。活动状态适合排序与预选，不作为唯一筛除条件；音量指示只能证明收到声音，不能证明选对直播。

首版不自动试听所有应用判断日语、不根据窗口标题识别直播、不按最大音量切换，也不自动恢复上次目标并立即开始翻译。进程树映射、多标签页、应用重启、设备切换和其他应用同时发声必须列入实测。

来源事实：会话枚举按音频设备进行，需结合通知维护列表；`Active` 只代表流正在运行，不保证此刻有可听声音；会话可能跨进程，返回 PID 不等于可靠应用根进程。上述预选和确认策略是本项目设计。[会话枚举](https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nf-audiopolicy-iaudiosessionmanager2-getsessionenumerator)、[会话状态](https://learn.microsoft.com/en-us/windows/win32/api/audiosessiontypes/ne-audiosessiontypes-audiosessionstate)、[进程 ID](https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nf-audiopolicy-iaudiosessioncontrol2-getprocessid)

## 5. 成本讨论结论

增量修订会增加请求数和重复处理量，但不等于成本必然失控。关键在于每段触发多少次、每次重发多少上下文，以及返回多少译文。

以每次重译当前前缀、片段等长为假设：

| 一段话拆分数量 | 相比只翻整段的原文输入量 | 调用次数 |
| --- | --- | --- |
| 2 段 | 约 1.5 倍 | 2 次 |
| 3 段 | 约 2 倍 | 3 次 |

例如三段对应 A、A＋B、A＋B＋C，原文处理量为 1＋2＋3＝6 份，而一次性翻译为 3 份。

以上不是总账单倍数：提示词、历史上下文会重复发送，完整译文也可能重复输出；模型的思考 tokens、缓存和分词方式还会影响费用。

- 翻译应由语义片段触发，而不是由每个字或每次 ASR 更新触发。
- 不固定增加一次多余的段末翻译请求。
- 不把“每个整句只会拆两三次”当作已验证事实，直播口语可能持续追加内容而没有清晰句号。
- 低价 API 值得作为起点，但便宜不代表已证明满足日语直播翻译质量要求。

### 先前预算的适用范围

讨论中使用过示例：每小时 600 次翻译，每次 450 输入 tokens、30 输出 tokens，即每 100 小时 2700 万输入和 180 万输出 tokens。

这个示例不是实测，不是预算上限，也未证明适用于当前增量修订方案。后续估算需要明确这些调用数是否已经包含修订，避免重复计算或漏算。

## 6. 模型调研如何保留

模型调研是候选依据，不是已作出的型号选择。价格与版本会变化，接入时需重新核验。

- 本地 ASR：优先讨论 Qwen3-ASR-0.6B，保留 1.7B。
- 通用翻译 LLM API 的已讨论候选：豆包 Seed 2.0 Mini/Lite、智谱 GLM Flash/FlashX、DeepSeek 等。
- DeepSeek 旗舰型号可作为质量对照，不预设旗舰模型是产品的最低要求。
- Qwen-MT 等专用翻译 API 和 Microsoft/Google 正式机翻 API 保留对照；最新优先级为低价云端翻译，Index 公共 API 的资料核验见第 21 节。
- Soniox、Scribe、Voxtral、Qwen 云端流式 ASR 保留候选背景；已重新讨论云端 ASR 延迟与费用，但不改变本地默认、不自动上传音频，见第 21 节。
- 暂无足以证明某个候选在“日语 VTuber 直播”场景最强的可靠比较结论，不使用英语语音或编程排行榜替代本场景判断。

参考入口：

- [Qwen3-ASR 官方说明](https://github.com/QwenLM/Qwen3-ASR)
- [阿里云 ASR 选型](https://help.aliyun.com/zh/model-studio/asr-model/)
- [阿里云模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- [豆包模型价格](https://www.volcengine.com/docs/84458/1585097?lang=zh&redirect=1)
- [智谱模型价格](https://bigmodel.cn/pricing)
- [DeepSeek 模型及价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

## 7. 时间与 Qwen 接口

### T1：建立音频时间轴，不依赖词级时间戳

明确行为：

1. 每次会话创建新的 `session_id`。采集端按实际样本数记录音频范围；重采样时保存与原始时间轴的映射。
2. 丢帧或采集断开单独记录缺口，不把断开前后的音频拼成无间断时间线。
3. VAD 的起止位置使用音频时间轴；API 超时、UI 存活时间使用单调时钟，两者不混用。
4. ASR 快照附带它已处理到的音频位置和结果到达时间。关联范围只表示这次识别覆盖的音频，不冒充文本的精确起止。
5. 延迟统计分别记录识别到达、翻译请求和字幕显示时间；没有对齐证据时不输出“精确词延迟”。

来源事实：Qwen 官方流式接口不支持时间戳，也不调用 ForcedAligner；对齐是另一个能力。我们的样本时钟和缺口记录是适配这一限制的设计。[Qwen 流式实现](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_asr.py)

### T2：限制 ASR 状态寿命，不假定流式等于恒定开销

来源事实：核对的官方实现将输入累积到 `audio_accum`，在流式步进中重复提交累计音频，并回退末尾 tokens 后续写文本；它不是“每块音频严格只编码一次”的接口。[Qwen 流式实现](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_asr.py)

我们的行为：优先在可用停顿处排空旧状态并启动新状态；连续讲话时也必须受音频窗口预算约束。重置不能静默丢尾部音频。跨窗口的重叠、去重和上下文传递方案需接入前确定，不能简单清空缓冲后宣称支持长时间直播。ASR 窗口切换不自动导致中文定稿。

## 8. 原文状态与字幕状态分开

### S1：保留原文快照，维护稳定前缀和可变尾部

明确行为：

1. 每次文本变化保存原始快照，增加源版本号；完全相同的快照不增加版本，不触发重复翻译。
2. 若后端有明确稳定提交语义，适配层使用该语义；仅仅返回 `state.text` 不算稳定提交事件。
3. 没有提交事件时，候选方法是比较连续 ASR 快照的共同前缀，再保留可配置的尾部缓冲。共同前缀只是稳定性启发式，不是语音正确性的证明。
4. 只有稳定候选内的文本可成为正常翻译输入；末尾未完成文本继续等待，不把它当作完整短句。
5. 若后端改写了已消费原文，活动段增加版本并重新翻译；已锁定字幕不回改，保留冲突记录。关键语义错误有新证据时按 U3 生成独立更正，不把旧段重新激活。
6. LLM 修订日文永不覆盖这些原始 ASR 快照，也不自动反馈成新的识别事实。

参考机制：WhisperLiveKit 区分 `lines` 与 `buffer_transcription`；LocalAgreement 以多次结果共同前缀决定提交。上述 Qwen 适配、冲突处理是本项目补充。[WhisperLiveKit API](https://raw.githubusercontent.com/QuentinFuxa/WhisperLiveKit/main/docs/API.md)、[Whisper-Streaming](https://github.com/ufal/whisper_streaming)

### S2：四个翻译段落状态

| 状态 | 允许的变化 | 离开状态的条件 |
| --- | --- | --- |
| 积累中 | 原文增长或修订；可以尚无中文 | 首个有效初译到达，或原文关闭 |
| 活动段 | 增加原文版本；更新内部译文及尚未锁定的当前字幕条 | 规则判定原文关闭 |
| 等待定稿 | 不追加该段原文；等待覆盖最终源版本的翻译 | 有效最终结果到达，或定稿等待超时 |
| 已结束 | 不再修改可见译文；可作为带来源的历史上下文 | 不回到活动状态 |

“已结束”还必须记录质量状态：正常定稿、译文不完整、翻译失败。源文本关闭不等于 API 已返回，不得把旧版初译标成覆盖完整原文的定稿。关闭旧段后允许开始积累新段。

这些是翻译段落状态，不是屏幕字幕条状态。同一段可产生多条字幕；某条退出当前位置后即锁定，不必等待整个翻译段落结束。锁定只表示停止原位改写，不代表语义已被证明正确。

参考机制：SimulStreaming 分开输出已确认 `text` 与可修改 `unconfirmed_text`。我们的段落状态和失败质量标记是改造；不采用“两次中文一样就永久锁定”的规则。[SimulStreaming 输出说明](https://github.com/ufal/SimulStreaming#usage-real-time-simulation-from-audio-file)

## 9. 翻译触发与原文关闭

### G1：本地规则决定翻译机会，不另发 LLM 断句请求

处理顺序：先检查是否有未消费的稳定内容，再寻找候选边界，最后检查最小调用间隔。不同触发条件同时成立时只生成一个最新快照。

| 条件 | 明确行为 |
| --- | --- |
| 稳定文本出现句末标点 | 翻译到该边界；若其后尚无内容，保留可配置短确认窗口，避免瞬时标点立即锁死译文 |
| 出现短暂停顿 | 在稳定文本中寻找可用分句边界，有新内容才初译；短暂停顿本身不关闭整段 |
| 文本持续增长且达到等待或长度预算 | 选取当前最靠后的可用边界翻译；不是重新提交每一次 ASR 更新 |
| 只有少量文字、只有逗号或明显未完结构 | 暂不单独翻译；逗号不是充分条件，助词或未完谓语末尾不能直接视为语义结束 |
| 达到等待上限但仍无可用边界 | 不猜测补句；保持等待状态。若有可独立解释的前半部分，可只译该部分并保留未消费尾部 |
| 长停顿、句末确认完成或停止会话 | 关闭当前源段，处理剩余识别结果，并合并生成最终翻译机会 |
| 达到段落硬上限但句子仍未完成 | 在最后可用边界关闭；无边界则以“不完整源段”结束，保留原文，后续可携带上下文但不伪装成完整句子 |

日语实现需有显式边界规则及反例测试：句末标点只是候选信号；不能认为所有带 `けど`、`から` 等词尾的片段都完整或都不完整。词表与具体语法覆盖尚未确定。

调用前按原文内容去重：只有时间经过、没有新的可翻译内容时，不重复调用。初译与定稿使用同一调度路径；原文和翻译任务要求均未变化时，关闭状态本身不要求重新翻译。

参考机制：LiveCaptions-Translator 的 `SyncLoop` 使用句末、文本变化次数、空闲轮数等条件入队。我们改为时间和文本增量条件，加入日语边界检查、去重与段落状态，不复制其轮询计数或 UTF-8 字节阈值。[Translator.cs](https://raw.githubusercontent.com/SakiRinn/LiveCaptions-Translator/master/src/Translator.cs)

### G2：必须明确配置含义，不能只留下“适当等待”

| 参数类别 | 控制的行为 |
| --- | --- |
| 稳定性尾部预算 | 共同前缀中暂不交给翻译的末尾范围 |
| 短停顿阈值、句末确认窗口、长停顿阈值 | 分别决定初译机会、句末观察和原文关闭；三者不共用一个 VAD 阈值 |
| 最小翻译间隔、最小新增文本量 | 抑制高频重译；已确认的短回复可按句末规则处理，不被长度门槛永久饿死 |
| 最长初译等待、段落时长和长度上限 | 分别控制首次显示延迟与活动段规模 |
| API 并发、待处理段数、请求超时、定稿等待超时 | 限制云端积压并规定异常退出时机 |
| 音频窗口、历史上下文时间及字符预算 | 防止 ASR 与 LLM 输入随直播时长无限增长 |

本轮明确的是参数职责，不是数值。具体值与边界词表需在实现前形成一组起始配置；它们不是可以从参考项目直接照抄的日语最优值。

## 10. 翻译请求、合并和迟到处理

### Q1：请求绑定不可变快照

每次请求在客户端绑定 `session_id`、`segment_id`、`source_revision`、原文快照和上下文快照。关联关系由客户端保存，不信任模型自行回填编号。

请求包含当前段原文、有限历史原文、带来源的历史译文、相关术语，以及已显示锁定内容和允许修改区域。结合当前段完整原文理解，不仅发送新追加的几字；返回可更新区域的完整结果，不让模型输出任意 UI 文本补丁。内部整段复核结果与屏幕新增内容分开，避免重复显示已表达的意思。字幕条 ID、锁定状态和请求时的显示版本由客户端维护；返回时再次检查，已在等待期间锁定的条不能被覆盖。源片段与字幕条的关联、去重及结构化字段仍需确定，不能仅依赖模型遵循提示词。

原文、历史和术语一律作为待处理数据，与固定翻译指令分隔；主播说出的命令或提示词不得改变任务、索要密钥或触发工具。

参考机制：SimulStreaming 保留源上下文并维护可变译文；完整段快照、客户端版本绑定和无工具权限是本项目选择。[SimulStreaming](https://github.com/ufal/SimulStreaming)

### Q2：同段最多一个在途请求和一个最新待处理版本

1. A 在途时，若 B、C 先后到来，待处理槽由 B 更新为 C，不依次执行两个过时任务。
2. 原文关闭时，把待处理槽替换为该段最终版本，不另排一份重复的“修正请求”。
3. 已发出的请求不能假设取消即可免计费；优先合并未发送版本。
4. 不同段共享有限并发和队列。过载先合并修订；仍超预算时，淘汰最旧且尚未发送的段并记录“翻译跳过”，保留原文。不得静默显示成已翻译完整。
5. 超时不阻塞 ASR；最多进行一次受队列及时间预算约束的重试。段已过期或会话已停止时不为旧段继续发起重试。

参考机制：LiveCaptions-Translator 把同步与翻译拆成独立循环，以快照入翻译任务队列。这里的一在途一待处理、过载和重试规则是本项目建议，不声称其源码采用完全相同策略。[Translator.cs](https://raw.githubusercontent.com/SakiRinn/LiveCaptions-Translator/master/src/Translator.cs)

### Q3：返回结果只能推进显示版本

- 会话不匹配、段已结束或结果版本不高于已显示版本：拒绝更新字幕。
- 结果早于最新原文版本，但不早于已显示版本，且新原文只是追加、未改写该请求覆盖内容：可作为临时初译显示，同时继续最新请求。
- 新原文已改写结果所依据的内容：丢弃不兼容结果，不把错误初译重新显示出来。
- 只有覆盖关闭时最终源版本的有效译文才算正常定稿。
- 定稿超时：结束该段并标记不完整或失败，不让它永久占用活动位置。
- 段已退出可见区域时，返回结果不使它重新弹出。未结束且版本有效的迟到结果可进入有界会话历史，不挤占主字幕；已结束段的旧请求仍按上述规则拒绝。关键更正走 U3 的新事件，而不是重新显示旧结果。完整会话持久化仍未决定。

参考机制：WhisperLiveKit 使用序号与可变 buffer；Live-translation 按 `(origin, turnId)` 维护待完成字幕。上述源版本兼容性和定稿条件是本项目补充。[WhisperLiveKit API](https://raw.githubusercontent.com/QuentinFuxa/WhisperLiveKit/main/docs/API.md)、[Live-translation 架构](https://github.com/fmadore/Live-translation/blob/main/docs/architecture.md)

## 11. 显示行为与可重复验证

### U1：已选择的字幕形态与备选方案

采用轻量直播方案，不把所有候选同时做成首版功能。

| 子任务 | 已选择的行为 | 讨论过但不作为默认的方案及取舍 |
| --- | --- | --- |
| 展示载体 | 桌面独立悬浮窗，可调整位置；置顶、穿透和全屏行为在确定操作系统后验证 | 网页内嵌需适配页面和全屏；侧栏便于回看但视线离开直播 |
| 可见内容量 | 前一条弱化＋当前条突出，每条默认最多两行 | 单条更简洁但容易错过；多条信息流更易回看但遮挡和注意力成本更高 |
| 初译时机 | 稳定语义短句＋边界/停顿检查＋等待预算，按 G1 调度 | 等整句更稳定但空白更久；固定周期不检查语义更容易显示残句 |
| 修订范围 | 默认只改当前条，前一条锁定；关键错误按 U3 例外补救 | 永不修订难补救初译；最近多条随时改写容易打断阅读 |
| 停留策略 | 阅读时间与有限回看结合，主字幕优先跟上直播 | 直接被新条挤掉可能闪现；逐条排队读完会越看越落后 |
| 语言与状态 | 默认中文，日文可选且默认关闭；状态轻量展示 | 双语默认开启增加阅读负担；调试信息另放诊断视图 |

单条偏定稿方案、多条侧栏方案仅保留为后续对照，不是额外首版交付要求。上述组合是产品选择，不是已证实的最佳效果。

参考机制：LiveCaptions-Translator 的覆盖层与显示句数、Live-translation 的操作界面与字幕层分离，支持展示与处理解耦；本表中的默认组合由本项目确定。[LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator)、[Live-translation 架构](https://github.com/fmadore/Live-translation/blob/main/docs/architecture.md)

### U2：三个单位、两种时间，不为直播先做精细打轴

1. 识别片段是 ASR 的输入覆盖与文本快照；翻译段落是理解所需上下文；字幕条是屏幕上可读的一小块中文。三者不强制一一对应。
2. 音频时间用于追踪来源、停顿和延迟；显示时间用于安排字幕出现、修订和隐藏。中文真正出现后才开始计算阅读时间。
3. Qwen 缺少词级时间戳不阻止实现这种直播字幕。没有对齐证据时，只保留可证实的音频覆盖范围，不按中文字符数伪造子字幕的精确起止时间。
4. 不控制或延迟播放器时，翻译天然晚于相应讲话；精确打轴不能让晚到的译文回到过去显示。
5. 按中文语义及实际渲染宽度拆条、换行，不照搬日语断句或按 UTF-8 字节切分。长译文拆成短条，不缩小字号硬塞、不截断、不自动摘要。
6. 从视频字幕工具借鉴分段、阅读时长和布局职责，不引入全视频未来上下文、离线回填或配音产品范围。额外强制对齐不作为首版前置条件。

参考机制：stable-ts 将按标点、长度、时长等重组字幕作为独立操作；其按词间隔处理依赖时间戳，不能直接套到 Qwen 无词时间戳输出。[stable-ts](https://github.com/jianfch/stable-ts#regrouping-words)。Subtitle Edit 的时长与长短行处理用于启发阅读规则，不直接照抄阈值。[Subtitle Edit 文档](https://subtitleedit.github.io/subtitleedit/)。WhisperX 将识别与对齐分离，VideoLingo 将分段、翻译及字幕适配分步处理；这里只吸收职责拆分，不新增模型链路或多轮翻译调用。[WhisperX](https://github.com/m-bain/whisperX)、[VideoLingo](https://github.com/Huanshere/VideoLingo)

### U3：有限修正，重要错误显式补救

- 当前条返回兼容的新译文时原位更新，不逐字播放，不重复入场或滚动动画。
- 移到前一条及进入历史后锁定；普通措辞润色不再修改，也不发布更正。
- 否定、动作主体、人物关系、数字等关键含义有新原文证据或明确依据时，允许生成独立的“更正：……”短条，关联被纠正的字幕。不能仅因模型换了一种说法就认定旧条错误。
- 更正作为有版本的新事件经过相同调度，不恢复已结束段；同一证据和目标版本去重。不把任意迟到旧请求当成更正依据。
- 没有足够依据时保留不确定性，不猜测纠错。常规字幕和更正发生争用时都受延迟及队列预算约束；更正展示优先级与有效回溯窗口仍需起始配置。
- 已锁定文本保持原样，历史可附加更正关联标记，不能悄悄覆盖用户读过的内容。

参考机制：SimulStreaming 区分确认文本与可变文本；当前条锁定和独立更正是本项目为阅读稳定性设计的规则，不声称参考项目已实现。[SimulStreaming](https://github.com/ufal/SimulStreaming)

### U4：阅读时间、积压与布局

- 固定字幕框位置和宽度，当前条与前一条有清楚但不过分抢眼的视觉层级；调整字号和位置属于用户设置，不随文字增长自动跳动。
- 新字幕条出现时才推进前一条；同一条修订不推动历史。优先保持未改动部分的布局，必要换行不能以遮字或截断为代价。
- 依据中文长度与阅读速度配置正常停留时间，并设上下限。意义明显变化可增加阅读时间，但仍受总存活上限约束；标点微调、重复版本、心跳不重置计时。
- 保留条数、每条最大存活时间、无新内容后的隐藏时间是独立参数。正常停留是目标，不承诺快速讲话时每条都能读完。
- 主字幕优先跟上直播，不无限排队。过载先合并尚未发送的翻译更新；显示队列中的过时条不再轮番占据主字幕，转入有界会话历史。未翻译内容明确标为跳过，不补造译文。
- 提供按需查看的有限会话历史，不默认把多条历史铺在直播画面上。历史保留预算与翻译上下文预算分开；退出屏幕不等于删除上下文。落盘、全量保存和导出未纳入默认范围。
- 不因跟不上就自动删减成摘要；如果将来加入摘要，需要独立的产品决定和提示。

参考机制：Caption.Ninja 分开控制 `maxlines`、`maxage`、`showtime`；Subtitle Edit 提供阅读速度和时长调整思路。本项目的主字幕追赶、有界回看及修订计时规则是直播场景改造。[Caption.Ninja](https://github.com/steveseguin/captionninja)、[Subtitle Edit 文档](https://subtitleedit.github.io/subtitleedit/)

### U5：状态提示与 VTuber 特殊内容

- 用不抢眼的位置区分正在监听、正在翻译、连接异常；错误提示不冒充主播发言。
- 沉默不是识别失败。只有检测到语音且识别结果不足或不可用时，才考虑显示“这段没听清”；不能把背景音乐或单纯无文本一概标成失败。
- ASR 延迟、API 耗时、源版本和纠错依据进入可选诊断视图，不占据正常字幕；不展示未经校准的模型自报置信百分比。
- 来源完整性与翻译质量分开。当前条或前一条的源标记为不完整时，只在标题旁显示“原文不完整”，字幕正文仍只显示译文；cue 消失或切换后清除旧标记。`source_incomplete=false` 表示“未标记不完整”，不能表述为已确认完整。有限历史单独展示来源完整性和原因，未知原因代码使用纯文本友好回退；元数据更新不重置阅读计时或当前翻页。
- 没有可靠说话人归属时不标姓名、不自动分配人物颜色。多人同时讲话也不保证能逐人完整恢复；说话人编号不等于真实身份。
- 笑声、犹豫、口癖、重复和自我纠正按对含义及语气的影响保留，不逐声转写，也不一律清洗成正式书面语。不可确定的内容不靠剧情常识补齐。

参考机制：Live-translation 分离字幕、状态及音量事件；来源标记来自本项目的 `StableSourceOrganizer` 事件及引擎来源元数据，标题提示、历史纯文本回退和不重置阅读状态由 UI 实现。本条显示规则由本项目确定，代码与确定性检查见 `src/live_translator/source_organizer.py`、`src/live_translator/engine.py`、`src/live_translator/ui.py` 及对应测试。[Live-translation 架构](https://github.com/fmadore/Live-translation/blob/main/docs/architecture.md)

### U6：用固定事件测试真实显示路径

模拟器不访问音频设备、不调用 API，向与真实链路相同的字幕状态处理器发送以下事件。它只是 UI 与调度验证，不算 ASR 性能证据。

| 输入序列 | 必须观察到的结果 |
| --- | --- |
| 同一 ASR 快照重复到达 | 不新增翻译请求或字幕 |
| A 在途，B、C 连续更新 | 待处理仅保留 C |
| 新版译文先显示，旧版稍后到达 | 不发生版本回退 |
| 后续原文增加否定或修正专名 | 活动段按新原文修正，不重排全部历史 |
| 原文关闭而最后翻译仍在途 | 标记等待定稿，不能把旧初译冒充完整定稿 |
| API 超时、队列过载、字幕已过期 | 有明确失败/跳过状态，ASR 继续，不弹回旧字幕 |
| 长时间无停顿、音频缺口、停止会话 | 不无限积累状态；处理尾部或记录不完整，不悄悄丢失 |
| 一段翻译上下文连续产生多个短条 | 按条展示，不把整段中文反复播放，不重复已锁定含义 |
| 否定在后半句才出现，错误条已锁定 | 有证据时生成关联更正；不偷偷改旧条，不反复发同一更正 |
| 请求期间当前条移到前一条 | 返回时再次检查显示版本，不覆盖已经锁定的条 |
| 长字幕后迅速到来多条新字幕 | 不缩字、截断或无限排队；主字幕跟进，过时内容可在有限历史查看 |
| 标点微调与关键语义修订交替发生 | 前者不重置计时，后者可延长阅读但不无限续命 |
| 沉默、背景音乐、语音不可识别、API 变慢或断开 | 区分监听、识别不足与翻译异常，不把所有无字幕情况称为没听清 |
| 多人插话、笑声、口癖、自我纠正 | 不凭空标姓名；保留影响意思的语气和更正 |

除状态断言外，还需人工观察能否读完、修订是否打断阅读、前一条是否有帮助、遮挡是否可接受、主字幕是否持续落后。先验证同一套模拟事件下的阅读体验，不以 UI 测试代替真实日语质量、端到端延迟或显卡性能验证。

参考机制：Live-translation 的确定性 demo 与真实 provider 发送同种事件并走同一 UI 路径。表中事件集是我们的验证要求。[架构文档](https://github.com/fmadore/Live-translation/blob/main/docs/architecture.md)

## 12. LLM 补救 ASR 错漏：同次纠错与翻译，禁止无依据补造

状态：针对用户“修复句子、补齐 ASR 漏洞”的新建议；不是已验证效果或对漏识别的恢复保证。

### C1：明确允许与不允许的行为

| ASR 问题 | 建议行为 | 不允许的替代做法 |
| --- | --- | --- |
| 标点或分词不合理 | 在不改变语义的情况下整理修订日文 | 将所有口语改写成书面语 |
| 同音字、专名误识别 | 结合原文读音线索、当前话题与显式术语映射提出最小修正 | 仅因为知道某位主播而强行替换成其名字 |
| 疑似漏了局部助词或短词 | 有前后文或真实识别候选依据时允许提出补字，并记录插入位置和依据 | 仅因为补后更通顺，就宣称音频确实包含该词 |
| 日语正常省略主语 | 必要且指代清楚时在中文中自然表达；日文原文不补成主播实际说过的主语 | 把正常省略视为 ASR 错误 |
| 否定、数字、姓名、动作主体等关键含义疑似有错 | 没有新 ASR 证据或明确映射时保留不确定性，等待后文；不能靠合理性翻转语义 | 用剧情常识猜金额、补否定、指定人物 |
| ASR 整段漏掉，或音频本身缺失 | 不生成缺失内容；翻译可确定部分，必要时标记识别不完整 | 根据话题编造一整句字幕 |
| 主播尚未说完 | 等待或保留未完成语气，后文到来再修正 | 把句子续写得完整并显示为事实 |
| 笑声、重复、口癖、自我纠正 | 保留影响含义和语气的部分；不默认全部当成识别噪声删除 | 以“修复 ASR”为名改变主播表达 |

研究依据：GER（生成式 ASR 纠错）可以利用上下文和识别候选改善结果，但缺乏音频的 LLM 也可能给出语法正确却背离原话的修订。因此这里的“修订日文”始终是推断，不是音频真值。[ClozeGER，ACL 2024](https://aclanthology.org/2024.findings-acl.37/)

上下文与语音/读音对应线索比单纯追求句子通顺更有依据。相关研究使用 N-best 候选与上下文匹配，但不能假设 Qwen 当前接口已经暴露可用的 N-best 或可靠置信度，也不能把其他场景的成绩移植为日语直播保证。[Contextual ASR Error Handling，COLING 2025](https://aclanthology.org/2025.coling-industry.32/)

### C2：一次请求完成，保留可追溯数据

输入：当前 `raw_asr` 快照、少量历史原文、相关术语及读音、上一次译文（明确标注为可修订结果）。原文和实际证据优先于旧中文，旧译文不是事实来源。

建议返回及保存的字段：

| 字段 | 明确用途 |
| --- | --- |
| `raw_asr` | 由客户端保存，不允许模型覆写 |
| `corrected_ja` | 最小修订后的日文；无修正时与输入相同，不强制每次都改 |
| `translated_zh_cn` | 翻译结果，不夹带分析、提示词或纠错解释；整段内部复核与可显示短条分开，具体结构需按 Q1/U2 确定，不能整段反复覆盖屏幕 |
| `corrections` | 有修改才返回，记录原片段、替换内容、位置、类别和简短依据；插入与替换要可区分 |
| `uncertain_spans` | 标记无法确定的片段和原因，不用未经校准的自报百分比代替证据 |

校验：检查字段类型、长度、修订位置与原文是否匹配，以及版本是否仍有效；这些校验不能证明语义正确。结构无效时不展示整段原始模型响应，走有限重试或翻译失败流程。

翻译不串接第二次“先修复、再翻译”调用；由同一次调用输出修订和中文。额外代价是更长提示词、修订日文和改动记录的 tokens，不是必然翻倍的请求次数。无改动时返回空改动列表，不生成长篇理由。

保守修订与译文绑定为同一版本；后续新原文出现时可以撤销上次修订。未经独立确认的纠错不能自动写进永久术语表，也不能覆盖未来 ASR 提示中的事实，防止错误自我强化。

来源与改造：旧研究记录第 5 节已有 `raw_asr / corrected_ja / translated_zh_cn` 分层建议；本节增加证据、版本、局部补字边界和失败行为。上述论文提供风险和方法依据，不直接提供本项目接口。[原研究记录](archived/LIVE_TRANSLATOR_RESEARCH.md)

### C3：不把“更通顺”当作验收标准

后续用人工核对的日语原文比较关闭/开启纠错两种模式，分别统计：修对的错误、把正确内容改错的次数、无依据新增内容、否定/人物关系/数字错误、中文关键语义错误，以及额外费用和延迟。

至少包含四个固定反例：ASR 本来正确；专名确实识错；否定确实漏识但文本无法确认；整段语音缺失。后两项允许“不知道”，不能因没有补齐而强迫模型猜测。是否默认启用纠错，应依据这些结果，而不是中文是否更像一段流畅文章。

## 13. 不在本轮默认加入的能力

- 词级强制对齐、播放器控制、逐字中文流式输出。
- 本地通用 LLM、单独的 LLM 断句调用。
- 全量聊天记录保存、音频上传、云端多模态复听、第二套 ASR 交叉验证。
- 自动重听所有可疑片段。未来若加入本地重识别，需要单独定义音频保留、GPU 预算和触发规则，不能假定文本纠错已经解决漏识别。
- 立即安装模型或恢复旧实现。本文只记录明确行为与待验证边界。

## 14. 后续讨论与尚未完成的规格

字幕方案见第 11 节；Windows 11 首发、应用音频采集与简单预选，以及单一 WSL2 开发入口仍是当前边界，见第 4、15 节。2026-10-25 新增的桌面外壳和进程职责是推荐实施基线，尚未逐项确认或实现；最新决定为 WSL2 运行 Python 核心与 Qwen/vLLM，Windows 原生推理后置，见第 19、22 节。

LLM 同次保守纠错与翻译的建议继续保留，具体边界见第 12 节；不把字幕方案获认可等同于已验证纠错效果。

后续仍需逐项研究或确定：

1. 具体浏览器、进程树与音频会话映射、设备变化处理，以及悬浮窗的全屏、置顶与穿透兼容性。
2. 字幕字号、宽度、阅读时长、可接受延迟、积压上限、历史预算及更正窗口的起始配置；翻译输出与字幕条的关联、锁定校验、拆条去重接口。
3. 主播名称、昵称、口癖等上下文和术语的提供方式。
4. 如何判断产品效果达标，以及模型选择所依据的识别、翻译和资源指标。
5. API 密钥、费用承担和调用失败时的行为。
6. 按第 19 节重评 Nola、Voxt、sglang-omni 相关 ASR/流式方式及翻译 LLM/API/本地路线，优先验证 WSL Qwen/vLLM，Windows 原生交付保留为 TODO。
7. Windows 宿主与 WSL Python 核心之间通信方式、精确字段、错误/停止语义，以及 ASR v1 WebSocket 到 Windows 进程的连接方式；本轮不修改现有 contracts。
8. 采集桥接封装、可选原生 helper、Windows 桌面构建、WSL 服务启动与恢复；纯 Windows 私有推理运行时打包后置。
9. 按第 16 节的复核清单确认代码出处、依赖条件与许可告知；Qt 现有原型继续保留，但不是推荐的正式桌面外壳。

本轮仅授权修改本文档，不授权开发、安装、模型下载、真实模型接入或 API 调用。后续交付按第 19 节的三个完整结果组织；第三项真实模型验收只在获得明确任务授权后进行。

## 15. 开发入口、运行架构与环境记录

### D1：开发统一 WSL2，桌面宿主、字幕核心与 ASR 分工

代码编辑、Git、Codex 和主要开发工作继续留在 WSL2，不要求安装 Windows ChatGPT 桌面端、完整 IDE 或第二套 agent。运行位置与开发入口不是同一概念。本节新增架构是推荐基线，不改变单一 WSL2 开发入口，也不表示当前开始迁移。

| 部分 | 运行位置与职责 |
| --- | --- |
| Electron 主进程 | Windows 应用发现、设置和密钥管理、LLM HTTP 请求执行、Python/ASR 子进程监管，以及必要的音频采集桥接；密钥不进入 renderer 或 ASR |
| React＋TypeScript renderer | 主窗口与字幕 overlay 的交互和渲染；只提交用户意图、显示快照，不持有密钥、不运行第二套翻译调度 |
| Python 字幕核心进程（WSL2） | 唯一负责语义分段、翻译调度、字幕版本、显示历史与翻译上下文状态；向 Electron 主进程发带 request id/source revision/display version 的翻译命令，并接收带关联信息的结果 |
| 独立 ASR 工作进程 | 加载本地 ASR 模型、GPU 推理、音频输入、流式识别状态和健康检查；首版推荐 WSL2 Qwen/vLLM；Windows 原生运行列为 TODO |
| 开发与验证 | 代码与主要开发留在 WSL；Windows 专属采集、窗口交互和最终发布包必须在 Windows 验证。WSL 测试不能替代这些验收 |

逻辑上保持一个桌面应用、一个 Python 字幕核心和一个 ASR 工作进程，不扩大为微服务体系。Windows 后台逻辑不等于必须安装独立 Windows 系统服务。主窗口和 overlay 共用同一会话与核心状态。

仓库已有本地 WebSocket ASR v1 协议和实现，继续保留；这不代表 Qwen 接入或实时识别已验收，本轮选型不修改现有 contracts。Windows 主进程与 WSL Python 核心的跨环境通信待验证；经 wsl.exe 管理进程的 stdio JSONL 或认证本地通道都是候选，不预设 Windows Python 子进程。若使用 JSONL：输出字段经有界校验，stdout 只承载协议，stderr 只写脱敏日志；精确字段及确认、排空、超时和取消语义待后续设计。PCM 不经 renderer，也不逐样本编码进 JSON；采集桥接到 ASR 的具体传输封装仍待选定。已有的 `engine.py` `dispatch`/`drain_requests` 与调度请求中的 `request_id` 是核心与主进程分工的静态适配依据，不是 IPC 已实现的证据。

Electron 安全基线包括 renderer sandbox、`contextIsolation`、`nodeIntegration=false`、校验 IPC 调用来源、只加载本地受控内容并配置 CSP；远程直播页面不进入特权 renderer。Electron 的 `desktopCapturer` 是屏幕/窗口捕获接口，不等于进程音频隔离，也不能替代 Win32 采集桥接。[Electron 安全建议](https://www.electronjs.org/docs/latest/tutorial/security)、[desktopCapturer](https://www.electronjs.org/docs/latest/api/desktop-capturer)

### D2：桌面外壳采用 Electron 推荐基线，核心保持 Python

- Electron＋React＋TypeScript 是本轮推荐的桌面外壳基线，不是用户已逐项确认的最终选型，也不是已迁移实现。此选择让正式外壳使用成熟桌面 Web 技术，同时保留现有 Python 字幕状态核心；代价包括应用包体、内存占用、运行时和更新链路，需要通过实际打包评估，不编造数值。
- Python 继续用于字幕核心和 ASR 服务。WSL 沿用 Conda，为 ASR 使用隔离环境，不污染 `base`；Python 版本按真实依赖兼容性确定。
- Node/Electron 工具链允许用于获授权的实现工作，但不得自行安装或改变全局配置。D4 的 Node/npm 记录是 2026-09-09 的只读快照，不证明当前依赖、打包器或命令已配置；本节不把 npm 命令写成已有入口。
- 当前以自用为主，WSL2 中运行 Python 字幕核心与 Qwen/vLLM，Windows 端不要求另配 Python；不引入 Docker。免 WSL、私有 Windows Python/ASR 运行时与模型安装管理列为后续 TODO，不作为首版验收条件。
- “最小用户环境”不等于最小安装包。运行时、模型和应用拆分也不等于已确定具体安装器、更新机制、存储目录或包体。
- Windows 构建环境仍待选择；Windows 专属验证无法由 WSL 测试替代，也不能把单一 WSL 开发入口解释为纯 Linux 完成所有 Windows 构建与验收。

选型对比与参考来源见第 19 节。

### D3：WSL 开发与运行优先，纯 Windows 推理后置

- 当前开发/模型验证基线仍是 WSL2 上的官方 Qwen streaming＋vLLM 路径；Qwen README 标注这条官方 streaming 路径使用 vLLM 且不返回时间戳，vLLM GPU 安装文档不列原生 Windows 支持。该限制说明官方 SDK/vLLM 路径的现状，不能推论 Qwen 模型本身不能在 Windows 原生推理。[Qwen Streaming](https://github.com/QwenLM/Qwen3-ASR#streaming-inference)、[vLLM GPU 安装](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/)
- Nola 当前主线另有 Transformers 原生 Qwen runtime；CrispASR 也提供 Windows CUDA 发布方式及多种流式策略。它们是免 WSL 候选路径，不是本项目已验证后端。这些工作属于后续纯 Windows TODO，不再阻塞首版 WSL 方案；将来采用时仍需验证模型加载、流式质量、资源与长会话。[Nola 当前主线](https://github.com/CerealAxis/Nola-Translator/commit/fd74547acff7be4dc6f10b518d11391631eaa369)、[CrispASR Windows 安装](https://github.com/CrispStrobe/CrispASR/blob/main/docs/install.md)、[CrispASR 流式方案](https://github.com/CrispStrobe/CrispASR/blob/main/docs/streaming.md)
- WSL2 是当前明确选择的运行前提，首版验证 Windows 桌面与 WSL 服务互通；不因 Windows 原生后端未完成而阻塞首版，不自动换模型或退回全云。
- 本项目不引入 Docker 作为首版前置条件，也不卸载已有 Docker。WSL CUDA 使用 Windows NVIDIA 驱动；用户态 CUDA 依赖按推理栈匹配。[NVIDIA WSL 指南](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- 设置、字幕界面和模拟演示在 ASR 未启动时仍能打开；真实识别前检查服务。模型加载、采集失败、API 超时提供可理解状态；停止后停止新增请求并释放不再需要的资源。
- 当前仅有开发用模拟原型，不是免环境安装的普通用户发行版；真实模型接入和验收须等待明确授权。三个完整交付结果及验收边界见第 19 节。
- 账号、付费系统、移动端、自动辨认主播不作首版重点。术语手动输入、调用量及消费保护是后续产品建议，具体规格未定；费用估算不冒充实际账单。

### D4：2026-09-09 本机只读检查快照

以下是本次实际检查，不是安装清单或所有磁盘的完整软件盘点；PATH 未找到不等于全盘未安装，找到程序也不等于模型链路已验证。

| 环境 | 已确认情况 |
| --- | --- |
| WSL | Ubuntu，Conda `base` 激活；Python 3.11.7 位于 `/home/archtto/anaconda3/bin/python`，Conda 24.11.3；Git 2.43.0 位于 `/usr/bin/git`；Node 24.15.0 和 npm 11.14.1 来自 nvm |
| WSL PATH 未找到 | Linux uv、gcc/g++、make、cmake、rustc/cargo；不因此立即安装 |
| Windows uv | `C:\Users\19054\.local\bin\uv.exe`，版本 0.12.11，绝对路径调用成功；`uv python list --only-installed` 未列出解释器 |
| Windows Python | PATH 仅找到 WindowsApps 下 python/python3 入口，不能据此证明可用 Python 已安装 |
| Windows 其他入口 | 找到 Docker Desktop 的 docker.exe、CUDA Toolkit v12.6 的 nvcc.exe、nvidia-smi.exe、dotnet.exe；dotnet SDK 列表为空，未实测 GPU 推理或 Docker 引擎 |
| Windows 进程 PATH 未找到 | uv、Conda、Git、Node/npm、gcc/g++、MSVC cl、CMake、Rust/Cargo、PowerShell 7 pwsh；其中 uv 已由绝对路径确认存在 |
| 跨系统调用 | WSL 可找到 powershell.exe、cmd.exe、wsl.exe；本次在获准越过执行沙箱后已成功只读调用 Windows PowerShell，不表示所有后续调用天然拥有权限 |

Windows 持久化用户 PATH 已包含 `C:\Users\19054\.local\bin`，但当前 WSL 及其启动的 PowerShell 进程 PATH 未包含它，符合旧进程未继承更新的情况。先用绝对路径即可，后续在新终端验证，不重复添加 PATH 或重装 uv。Windows PATH 有重复项，本轮未清理，也未安装软件、修改环境或迁移仓库。

当前源码继续留在 WSL；模型缓存及 Linux 环境优先放 Linux 文件系统。[WSL 文件系统建议](https://learn.microsoft.com/en-us/windows/wsl/filesystems)

2026-09-22 用户指定 Windows 本机工作目录为 `D:\19054\localcapture`，用于客户端运行、调试及本机构建。WSL 默认挂载下对应 `/mnt/d/19054/localcapture`，实际使用前核对挂载和写入权限。这不改变 WSL 单一开发入口，不自动迁移仓库或建立第二套独立开发 checkout；需要暂存源码/产物时再明确范围，不覆盖目标目录已有内容。本轮仅记录路径，未创建目录、安装环境或复制文件；本机/CI 发布构建路线仍未最终选定。

## 16. 历史资料与代码的复核及吸收清单

### R1：复核范围与证据级别

2026-09-09，Luna Max 完成首轮只读盘点，主代理随后检查历史研究、当前产品行为约定、旧协议合同，以及音频、ASR 客户端、控制器、字幕窗口、翻译传输、URL/日志、打包脚本和代表性测试源码。结论是静态复核，不是依赖可安装、测试通过或目标机功能可用的证明。

截至 2026-09-09 的首轮静态复核，“我们写的协议文档”对应本文第 7 至 12、15 节的行为与接口约定，当时没有发现独立的新机器协议规格。此后本仓库已建立本地 WebSocket ASR v1 机器协议及实现；这不表示 Qwen 接入已验收。`archived/contracts/` 仍是旧 final-only 合同，不能作为新协议。桌面主进程与 Python 核心之间的 JSONL IPC 仍是第 19 节推荐，尚无精确 Schema。

历史研究原文移动到 `archived/LIVE_TRANSLATOR_RESEARCH.md`；只更新本文引用，不改写历史原文，不恢复旧 AGENTS 中的 Docker、Dolphin、仅 final 或固定供应商决定。新程序不得运行时导入 `archived/`。

### R2：值得提取的代码，以及必须修改的部分

| 旧实现及证据 | 可以吸收的明确行为 | 提取前必须改变/核验的边界 |
| --- | --- | --- |
| [audio.py](archived/windows-client/src/live_translator/audio.py)、[windows_audio.py](archived/windows-client/src/live_translator/windows_audio.py) | PCM 对齐校验、余数缓存、重采样排空、回调只入队、后台处理、有界队列与丢弃统计 | 不直接沿用回调 `time.monotonic()` 作为语音样本时间；分帧有连续递推且补零尾帧未表达有效样本数。新实现需要样本位置、缺口、有效尾长及跨重采样映射。16 kHz/100 ms 固定帧应按新协议确认，不冒充现有共识 |
| [asr.py](archived/windows-client/src/live_translator/asr.py)、[protocol.py](archived/windows-client/src/live_translator/protocol.py) | 先 start/ready 再送音频、独立收发、会话过滤、停止确认、超时与清理；生命周期确认不被业务队列阻塞 | 重新定义可变快照、源 revision、音频范围和过载事件；消息 seq 去重不能代替语义版本兼容。检查发送超时、服务认证和重连边界。旧 final-only 事件及常量不整体复制 |
| [urls.py](archived/windows-client/src/live_translator/urls.py)、[diagnostics.py](archived/windows-client/src/live_translator/diagnostics.py) | URL 格式/协议/凭据检查、本地 ASR 地址约束、轮转日志、已知密钥脱敏与处理器清理 | 地址检查不等于服务认证或端口访问保护；脱敏只覆盖已知值及有限模式，不代表任意异常和请求都安全。新增认证凭据和新供应商字段需同步处理 |
| [translator.py](archived/windows-client/src/live_translator/translator.py) | HTTP 客户端所有权、关闭、超时/状态码异常转换、响应基本校验及 MockTranslator | Anthropic 请求格式只适用于相应供应商，不默认沿用；旧纯文本输出改为结构化纠错/翻译结果，加入版本绑定和有限重试。旧“已确认上文”提示不能把历史译文当事实；环境代理策略另定 |
| [qt_overlay.py](archived/windows-client/src/live_translator/qt_overlay.py) | 若后续重新选择 PySide6，可定向复核透明置顶窗口、Qt Signal 更新入口、拖动/位置约束、设置保存、纯文本显示 | 2026-09-23 的 Qt 原型继续保留；它不是本轮推荐的正式外壳。字幕条与翻译段分离；默认中文、锁定与更正、按条阅读计时重做。旧内容键含状态/消息，会因状态变化重启隐藏计时；按内容调整高度可能改变位置。子控件鼠标透明及位置锁定都不等于整窗穿透 |
| [tests](archived/windows-client/tests/) | 伪造音频设备、进程内 WebSocket、MockTransport、离屏 Qt 和失败清理测试组织 | 旧 final 测试改为版本/锁定/乱序/缺口测试；测试夹具先服务新状态机，不让旧断言反向决定需求。本轮只读测试，未执行 |
| [build.ps1](archived/windows-client/packaging/build.ps1)、[ci.yml](archived/.github/workflows/ci.yml) | Windows 打包、运行库/证书/敏感文件检查、冻结 self-test、哈希产物的验证流程 | 旧脚本含 `python312.dll`、固定依赖及旧目录假设，不能原样运行；界面与采集库选定后再适配。保留告知检查，不把现有告知视为覆盖新模型/服务 |

这些是候选提取单位，不是承诺整个文件无需修改即可使用。配置与密钥代码也可参考，但本轮没有对其所有 ACL/异常分支进行完整安全审计，不把子代理初查当成全面认证。

### R3：不整体复用的核心

1. **应用发现与应用回环采集：新建。** 旧 `list_loopback_devices` 和 `device_index` 只对应输出设备；没有新方案的应用会话候选和进程树映射。旧采集最多改造成手动混音备用。[windows_audio.py](archived/windows-client/src/live_translator/windows_audio.py)
2. **语义段落、翻译调度和字幕状态机：重建。** 旧控制器每个 final 新建段并串行翻译；翻译前跳过不可见段，只有结果仍能更新可见字幕时才追加上下文。这直接违背显示历史与上下文分离，不能仅加 revision 字段修补。[controller.py](archived/windows-client/src/live_translator/controller.py)
3. **Qwen 服务与流式窗口管理：新建。** 旧客户端和合同不能证明存在相应服务，更不能证明模型持续实时。ASR 快照、音频覆盖、窗口重置/去重、显存和长会话验证仍需独立完成。
4. **旧机器协议：只保留规范化做法。** Schema、示例、模型、解析器、测试一致更新的原则可用；旧固定 3200 bytes 音频与 final-only 语义不充当新协议。[旧合同](archived/contracts/README.md)

### R4：研究文档中值得保留的前人经验

| 历史研究来源 | 新方案采用的明确行为 | 不直接搬用的部分 |
| --- | --- | --- |
| 第 2、3、4 节：VAD/提交/分段、LocalAgreement、可变 buffer | 三种边界分别管理；适配后端快照，保留有限可变尾部和版本；按本文 G1 寻找翻译机会 | 不假定 Qwen 有可靠提交事件或词时间戳，不照搬“只翻不可变 committed segment”或注意力算法 |
| 第 5 节：上下文、纠错、术语 | 原始 ASR 不覆盖；同次保守纠错/翻译；显示生命周期与上下文预算分开 | 30–120 秒不是实测最优值；历史中文不是事实；术语编辑/热词不因旧文出现而自动加入首版 |
| 第 6 节：评测 | 同时检查关键语义错误、过度纠错、首次有用中文延迟、修订干扰、长时间资源增长 | 不沿用游戏并行产品范围、4–4.5 GB 显存目标或未经核验的本机显存数字；无精确对齐不报告精确词延迟 |
| 第 7 节：LiveCaptions-Translator、Caption.Ninja、Subtitle Edit、Live-translation | 当前/前条分层、宽度排版、独立显示期限、状态与字幕分离、模拟事件走真实显示路径，来源及行为见 U1–U6 | 不照搬双语默认、固定动画/隐藏秒数或在 URL 放密钥；当时不锁定 PySide6。2026-10-25 的 Electron 基线仍是推荐而非实现，见第 19 节 |
| 第 8 节：Windows/WSL 责任分离 | Windows 处理采集/显示/翻译，WSL 处理 ASR；热路径内存传输，不靠共享音频文件轮询 | 不恢复强制 Docker、WSL uv 或已固定的 CI 打包路线 |

来源：[归档历史研究](archived/LIVE_TRANSLATOR_RESEARCH.md)。这里记录对旧研究的取舍，不重新声称其外链、模型价格或上游实现截至本日均已核验；使用外部实现时再定向核对当前原始来源。

### R5：提取顺序与剩余检查

先建立最小的新事件/状态模型与确定性测试，再围绕它提取小组件；Windows 应用采集可作为独立平台验证，不必等待完整模型链路。随后适配通信、Qwen、翻译及窗口，最后整理发布脚本。避免先迁移旧控制器，再被迫围绕旧 final 语义改需求。

复用前记录源文件、来源版本或哈希、保留行为、改动及验证结果；在本文维护摘要，在代码保留必要出处，不新建重复研究文档。新程序从新目录运行，归档只读。

本次仓库文件检查没有发现项目自身明确的授权文件，第三方告知只说明其依赖。记录为来源/授权待确认，不据此作法律结论，也不将它当作停止只读设计和测试规划的理由。实际分发前核对来源与依赖要求；本轮未复制源码。

未运行旧测试、构建、模型或真实 API；未验证 Windows 音频/全屏/点击穿透，也未验证 GPU、长会话与端到端成本。上述静态复核不代替这些实测。

## 17. 2026-09-23 模拟字幕原型实施状态

本节记录第 11 节模拟原型建议在后续获得授权后的实施结果，不回写第 16 节 2026-09-09 的历史静态复核结论。

- 已交付 headless 演示器、可选 PySide6 控制窗和独立悬浮字幕层。演示器通过 `SubtitleEngine.dispatch` 和 `drain_requests` 运行；模拟返回只使用实际排出的 `request_id`。`all` 顺序运行所有已登记场景，并在有界 `demo_scenarios` 中保留每场摘要，控制窗总历史最多 30 项且优先显示场景摘要。
- 普通场景的 `source` 是预先组织的语义片段；新增 `incomplete-source` 由 `DemoRunner` 将固定稳定文本和采集缺口送进真实 `StableSourceOrganizer`，再把其源事件送入同一引擎、请求、模拟回复和 UI 路径。此原型没有接入 ASR、没有处理真实音频，也没有调用真实翻译 API；预设中文仅用于界面和状态体验，不表示翻译质量结果。
- 覆盖层用 Qt `QFontMetrics` 的像素宽度分页，每页最多两行；当前条长文可手动翻页，完整原文通过有限历史查看；前一条也可在控制窗选中后查看全文。原位修订保持当前翻页位置。来源不完整标记在当前条/前一条标题旁显示，译文正文不拼接提示；标记更新不重置翻页或引擎阅读计时。有限历史单独显示“原文不完整”或“未标记不完整”及可读原因。位置锁只禁用拖动，不提供鼠标点击穿透承诺；`stop` 后核心会归档并清空活动字幕，历史仍可查看。
- 排版在标准库中保护常见组合附加符、变体选择符、肤色修饰符、ZWJ emoji、区域指示符配对和 Hangul 组合，并避免常见中英文闭合标点落在软换行行首。源码页可精确重建输入全文。此实现不是完整 Unicode UAX #29 grapheme 分段器；Indic conjunct、Prepend 等未覆盖规则及复杂文字塑形不保证精确排版，因此不宣称全 Unicode grapheme 精确。
- PySide6 仅作为本轮原型的可选 GUI 实现，不据此锁定正式 Windows UI 技术；现推荐 Electron＋React＋TypeScript 作为后续外壳基线，Qt 原型保留且不删除。`pyproject.toml` 声明最低 PySide6 6.6；本轮 WSL 离屏实测使用 Python 3.11.7、PySide6 6.11.1，PySide6 6.6 尚未验证。
- 较早的实施检查快照记录 `python scripts/verify.py` 共 103 项通过、`all` 播放八场；该数字保留为当时基线，不代表本轮结果。本轮来源标记集成后实际运行 `python scripts/verify.py`：自动发现 124 项并全部通过。`PYTHONPATH=src python -m live_translator --headless --scenario all` 成功结束，`PYTHONPATH=src python -m live_translator --list-scenarios` 列出新增场景；这些离屏及 headless 检查不替代真实桌面验收。
- 本轮 WSL Qt 环境为 Python 3.11.7、PySide6 6.11.1；项目声明的最低版本 PySide6 6.6 尚未验证。当前 WSL 执行 `fc-list :lang=zh family` 无输出，截图中的中文显示为方框。Qt 测试验证字符串和布局逻辑，不证明中文字形可读；截图不记作视觉验收通过，Windows 字体渲染和窗口视觉仍待验证。
- 尚未在 Windows 验证窗口置顶、全屏行为、鼠标交互、设备采集或发布包；尚未验证 WSL/Qwen 加载、持续 ASR 性能、真实日语翻译质量、延迟或 API 费用。Windows 工作目录未写入，未安装运行时、依赖或模型。

参考来源：2026-09-23 用户授权的模拟字幕原型任务；本节所列命令和版本来自本轮本地实测及 [pyproject.toml](pyproject.toml)，产品行为边界沿用 U1–U6。

## 18. 2026-09-23 稳定日语源文本整理器实施状态

- `src/live_translator/source_organizer.py` 将上游稳定文本快照组织为与 `SubtitleEngine` 公共合同兼容的 `source` 事件；它处理的是文本快照，不接收音频。
- 输入必须已由上游稳定化。本模块不实现 Qwen 流式稳定化或音频采集，也不代表 ASR 已接入。日语断句/启动阈值尚待真实语料和实时数据实测，当前取值不作为已验证参数。
- `source_incomplete`（默认 `false`）及可选 `source_diagnostic` 已由引擎和调度器带入 segment、上下文、请求及 cue。它们与翻译质量状态分开；`false` 仅表示“未标记不完整”。UI 对不完整 cue 显示轻量标题标记，历史详情单独展示状态及原因；未知 code 有纯文本回退。元数据更新不改变译文、不重置阅读计时或翻页。
- 版本合同：同一 segment、同一 source revision、同一原文的关闭事件可以刷新来源标记；若该版本已有待发/在途请求或已显示译文，不因这次元数据更新重复翻译。已显示 cue 只同步来源标记，保留译文及阅读计时。每个已发请求绑定其提交时的原文版本和来源元数据；旧版本返回沿用请求绑定的标记，不继承更新版本的完整性状态。精确匹配当前版本的结果才可采用该版本关闭时刷新后的来源标记。
- 新增模拟适配会为活动会话保留一个 `StableSourceOrganizer`，停止时释放；`organizer_input` 只接受当前活动会话。`incomplete-source` 使用该整理器产生 `capture_gap` 源事件，之后的完整句继续经同一模拟翻译链路显示。此验证只覆盖固定稳定文本和状态机，不证明真实 ASR、音频缺口检测或日语口语分段质量。
- 较早检查快照中源整理器单测为 20 项、全套为 103 项；本轮全套 `python scripts/verify.py` 自动发现 124 项并通过。WSL 离屏 Qt 通过只证明字符串和布局逻辑；由于当前环境没有可用中文字体，不能据此声称中文视觉可读。

参考来源：`src/live_translator/source_organizer.py`、`src/live_translator/engine.py`、`src/live_translator/scheduler.py`、`src/live_translator/demo.py`、`src/live_translator/ui.py` 及对应确定性测试。本节记录当前实现边界，不改变第 9 节待实测的触发策略，也不代表音频或 Qwen 链路已完成。

## 19. 桌面外壳、进程职责与交付边界

状态：桌面技术沿用 2026-10-25 推荐，尚未实现；部署位置按 2026-10-27 用户决定更新为 Windows 桌面＋WSL2 Python 核心/ASR，纯 Windows 推理是 TODO。当前 Python 模拟字幕原型继续保留；本节不要求立即迁移、安装工具或接入真实模型。WSL2 仍是唯一主要开发入口。模型与翻译路线重新评估见第 20 节；本节不据 Nola 或 Voxt 推导最终模型选择。

### A. 桌面技术比较与推荐

推荐 **Electron＋React＋TypeScript 桌面外壳＋Python 字幕核心＋独立 ASR 工作进程**。考虑依据是继续复用 Python 语义分段、调度与字幕状态，把窗口交互、密钥和进程管理放进桌面主进程；相近分工在 Nola 中有可检查的实现参考。推荐不等于代码可直接复用，也不代表包体、内存、采集或 Windows 构建已验证。

| 方案 | 对本项目的适配与代价 | 当前判断 |
| --- | --- | --- |
| Electron＋React＋TypeScript | 主进程、受限 renderer 和子进程职责可分开；当前 Python 核心放在 WSL2，私有 Windows Python 是后续选项。Electron/Node 运行时会增加包体、内存和更新维护成本，具体影响须实测 | 推荐基线；尚未实施 |
| Tauri | Web 前端可配原生宿主；Windows 开发/打包会引入 Rust 工具链与宿主桥接工作。可作为后续比较项，不以未实测包体数字决胜 | 暂不选作基线。[前置条件](https://v2.tauri.app/start/prerequisites/)、[Windows 安装包](https://v2.tauri.app/distribute/windows-installer/) |
| WebUI | 界面迭代可复用 Web 技术，但本项目仍需桌面窗口/overlay、应用发现、音频采集、进程生命周期和受控本地接口；单有网页界面不能提供这些宿主能力 | 不作为首选外壳；若后续提出完整宿主方案可复评 |
| .NET 桌面 | 可自包含部署运行时，适合 Windows 原生界面；仍需通过 IPC 调用 Python 核心，并维护另一套界面语言与状态映射 | 可行备选，不作为当前推荐。[.NET 部署](https://learn.microsoft.com/en-us/dotnet/core/deploying/) |
| PySide6 | 现有 Python 原型可继续运行，Python/Qt 也可随应用打包；已有窗口实现可参考。但正式 UI、Windows 采集与发布包均未验收，且目前不选它作为产品主线 | 保留现有原型，不删除；重新选用须有明确依据 |

表中的内存、包体、更新与开发成本是架构评估维度，不是测量结论。选择前需在 Windows 目标机比较实际安装包、空闲/运行内存、启动、升级和故障恢复。

### B. 进程职责与通信建议

1. **Electron 主进程**负责设置与凭据、LLM HTTP 请求、进程监管及采集桥接。API 密钥只留在主进程侧，不进入 ASR、renderer、字幕历史或日志。
2. **Python 字幕核心运行在 WSL2**，是语义分段、翻译调度、字幕版本和历史状态的唯一所有者。现有 `engine.py` 已有 `dispatch`、`drain_requests`，scheduler 的请求带 `request_id`；这为“核心产生请求、主进程执行 HTTP、核心接收结果”的分工提供静态适配依据，**不代表 IPC 已实现**。
3. **主窗口与字幕 overlay**共享同一会话状态。renderer 只传用户意图并渲染核心快照，不再维护第二套调度器或字幕版本状态。
4. **ASR 工作进程**不持有翻译密钥。现有本地 WebSocket ASR v1 协议和实现继续保留，本轮不修改 `contracts/`；它不证明任何特定模型已经接入或验收。
5. Windows Electron 主进程与 WSL Python 核心之间通信待验证；受管 wsl.exe stdio JSONL 或认证本地通道为候选，不预设 Windows Python。若使用 JSONL：使用有界消息和严格字段校验；stdout 只发协议，stderr 只写脱敏日志；消息携带关联请求、源版本和显示版本。停止确认、排空、取消、超时和重启语义以及精确字段仍待设计。PCM 不经 renderer，也不逐样本转 JSON；采集到 ASR 的音频传输另行选型。

Electron renderer 的安全基线为 sandbox、`contextIsolation`、`nodeIntegration=false`、校验 IPC 来源、只加载受控本地内容并设置 CSP。远程直播网页不进入特权 renderer。Electron `desktopCapturer` 捕获屏幕/窗口，不等于隔离指定应用进程音频。[Electron 安全建议](https://www.electronjs.org/docs/latest/tutorial/security)、[desktopCapturer](https://www.electronjs.org/docs/latest/api/desktop-capturer)

### C. 音频采集、WSL 运行和 Windows 原生 TODO

- 应用级音频的 Windows 候选为 Win32 process loopback。Electron 选择窗口本身不隔离该进程音频；设备输出混音仍是用户主动选择的备用来源，遵循第 4 节 A1/A2。
- 若 Electron/Node 宿主无法安全、稳定地完成所需采集，可评估小型原生 Windows helper；它是应用私有组件候选，不要求普通用户另装编译工具链。采集封装尚未选定。
- 当前开发基线的含义需要精确区分：Qwen README 的官方 streaming 路径仅提供 vLLM 实现且不返回时间戳；vLLM GPU 安装文档不支持原生 Windows。此事实只描述该 SDK/推理路径，**不能推论 Qwen 模型本身不能原生运行 Windows**。[Qwen Streaming](https://github.com/QwenLM/Qwen3-ASR#streaming-inference)、[vLLM GPU 安装](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/)
- Nola 当前主线（commit `fd74547acff7be4dc6f10b518d11391631eaa369`）含 Transformers 原生 Qwen runtime；CrispASR 文档列有 Windows CUDA 发布方式。CrispASR 说明了重叠窗口、持久缓存和文本前缀等流式方法，并指出重复转录累计音频不会保留 encoder/KV cache。它们是免 WSL 的具体候选，不是本项目验收结果或质量结论。[Nola 当前提交](https://github.com/CerealAxis/Nola-Translator/commit/fd74547acff7be4dc6f10b518d11391631eaa369)、[CrispASR Windows 安装](https://github.com/CrispStrobe/CrispASR/blob/main/docs/install.md)、[CrispASR 流式说明](https://github.com/CrispStrobe/CrispASR/blob/main/docs/streaming.md)
- Windows 原生后端尚未验证，现列为后续 TODO，不是首版发布门槛。首版明确使用 WSL2 Qwen/vLLM；需验证 Windows 采集到 WSL 的音频、字幕返回、长会话与停止恢复。不得把 Electron 外壳说成已去掉 WSL，也不静默切换模型或退回全云。

后续纯 Windows TODO：应用、私有运行时、模型分别版本管理和校验，下载支持大小/许可提示、进度、取消和恢复；不改全局 PATH、不后台运行 pip。该方向不阻塞当前 WSL 自用版本，也不承诺能消除 GPU 驱动和硬件要求。

### D. Nola 与 Voxt 的可借鉴行为

**Nola。** 本轮于 2026-10-25 研究时核对的较早提交 `5e89b8e14e7f938b2364115d3cfc6eb37509141b` 中，`package.json` 显示 Electron/React/TypeScript 外壳及通过 `extraResources` 携带 Python 引擎；引擎入口采用 stdio JSONL，协议带版本、字幕事件及模型 ready/loading 状态；`DESIGN.md` 描述单会话多窗口投影与 CJK 字体；翻译 scheduler 有限 LRU 缓存、并发控制，以及首文本/分段延迟指标。可借鉴受管 Python 子进程、版本化消息、共享会话多窗口、字体回退、有限调度与可观测性。[Nola `package.json`](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/package.json)、[引擎入口](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/engine/nola_translator_engine/__main__.py)、[协议](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/engine/nola_translator_engine/protocol.py)、[设计说明](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/DESIGN.md)、[翻译调度](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/engine/nola_translator_engine/translation/scheduler.py)

若实现翻译缓存，键需覆盖供应商、模型、语言、提示版本、上下文和术语，不能只按原文命中。**不直接搬用** Nola `runtime.py` 的稳定译文前缀/冲突丢弃策略：日语句尾否定可能晚到，当前条必须保留有界修订能力。`audio/capture.py` 的输出设备 loopback 不等于应用进程采集；`audio/resample.py` 中的回调时间或补零长度也不能直接当作真实音频时间。[Nola runtime](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/engine/nola_translator_engine/runtime.py)、[音频采集](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/engine/nola_translator_engine/audio/capture.py)、[音频重采样](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/engine/nola_translator_engine/audio/resample.py)

Nola 的原代码标注 GPL-3.0-only；直接 fork 是附条件备选，须先确认该许可下的分发要求及改造收益。GPL 不等于不能商业化。当前建议针对性重建外壳、保留本项目 Python 核心；复制或改写第三方代码前核对许可并保留所需告知。[Nola 许可](https://github.com/CerealAxis/Nola-Translator/blob/5e89b8e14e7f938b2364115d3cfc6eb37509141b/LICENSE)

**Voxt。** `sgl-project/sglang-omni/Voxt` 是 macOS SwiftUI/AppKit 方向，不适合直接 fork 到 Windows。本项目可借鉴：取消任务后等待其真实退出；用会话/输出代次拒绝迟到回调；受管子进程先优雅关闭，超时后再终止。[TrackedTaskStore.swift](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/Voxt/Voxt/Core/Utilities/TrackedTaskStore.swift)、[RecordingSessionLifecycle.swift](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/Voxt/Voxt/App/Recording/RecordingSessionLifecycle.swift)、[Voxt 架构说明](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/Voxt/docs/Architecture.md)

### E. 推荐交付框架与授权边界

建议把后续工作组织为三个可独立评审的完整结果，而非拆成一串零散小 phase：

1. **桌面外壳贯通现有模拟链。** 新窗口、overlay、Python 核心、请求/结果 IPC、共享会话、进程退出与错误状态走通现有模拟事件；验证安全隔离、单一调度器和字幕版本不回退。
2. **采集与跨环境贯通。** 获准后在 Windows 验证应用发现及 process loopback，必要时评估 helper；贯通 Windows 音频输入、WSL 字幕核心/模拟 ASR 与字幕返回，验证启动、断连、停止排空及恢复。Windows 私有 Python/ASR 打包不列首版前置。
3. **获明确授权后的真实模型验收。** 根据第 20 节的模型比较结果选定候选，再验证流式识别、GPU 和长会话、日语质量、翻译质量/费用/延迟及停止恢复。模型下载、真实模型接入和付费 API 使用均须有明确任务授权；本轮文档授权不包含这些操作。

截至本节更新，未实现 Electron 外壳或 JSONL IPC，未运行 npm/Node 构建命令，未安装工具、下载模型、访问 Windows 或调用 API。README 与现有 Python/Qt 原型说明保持原样；现有命令记录只代表既有入口，不据本节新增命令。

## 20. 2026-10-25 模型、运行时和翻译路线重新评估

用户明确允许重新商议模型和翻译方式。本节记录公开源码静态复核与建议，不是模型实测，也不宣布替换当前默认组合。选择单位是“模型权重＋量化版本＋推理运行时＋流式策略＋部署平台”，不能只比较模型名称。小型专用翻译模型也可能是生成式 LLM；“本地/云端”与“通用 LLM/专用机翻”是两个不同维度。

### M1：重点项目实际使用什么

本轮 Nola 模型复核固定于 `fd74547acff7be4dc6f10b518d11391631eaa369`，Voxt/sglang-omni 固定于 `6756aebd86a556d64a961910b86e74f9c048ea24`。第 19 节的 Nola 早期代码审查另有固定提交，不把两个快照混成同一版本。

| 项目 | ASR 实际注册或默认 | 翻译路径 | 对本项目的含义 |
| --- | --- | --- | --- |
| Nola | Qwen3-ASR 0.6B/1.7B、SenseVoiceSmall，具有 Transformers/FunASR、GGUF/llama.cpp、CrispASR 等不同适配；还注册其他可选模型。设置默认是 Qwen 1.7B HF，但中文指南向独显用户推荐 Qwen 0.6B Crisp，二者不是同一概念 | 本地 Hy-MT2 1.8B/7B、Index-Translate 2B/9B/35B-A3B、M2M100 418M；通用 LLM 接口；Microsoft Translator、Google Cloud Translation v2、MyMemory、Index 公共服务；部分阿里云 ASR 可复用其翻译输出。设置默认本地 Hy-MT2 1.8B Q3_K_M | 同一产品可以把多种后端放在一致的字幕流程之后；目录中出现不等于每种组合都通过 Windows/日语验收 |
| Voxt | 默认 `mlx-community/Qwen3-ASR-0.6B-4bit`；另有 Qwen 1.7B、Whisper、SenseVoice、Cohere、Nemotron 3.5、MOSS-Transcribe-Diarize、Parakeet 等注册 | 本地 MLX 通用 LLM、远程 LLM、独立 Hy-MT2 1.8B GGUF（Q4_K_M/Q8_0）。默认翻译提供者为本地 customLLM，目标语为英语；不能把它当成默认日中方案 | macOS/Apple Silicon 的 MLX/Metal 后端不能直接作为 Windows CUDA 可用证据；可参考模型选择和运行时管理 |
| SGLang-Omni 主线 | 多模型推理运行时，含 Qwen3-ASR、Nemotron 3.5、Whisper、MOSS 等服务路径；不是另一款 Windows 字幕客户端 | `/v1/audio/translations` 的文档路线是合适的多语言非 turbo Whisper 译英语；Qwen、Nemotron、MOSS 等不因此获得日中翻译能力 | 可借鉴实时会话和后端适配；不因存在 translations 接口就取消独立中文翻译步骤，也不把整个服务框架作为桌面应用前置条件 |

Nola 来源：[设置默认值](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/src/shared/settings.ts)、[中文模型指南](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/docs/nola-docs/zh-CN/getting-started/local-models.md)、[模型清单](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/models/catalog.py)、[运行时分发](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/runtime.py)。其云模型预设只是应用配置，不代表本轮已核验供应商可用性、价格或服务质量。

Voxt/主线来源：[ASR 能力注册](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/Voxt/Voxt/Transcription/MLXModelSupport.swift)、[应用默认值](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/Voxt/Voxt/App/VoxtApp.swift)、[专用翻译模型](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/Voxt/Voxt/Core/Models/GGUFTranslationModelSupport.swift)、[主线语音翻译边界](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/docs/basic_usage/audio_translations.md)。

历史参考也提供不同路线：LiveCaptions-Translator 使用 Windows Live Captions 作为识别源，再接 LLM、Google/DeepL 等翻译或自托管翻译；fmadore/Live-translation 提供本地 Whisper 和云端语音服务，其本地 Whisper 翻译目标是英语；WhisperLiveKit 文档提供 NLLB/NLLW 本地翻译以及 Alignatt4LLM 路线。上述仅补核项目说明，不是逐个适配器代码审计。Windows Live Captions 的语言包、系统字幕读取和音频来源控制需要额外验证，不能据此声称满足本项目应用隔离和样本时间协议。[LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator)、[Live-translation](https://github.com/fmadore/Live-translation)、[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit)

### M2：流式能力必须按执行方式判断

1. **缓存增量识别：** Nemotron 3.5 ASR Streaming 0.6B 的 FastConformer/RNN-T 路线维护跨块状态；官方模型卡把日语列为可直接转录语言，主线有 cache-aware PCM WebSocket 会话。它是首轮重点候选，不把 H100 吞吐或配置中的毫秒块长当作 RTX 4060 中文字幕延迟。[模型卡](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)、[主线适配](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/docs/cookbook/nemotron3_5_asr.md)
2. **累计音频重识别＋文本前缀：** Nola 的 Qwen Transformers 路线使用累计音频、前缀回滚；其 0.6B HF 特例以 3000 ms 块触发，不能把该参数当成本项目推荐延迟。SGLang-Omni Qwen 文档也说明没有跨调用解码器 KV 缓存。CrispASR 上游区分滚窗、缓存、文本前缀三种 streaming kind，Qwen 前缀流仍会重新编码累计音频。[Nola Qwen](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/recognition/qwen_streaming.py)、[主线 Qwen](https://github.com/sgl-project/sglang-omni/blob/6756aebd86a556d64a961910b86e74f9c048ea24/docs/cookbook/qwen3_asr.md)、[CrispASR 流式分类](https://github.com/CrispStrobe/CrispASR/blob/f469d6dd86e42d42d0358fbef6fa75cd0c2aba29/docs/streaming.md)
3. **累计音频重识别，无文本前缀：** Nola SenseVoice 每次识别当前整个片段，使用 VAD 和最大段长限制成本；首块 600 ms、后续 1200 ms 是该项目参数。其 CrispASR 适配也由通用 StreamingRecognizer 反复调用 `transcribe`，不能把 CrispASR 上游具备的所有流式能力自动归给 Nola 的调用方式。[SenseVoice 组织](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/recognition/sensevoice_streaming.py)、[Crisp 适配](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/recognition/crisp_asr.py)
4. **整段上传、文字流式返回：** Nola MiniMax 适配先由 VAD 形成完整 WAV 再上传，SSE 文本随后持续返回；这不等于边说边上传识别。不能用 `stream=true` 一个字段判断实时能力。[MiniMax 适配](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/recognition/minimax.py)

产品要求保留为“持续接收直播音频、有限延迟产生可修订文本、资源有界”。缓存增量是优势，不是唯一准入条件；累计重识别若实测达标也可以采用。此前排除 Dolphin 的决定不自动撤销；如重评，必须按同一执行方式和长会话预算重新证明可用，不能只加定时循环就称问题解决。

### M3：建议收敛的候选与验证顺序

| 层 | 首轮重点 | 对照或备选 | 目前不列为默认 |
| --- | --- | --- | --- |
| ASR | Qwen3-ASR 0.6B、Nemotron 3.5 ASR Streaming 0.6B | SenseVoiceSmall 作轻量对照；Qwen 1.7B/Whisper 作质量与资源对照 | Voxt 所列 Parakeet TDT v3 的语言表不含日语；MOSS-Transcribe-Diarize 在其能力表只列中英且增加多说话人复杂度。MOSS-TTS 是合成模型，不与 ASR 混用 |
| 运行时 | WSL2 Qwen 官方 streaming/vLLM 优先，Conda 隔离环境 | Windows 原生 CrispASR/Transformers 等作为后续 TODO；其他框架按必要性评估 | 不为一个客户端默认部署整套分布式推理框架，不把 MLX 量化权重当作 CUDA 通用权重 |
| 翻译 | 按 2026-10-27 最新偏好，优先低价云端 API；建议 Index 公共 API 与一家低价付费 LLM API 对照 | Microsoft/Google 正式机翻 API；本地 Hy-MT2 1.8B Q4、Index-Translate 2B Q4、M2M100 418M 降为后续备选 | 首轮不默认同卡常驻翻译大模型；不把免费公共端点作为可靠性承诺，详见第 21 节 |

Hy-MT2 和 Index 的模型卡、Nola 适配提供了本地专用翻译的具体依据，但通用翻译基准不能证明 VTuber 口语、专名、句尾否定或 ASR 错字处理质量。[Hy-MT2](https://huggingface.co/tencent/Hy-MT2-1.8B)、[Index-Translate-2B](https://huggingface.co/IndexTeam/Index-Translate-2B)。量化文件大小不是峰值显存，还需计算运行时、KV/中间状态、ASR 共存以及直播播放器的资源；不再以“4060 只能运行约 1B”作硬性判断，也不承诺上述组合已能共存实时。

Nola 的 Microsoft 适配指向正式 Translator 服务，Google 适配指向 Cloud Translation v2；Index 公共入口使用专用模型，而非传统词典查询。因此 API 格式、收费方式和底层模型类型分开描述。2026-10-25 尚未核验免费政策；2026-10-27 已确认 Index 官方提供免费公共 API，详见第 21 节，但配额、长期可用性及服务保障仍未确认，不写成无限免费。[网络翻译适配](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/translation/network.py)、[Google](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/translation/google_translate.py)、[Index](https://github.com/CerealAxis/Nola-Translator/blob/fd74547acff7be4dc6f10b518d11391631eaa369/engine/nola_translator_engine/translation/index_translate.py)

### M4：对产品和接口的明确影响

- 翻译接口应把当前原文、有限上文、术语、上版译文和版本关联作为独立数据。按后端声明其上下文/术语/结构化纠错能力，不把同一段指令式 JSON 原样发送给所有机翻 API。普通机翻后端可以只翻当前完整快照，仍由核心管理短句修订；缺少纠错能力时关闭该项，不伪造 corrected source。
- 所有后端共用现有段落、调度和字幕规则；本地便宜也不逐字重译。ASR 和翻译共享 GPU 时优先保护音频处理，限定翻译并发和等待预算，记录过载，不默默丢词、切换云端或上传音频。
- 若采用本地翻译，由宿主管理独立推理工作进程，通过统一请求/结果边界执行；Python 字幕核心仍是唯一调度和版本所有者。主进程负责云端 HTTP 与凭据，renderer 不直接调用任何模型。本节扩展第 19 节的执行后端，不在本轮改机器协议。
- 首版界面只暴露一个经过验证的推荐组合和高级设置，不照搬所有项目的模型商店。下载前展示容量和版本，模型未就绪时允许设置与模拟字幕启动。
- 获准真实评测后，先用相同日语直播样本对比 ASR 的关键语义错误、专名/数字/否定、静音幻觉、首次有用文本和稳定文本延迟、长时间内存/显存增长；再用固定原文及连续修订轨迹比较翻译忠实度、无依据补全、错误修订、首次有用中文和最终中文延迟。
- 成本同时记录每小时请求数、输入/输出 token 或计费字符、重译倍率、网络失败重试和本地资源竞争。不能只比每百万 token 单价，也不能将本地零 API 账单写成零成本。候选价格待确定供应商时按官方价重新核对。
- 最终验收必须包含 ASR＋翻译＋播放器并行的真实 Windows 包测试；离屏 UI、README 支持列表、其他机器跑分和模型能加载均不能替代。

本轮仅完成公开资料/源码研究和文档修改；没有下载权重、安装推理引擎、接入真实模型、使用付费 API 或操作 Windows。本节的候选列表授权范围仍是讨论和后续评测设计。

## 21. 2026-10-27 讨论同步与整体计划

### P1：本次讨论范围及文档同步清单

按主题归并，从竞品重新评估到本次同传模型讨论共七项，而不是按消息数计数。以下“已记录”指修改前的文档状态，不表示能力已实现。

| 主题 | 本次更新前 | 本次处理 |
| --- | --- | --- |
| Nola、Voxt/sglang-omni：直接 fork 或吸收设计 | 第 19 节已记录 | 保留针对性重建外壳、复用本项目核心的推荐；不是整仓迁移 |
| Electron、WebUI、其他客户端与免环境交付 | 第 15、19 节已记录 | 保留 Electron 推荐；随后按第 22 节将纯 Windows 推理降为 TODO |
| 竞品 ASR、运行时、翻译后端与流式差异 | 第 20 节已记录 | 保留静态研究与真实验收的区别 |
| 消费级 GPU 下优先便宜翻译 API | 基线存在，最新优先级未同步 | 更新第 2、6、20 节；本地小型翻译降为后续备选 |
| 云端 ASR 响应速度与费用 | 有候选背景，缺少本次比较 | 补录 P2 的延迟分解、成本示例及选择边界 |
| Bilibili Index-Translate 公共 API | 有模型及第三方适配，缺少官方 API 核验 | 补录 P3；免费与服务保障分开 |
| 腾讯 Hy-SimulMT 同传模型 | 尚未记录 | 补录 P4 的许可、语言、资源与适用范围 |

### P2：本地与云端 ASR 的响应速度、成本和选择

当前行为：默认本地流式 ASR；云端作为可选路线评估，未选定供应商，也未实现云端切换。若未来提供云端模式，必须由用户主动选择并明确音频上传和计费边界；本地失败不自动上传。

延迟按“收集音频块＋本地或服务端推理/排队＋网络传输（云端）＋稳定化/端点等待”分析。首次局部文字、稳定可翻译原文、首条有用中文和最终中文分别统计；不能用 ASR 首 token 或网络 RTT 代替字幕延迟。云端可能因更强推理能力获益，也可能受网络和服务端排队影响；本地无公网传输但会与播放器争用资源。未实测前，不承诺云端一定快或慢多少毫秒。

2026-10-27 官方标准价快照，以 `qwen3-asr-flash-realtime` 为例，按送入的音频时长计费：

| 区域 | 每秒输入音频 | 每小时连续送入 | 每月 60 小时 |
| --- | --- | --- | --- |
| 中国北京 | ¥0.00033 | ¥1.188 | ¥71.28 |
| 新加坡 International | ¥0.00066 | ¥2.376 | ¥142.56 |

以上只算 ASR，不含翻译，不扣试用额度或优惠。北京页面列 36,000 秒试用，按开通、模型发布或审批中较晚日期起算有效期 90 天，不是每月长期赠送。不要把不同模型的 token 计费与上述秒计费混算。按输入音频计价时，不预设持续送入的静音免费；未来如用 VAD 减少上传，要另测截词、上下文及时间轴连续性。价格示例不证明该区域账号、语言配置和服务在目标环境已经可用。

行为建议：本地默认不变；获授权评测时，用同一日语样本和相同稳定化要求比较本地与云端的质量、p50/p95 延迟及每小时费用，再决定是否正式提供云端选项。来源：[阿里云官方模型价格，Qwen-ASR-Realtime](https://help.aliyun.com/en/model-studio/model-pricing)。

### P3：Index-Translate 与低价云端翻译

用户已表达优先使用便宜 API，避免翻译大模型与 ASR 争用 RTX 4060。实施建议为：优先比较 Index 公共 API 与一家低价付费 LLM API；具体付费型号、提示词、预算、失败策略和最终默认供应商待测，不因参数更大就直接选择旗舰模型。小型本地专用翻译保留后续选项。

截至本次核验，Bilibili 官方提供 Index-Translate-35B-A3B 公共免费接口，入口为 `https://index-translate.bilibili.com/v1`，提供兼容 OpenAI 的调用方式；官方示例支持 SSE 返回、术语约束与翻译指令。它是云端专用翻译模型 API，本机不承载 35B 权重；文字流式返回也不等于可直接接收连续直播音频。

明确行为：依然按稳定语义片段请求翻译，由字幕核心管理上下文、请求合并和版本修订；不因接口支持 SSE 就逐 token 刷屏。术语、上下文、上版译文与纠错结构须按该后端能力实际验证，不假设所有兼容接口支持相同字段。免费端点未核验固定配额、SLA 和长期政策，不承诺永久无限免费；失败时提示并执行有界重试，不默认切换到付费服务或不同数据接收方。

获授权后的评价使用日语直播口语，重点检查专名、否定、指代、省略、ASR 错字、增量修订与无依据补造，同时统计首条有用中文延迟、限流和失败率。宣传基准与支持语言数量不能替代本场景验证。Index-Echo 等音频产品另行判断，不能凭系列名称把文本接口当成日语 ASR。

来源：[Bilibili 官方项目及免费 API 公告](https://github.com/bilibili/Index-Translate)、[官方调用示例](https://github.com/bilibili/Index-Translate/blob/main/inference/llm/call_api.py)。本次仅阅读公开资料，没有向翻译端点发送请求。

### P4：Hy-SimulMT 的定位与取舍

腾讯混元 Hy-SimulMT 于 2026-10-26 发布，公开推理代码与模型权重；官方许可证明确公开的推理代码、参数及权重使用 Apache-2.0，第三方组件遵循各自许可。可按许可用于商业用途，不归为商业闭源模型；这不表示训练数据及所有训练过程都已公开。

官方明确支持中英双向实时同传：持续接收音频并生成译文；语音播报及声音克隆需另配 TTS。当前没有官方日语到中文支持依据，不作为本项目默认 ASR 或翻译后端，也不因此扩展产品语言范围。30B-A3B 的激活参数不能当作全部权重的内存需求；不推荐作为 RTX 4060 默认本地部署方案，未测显存及速度。

官方约 3 秒是 RealSI 评测的 StreamLAAL 翻译滞后指标，不是首次译音、首条字幕或任意机器端到端延迟保证。已找到开放权重、自托管工具与 App 体验入口，尚未确认可供本项目使用的官方公共商业 API、价格与 SLA。

可吸收的方向是连续音频输入、增量输出与质量/滞后的联合评价；以后若研究其输出决策，需具体检查实现再落到行为，当前不声称已提取算法。它与 Hy-MT2 文本翻译模型分开记录。

来源：[官方项目](https://github.com/Tencent-Hunyuan/Hy-SimulMT)、[模型卡](https://huggingface.co/tencent/Hy-SimulMT-30B-A3B)、[官方许可](https://github.com/Tencent-Hunyuan/Hy-SimulMT/blob/main/LICENSE-Hy-SimulMT.txt)。

### P5：整体计划与实施顺序

本表是现有方案的阅读索引，不另设一套产品规格；细节以对应章节为准。

| 工作面 | 当前整体规划 | 状态与依据 |
| --- | --- | --- |
| 产品 | 完全不懂日语的用户观看日语 VTuber 直播，以中文字幕理解内容；Windows 11 首发 | 已确定边界；第 1、4 节 |
| 用户流程 | 打开应用、选择推荐音频来源、主动开始、查看独立悬浮字幕、有限回看、停止；设置和演示可脱离模型启动 | 已确定方向；第 4、11、15 节 |
| 采集 | 指定应用优先，活动应用列表简单预选；设备混音手动备用，不默认麦克风，不承诺标签页隔离 | 行为已定，Windows 封装和实测待完成；第 4、19 节 |
| ASR | 本地优先；Qwen 0.6B 与 Nemotron 3.5 Streaming 0.6B 重点比较，SenseVoice 轻量对照；有界窗口、尾部排空和跨窗口去重 | 候选而非最终选型；第 7、20 节 |
| 翻译 | 低价云端 API 优先；Index 公共服务与低价付费服务对照；本地小型模型后置 | 用户成本偏好＋评测建议；P3 |
| 语义与时间 | 音频样本时钟、ASR 原文版本、段落和字幕条分开；稳定语义短句先译，后续有限修订 | 第 7–10 节；阈值待真实日语验证 |
| 字幕 | 前一条弱化、当前条突出；仅当前条原位修订，关键历史错误显式更正；跟上直播、有限历史、不截断全文 | 第 11 节；已有模拟原型，Windows 体验待验收 |
| ASR 纠错 | 可在翻译请求内保守处理错字；保留原始识别，不补造丢失语音、否定、数字和人物 | 第 12 节；默认启用与否待测 |
| 桌面架构 | 推荐 Electron＋React＋TypeScript；Python 核心唯一拥有分段/调度/版本；ASR 独立进程；宿主执行 HTTP 并管理密钥 | 第 19 节；推荐基线，外壳与 JSONL 尚未实现 |
| 开发和发布 | 自用优先；WSL2 开发并运行 Python 核心与 Qwen/vLLM，Conda 独立环境；Windows 只承担桌面与采集，不要求 Windows Python，不引入 Docker | 第 22 节；纯 Windows 推理及私有 Python 打包为 TODO |
| 复用 | 定向提取 archived 工具与测试；吸收 Nola 的进程/多窗口设计、Voxt 的取消/生命周期处理；保留现有核心及 Qt 原型 | 第 16、19 节；不整仓恢复，不直接 fork 作为默认路线 |
| 隐私和可靠性 | 默认不上传音频/保存录音；翻译文本发送边界明确；密钥仅后台；有界队列、可观察过载、拒绝迟到旧结果、停止排空 | 第 4、7–12、19 节及 AGENTS.md |
| 评测与验收 | 确定性模拟测试→Windows 采集/窗口/打包→获授权后真实日语 ASR 与翻译、长会话、费用和延迟 | 第 17–20 节；历史测试不冒充本轮实测 |

按第 19 节组织完整交付：先把桌面外壳、共享会话和现有模拟核心贯通；再完成 Windows 采集和 WSL 通信贯通；最后在获得真实模型/API 授权后完成模型比较和端到端验收。Windows 工作目录保留 `D:\19054\localcapture`；用户未解除“不操作 Windows 物理机”的限制，本次不写入或执行 Windows，后续 Windows 工作需取得相应授权或明确获准的 Windows CI 环境。

现有资产包括 Python 字幕核心/调度、稳定原文整理器、模拟演示与可选 Qt UI、本地 ASR WebSocket v1 协议及传输/模拟组件。此处依据现有文档和仓库入口盘点，不宣称本轮重新执行测试；真实采集、模型、API、Electron 正式客户端及发布包尚未验收。仍需确定的参数集中见第 14 节，不通过新增模型讨论悄悄改动机器协议。

本次仅更新产品文档及必要的协作规则引用，保留归档原文和已有代码；未安装环境、下载模型、调用推理 API 或操作 Windows。

## 22. 2026-10-27 最新决定：自用优先，推荐 WSL 推理

用户明确选择：项目偏向自用，希望利用已有 WSL 环境减少配置负担；Qwen/vLLM 的 WSL 实现作为推荐方案，纯 Windows 本地推理列为 TODO。本节取代第 19 节此前将“普通用户免 WSL”设为首版发布门槛的优先级。

明确行为：

- 开发继续统一 WSL2，沿用 Conda 独立环境；Python 字幕核心和 ASR 均运行在 WSL2，Qwen streaming/vLLM 优先实现与验证。不要求为当前方案额外配置 Windows Python。
- Windows 负责应用音频采集、桌面窗口和字幕悬浮层；Electron＋React＋TypeScript 保留为推荐外壳。翻译仍优先低价云端 API，Windows 宿主管理凭据和 HTTP，WSL 核心唯一拥有分段、调度与字幕版本。
- Windows 与 WSL 的启动和通信需专门设计。受管 wsl.exe stdio JSONL、认证的本地网络通道是候选；不直接照搬 Nola 启动 Windows Python 子进程的假设。明确发行版/Conda 环境定位、就绪、会话鉴权、消息大小、断连、取消和排空，验证 WSL 重启后的恢复。PCM 不经 renderer 或逐样本 JSON，不为连通性暴露无认证服务。
- 保留已有 ASR WebSocket v1；本文不改机器协议，也不声称跨环境通信、Qwen 加载或真实字幕链路已实现。
- Windows 原生 ASR、私有 Windows Python 打包、免 WSL 一键安装作为后续 TODO；不因此替换当前 Qwen/vLLM 基线，也不阻塞自用首版。
- 首版完成标准：在用户 Windows＋WSL2 环境中，稳定采集指定应用的直播声音、持续识别日语、调用翻译并显示可修订中文字幕，停止和异常可恢复；按前文要求实测质量、延迟、资源与费用。Windows 窗口/采集仍需 Windows 验证。

Nola 的经验保留为后续实现依据：它支持本地模型与第三方云服务，打包基础 Python，引擎运行时和模型可分开安装；这说明可以由应用管理依赖，不代表本项目现在必须承担该打包工作，也不消除 vLLM 的平台要求。来源：[Nola README](https://github.com/CerealAxis/Nola-Translator)、[Python 打包配置](https://github.com/CerealAxis/Nola-Translator/blob/main/package.json)、[基础 Python 构建](https://github.com/CerealAxis/Nola-Translator/blob/main/scripts/build-python-base.ps1)、[运行时清单](https://github.com/CerealAxis/Nola-Translator/blob/main/build/runtime-catalog.json)。上述为公开源码核对，不是本机安装验证。

授权边界：本次为同步文档、提交和推送；不安装环境、不下载或接入模型、不调用付费 API、不操作 Windows 物理机。后续执行仍遵循对应任务授权。
