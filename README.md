# Live Translator

日语 VTuber 直播的中文字幕客户端。交付为自带运行时的 Windows x64 完整便携包；真实 ASR 模型配置仍单独处理。

## 使用完整客户端

在 [dist](dist/) 中找到最新通过验证的 ZIP，完整解压后双击 `LiveTranslator.exe`。不要只复制 exe，旁边的 `resources`、运行库和资源文件都是客户端组成部分。当前包的位置、大小、SHA-256 和验证结果记录在 [latest-package.json](dist/latest-package.json)。

用户无需安装 Python、uv、Anaconda、Conda、Node.js、npm、Electron 或 VC++ 运行库，也无需进入项目目录执行命令。Electron、私有 CPython、字幕核心和生产依赖均随包提供；设置在当前 Windows 用户的应用数据目录保存，不依赖解压位置。

首次可直接点击“播放基础演示”。真实识别仍需单独完成 ASR 模型配置；翻译服务地址和密钥属于客户端设置。当前便携包未作发布者代码签名。

## 从源码开发运行

以下命令仅供开发者修改源码时使用，完整客户端用户无需执行。本机已有 uv 管理的 `core/.venv` 和桌面依赖，在 PowerShell 中运行：

```powershell
cd D:\live-translator\desktop
npm start
```

点击“播放基础演示”即可体验字幕，不需要配置 ASR、密钥或音频来源。“字幕演示”页面还提供否定晚到、乱序返回、失败、长译文和音频缺口等场景。主窗口与独立悬浮窗显示同一个 Python 核心的字幕；停止后清屏，当前会话的完整原文和译文仍可回看，开始新会话时清空回看。

默认识别方式是“预设文本模拟”。选择声音来源并点击“开始采集测试”后，应用会启动本机模拟进程，根据声音活动展示预设日文，再使用离线模拟翻译。它不识别主播讲话，也不会调用翻译 API。只有点击开始后才采集声音，不保存录音，不默认采集麦克风。

“指定应用”采集所选进程树；同一浏览器其他发声页面可能混入。输出设备混音是手动选择的备用模式，可能包含该设备其他应用的声音。采集失败不会自动扩大来源。

## 设置与悬浮窗

在停止状态下保存设置。翻译接口使用完整的 Chat Completions 地址、模型名和可选 API 密钥，支持 HTTPS，或用于本机服务的 loopback HTTP；保存不会发出网络请求。默认使用纯译文模式，结构化 JSON 和保守纠错需要自行选择，并以实际后端能力和质量验证为准。

API 密钥与 ASR 服务令牌由 Electron 主进程通过系统加密接口保存，不返回界面、不进入 Python 翻译请求或字幕历史；密码框留空会保留现有值，提供单独的清除选项。当前仍可保持全部模拟设置，无需配置真实 ASR。

可以调整悬浮窗字号和宽度，解锁位置后拖动顶部移动。启用鼠标穿透后，在主窗口关闭穿透即可恢复操作。当前条允许有限修订，前一条锁定；较窄窗口中的长条可以翻页，完整文本保留在回看中。字幕过期或停止后不继续显示占位字幕。

## 检查

以下命令只使用已经安装的项目依赖，不安装软件、不下载模型，不调用外部翻译服务：

```powershell
cd D:\live-translator
.\core\.venv\Scripts\python.exe scripts/verify.py
.\core\.venv\Scripts\python.exe scripts/verify.py --desktop-smoke
```

默认检查 Python 测试、TypeScript 类型、桌面构建和 Node 测试。`--desktop-smoke` 额外启动隐藏的真实 Electron 窗口，检查中文演示同步、renderer 隔离、系统密钥加密、窗口控制、停止、重启和进程退出。截图与结果写入 `artifacts/desktop-smoke/`，不代表人工验收了全屏或鼠标穿透。

纯命令行演示：

```powershell
cd D:\live-translator\core
uv run --frozen --offline python -m live_translator demo --list
uv run --frozen --offline python -m live_translator demo --scenario all
```

可选的 `desktop` 目录下 `npm run smoke:audio` 会播放短测试音，只采集该受控进程，使用预设 ASR 和本机假翻译接口验证整条链路，结果写入 `artifacts/audio-probe/`。常规检查不执行它，模型配置与真实 ASR 质量不属于该测试。

## 新环境安装

此处是安装步骤，不是每次启动所需的操作。本次接手沿用已有环境，没有重新安装全局工具。需要已有 Python 3.13、uv、Node.js 和 npm：

```powershell
cd D:\live-translator\core
uv sync --frozen
cd ..\desktop
npm ci
npm start
```

uv 会创建项目独立环境；本机开发环境选用 Anaconda 提供的 Python 3.13.5，依赖安装在 `core/.venv`，不继承 base 的包。只有这个开发环境依赖 `D:\Anaconda`，交付包使用自己的 CPython，不依赖该目录。首次安装桌面依赖会下载 Electron，不包含 ASR 模型。

## 构建完整客户端

在已安装项目依赖的 Windows 构建机执行：

```powershell
cd D:\live-translator
.\core\.venv\Scripts\python.exe scripts/package_windows.py
```

脚本复用锁定的 Electron 和 Python 生产依赖，首次下载约 11 MB 的官方 CPython 嵌入包并核对固定 SHA-256。它不复制开发虚拟环境，不携带测试依赖、用户设置或密钥，不在用户运行时安装包。原生 DLL 依赖检查及隔离运行验证通过后才生成完整 ZIP、逐文件清单和 SHA-256 文件。

隔离验证将客户端复制到包含中文和空格的新路径，PATH 只保留 Windows 系统目录，并将 Python、Conda、Node 和 uv 的开发环境变量指向无效位置。它检查包内运行时、界面、字幕同步、设置加密、停止、重启和子进程退出；结果位于 `artifacts/package-validation/`。实际包支持 `LiveTranslator.exe --self-test <结果目录>`，该诊断只运行预设演示，不配置真实 ASR。

实际验证范围、部署取舍及待验证项统一记录在 [PRODUCT_DISCUSSION.md](PRODUCT_DISCUSSION.md#23-2026-10-28-接手后的非模型桌面开发版)。机器协议见 [contracts](contracts/README.md)。`archived/` 是历史参考，`claude-context/` 是本机忽略的历史会话备份，当前程序不会从这些目录导入代码。
