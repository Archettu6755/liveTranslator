# 机器协议

本目录的 Schema、示例、Python 模型和解析器共同维护当前接口；旧 `archived/contracts/` 的 final-only 协议不适用。合同一致性检查位于 `core/tests/test_contracts.py`，它检查示例、编解码器与本目录所用的 Schema 约束。

## ASR WebSocket：asr.v1

[Schema](asr-v1.schema.json) 与 [示例](asr-v1.examples.json)。服务只绑定 `127.0.0.1`，路径为 `/v1/asr`，握手要求 `Authorization: Bearer …`。应用管理的模拟进程使用每次启动新生成的令牌；外部本机服务的令牌经用户设置，不传给 renderer。

客户端先发 `session.start`，收到 `session.ready` 后再发送音频。音频为 16 kHz、单声道、有符号小端 int16 PCM。每条二进制消息前 8 字节是小端 uint64 `start_sample`，后面是有效 PCM；尾帧按实际长度发送，不补零冒充有效样本。整条二进制消息最多 65536 字节，JSON 消息也受 64 KiB 接收限制。

服务发送可修订的窗口全文 `transcript.snapshot`、音频时间上的 `speech.activity`、可观察的过载事件及错误。`seq` 在会话内递增，音频时间不是结果到达时间，不提供词级时间戳。客户端显式报告采集缺口。

停止发送音频后发 `session.stop`，服务按序排空已接受的音频，提交尾部窗口，最后返回 `session.stopped`。客户端等确认后关闭连接；连接及停止均有超时。默认 `scripted` 后端只按声音活动输出预设文本，`qwen` 后端当前明确返回未配置错误，不伪造真实识别结果。

## 桌面与核心：host-core.v1

[Schema](host-core-v1.schema.json) 与 [示例](host-core-v1.examples.json)。受管 Python 进程通过 UTF-8 stdin/stdout JSONL 通信，每行最多 1 MiB，输入队列最多 128 条；stderr 用于脱敏诊断。PCM 音频不经过该通道，翻译 API 密钥不传给 Python。

桌面先发 `hello`，等待 `core.ready`，随后配置翻译模式和术语。桌面为每个命令附带 `command_id`，核心输出携带同一进程内递增的 `seq`。`snapshot.version` 是显示状态版本；会话 ID、源版本及字幕条版本各有独立含义。核心重启后桌面更换进程代次，拒绝旧进程的迟到翻译。

`command.accepted` 表示命令已接受。停止以 `session.stopped` 为完成确认，等待期间核心继续接收翻译返回；退出以 `core.exiting` 及实际进程退出为完成证据，不能把发送停止或退出命令等同于已完成。

核心输出 `translate.request`，绑定 `request_id`、`session_id`、`source_revision` 和不可变提示消息。Electron 主进程执行一次 HTTP 请求并返回 `translation.result`，保留关联字段。每段一个在途请求和一个最新待处理版本由 Python 调度器管理；HTTP 执行端不另建重试调度，最多同时执行两个请求，6 秒超时，回复体最多 256 KiB，不跟随重定向、不向界面转发服务错误正文。失败重试、版本兼容、锁定、历史和显示期限由核心决定。

renderer 只使用 preload 暴露的用户意图接口，不接收原始翻译请求或凭据。主进程检查窗口、主 frame、受控本地 URL、操作权限及字段；悬浮窗没有开始采集或修改服务设置的权限。
