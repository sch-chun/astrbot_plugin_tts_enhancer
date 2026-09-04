# AstrBot TTS Enhancer

> **让 AstrBot 的回复自然带上情感、方言与个性化声音，**
> 解决"传统文本输入"与"TTS 供应商丰富能力"之间的不平衡，以高可插拔架构轻松接入任意语音服务。

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-blueviolet)](https://github.com/AstrBotDevs/AstrBot)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.2.1-green)](CHANGELOG.md)

---

## 为什么需要它？

AstrBot 默认只能向 LLM 传递文本，但现代 TTS 服务早已不满足于"读文字"——它们支持调整音量、语调语速甚至情感标签、多语种和方言、音色克隆、声音设计……

传统调用方式只能扔进去一个 `text` 参数，这些能力全被浪费了。更麻烦的是，许多供应商只提供 API，没有易用的 UI 来管理音色克隆与设计。

**TTS Enhancer 为这种"不平衡"而生：**

- **高可插拔的多供应商架构** – 每个供应商独立实现适配器，互不干扰。
- **能力说明书机制** – 每个供应商配套一份 Markdown 文档，描述其支持的参数与用法，SubAgent 据此智能生成最优参数。
- **按需前端 UI** – 为缺乏 Web 界面的供应商提供可复用的管理组件；已有官方控制台的供应商可直接跳转链接，无需重复实现。

---

## 核心设计

### 1️⃣ 多供应商适配器（Provider Adapter）

每个 TTS 供应商只需继承 `TTSProviderAdapter` 抽象类，实现：

- `get_tool_schema()` → 定义 Function Calling 的参数结构
- `get_subagent_system_prompt()` → 将能力说明书注入 SubAgent
- `call_api()` → 调用真实 API
- `create_voice() / list_voice() / delete_voice()` → 音色管理

新增一个供应商只需编写一个 Python 文件和一份 Markdown 文档，即可自动被插件发现。

### 2️⃣ 能力说明书（Capability Docs）

每个供应商附带一份 `{template_key}.md` 文档，详细说明：

- 支持哪些参数（`instruction`, `volume`, `rate`, `pitch`, `language_hints`……）
- 情感标签列表、方言列表、使用示例
- 参数范围与默认值

SubAgent 在合成时会**动态读取这份文档**，根据对话上下文生成符合该供应商能力的参数，绝不越界。

### 3️⃣ 前端 UI：可复用组件 + 按需定制

插件提供了**可复用的前端组件**（`BailianSpeechSynthesizer`），封装了音色管理的标准交互流程（上传/URL/设计三种模式、试听、列表、删除）。

但具体到每个供应商：

- **需要前端界面** → 复用通用组件，仅需在 `app.js` 中注册并配置 `providerConfig`（语言列表、帮助链接等）
- **已有官方 Web 控制台** → 直接配置外链跳转，无需重复实现
- **有特殊交互需求** → 可单独编写自定义组件

> 这种设计的初衷是：**为那些只有 API、没有 UI 的供应商补齐管理体验**，而非强制统一。

---

## 支持的供应商

| 供应商 | 模型 | 情感控制 | 系统音色 | 复刻 | 设计 | 方言 |
|---|---|---|---|---|---|---|
| **百炼 Qwen Audio 3.0 TTS** | flash / plus | 30+ 标签 + 拟声 + 自然语言指令 | ✅ | ✅ | ✅ | 20+ 种 |
| **百炼 CosyVoice v3.5** | flash / plus | 自然语言指令 | ❌（仅复刻/设计） | ✅ | ✅ | 17+ 种 |

> 更多供应商（Edge TTS、MiniMax、GPT-SoVITS 等）正在规划中，欢迎社区贡献！

---

## 快速开始

1. **安装插件**
   ```bash
   cd <AstrBot>/data/plugins
   git clone https://github.com/sch-chun/astrbot_plugin_tts_enhancer.git
   ```

2. **配置供应商**
   插件配置 → 添加至少一个供应商。

3. **让模型输出 `<tts>` 标签**
   主模型在回复中包裹 `<tts>要合成的文本</tts>`，插件将自动处理并发送语音消息。

4. **（可选）使用 Tool 调用**
   插件已注册 `send_voice_to_user` 工具，模型可主动决定何时发语音，无需标签。

---

## 配置项（精简）

```yaml
enable_enhance: true              # 启用 SubAgent 自动增强
enhance_llm_provider: ""          # 用于增强的模型（为了省钱可以选择能力稍差的便宜甚至免费模型）
context_window: 10                # 上下文轮次
dual_output: false                # 同时输出文本和语音
log_enhanced_params: false        # 打印生成的参数
providers:                        # 供应商列表（支持多个回退）
  - __template_key: bailian_qwen_audio_3_0_tts
    display_name: "我的语音"
    priority: 0
    api_key: "sk-..."
    workspace_id: "ws-..."
    model: "flash"
    voice: "longanhuan_v3.6"
    timeout: 60
```

详细配置项说明请参考插件配置页面的帮助信息。

---

## 架构一览

```
┌─────────────────────────────────────────────────────────────┐
│ [主模型]  输出 "<tts>今天天气真好</tts>"                     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [TTS Enhancer 插件]                                         │
│   1. 解析 <tts> 标签                                        │
│   2. 获取最近上下文（窗口大小可配）                          │
│   3. 构造 SubAgent 提示（含供应商能力说明书）                │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [SubAgent]  调用 tts_enhance 工具                           │
│   输出结构化参数：{ text, instruction, volume, rate, pitch,  │
│                     language_hints }                         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [Provider Adapter]  校验参数 → 调 API → 下载音频            │
└─────────────────────────────────────────────────────────────┘
```

---

## 贡献指南

欢迎新增 TTS 供应商！只需几步：

1. **编写适配器**：在 `providers/` 下新建 `<vendor>_<model>.py`，继承 `TTSProviderAdapter` 或已有的公共基类。
2. **撰写能力说明书**：创建 `providers/docs/<template_key>.md`，详细描述参数、标签、示例。
3. **前端接入（按需）**：
   - 需要 UI：在 `pages/tts_manager/components/` 下新建 Vue 组件，引用通用组件并配置 `providerConfig`；在 `app.js` 中注册映射。
   - 已有官方控制台：仅在 `app.js` 中配置外链即可。
4. **添加配置模板**：在 `_conf_schema.json` 中补充供应商配置项。

所有新增供应商将自动被工厂发现并加载，无需修改核心代码。

---

## 文档与更新

- [CHANGELOG.md](CHANGELOG.md) – 完整版本记录
- 能力说明书样例：`providers/docs/bailian_qwen_audio_3_0_tts.md`

## 许可

GNU Affero General Public License v3.0 – 详见 [LICENSE](LICENSE)
