# AstrBot TTS Enhancer

> 多供应商智能语音合成插件，支持 SubAgent 模式自动注入情感标签与指令控制，让 AI 说出有温度的话。

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-blueviolet)](https://github.com/AstrBotDevs/AstrBot)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.2.1-green)](CHANGELOG.md)

## 这是什么

让 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的回复**自然带上语音**，并且会根据上下文自动调整情绪、语速、方言，而不是冷冰冰的一字一板。

- 主模型输出 `<tts>...</tts>` 包裹的文本
- 插件把上下文交给 SubAgent，按当前供应商的能力说明书调用 LLM 注入情感标签 / 指令 / 音量 / 语速 / 音调
- Provider Adapter 拿到结构化参数后调用 TTS API，输出音频消息

支持两种调用路径：
- **标签触发**：主模型在回复中用 `<tts>文本</tts>` 包裹要转语音的部分
- **Tool 调用**：注册 `send_voice_to_user` 函数工具，模型可主动决定何时发语音

## 核心特性

- 🎭 **情感自适应**：根据对话上下文自动选择情感标签 / 自然语言指令
- 🗣️ **方言支持**：通过自然语言指令说方言（Qwen 支持 20+ 种、CosyVoice 支持 17+ 种）
- 🎨 **声音复刻 / 设计**：内置 Web 页面管理音色，可上传音频复刻你的声音，也能用自然语言描述生成新音色

更多能力（多供应商回退、多语种、参数校验）见下方「支持的供应商」与「进阶用法」。

## 支持的供应商

| 供应商 | 模型 | 情感控制 | 系统音色 | 复刻 | 设计 | 方言 |
|---|---|---|---|---|---|---|
| **百炼 Qwen Audio 3.0 TTS** | flash / plus | 30+ 情感标签 + 拟声标签 + 自然语言指令 | ✅ | ✅ | ✅ | 20+ 种 |
| **百炼 CosyVoice v3.5** | flash / plus | 自然语言指令 | ❌（仅复刻/设计） | ✅ | ✅ | 17+ 种 |

更多供应商规划中（欢迎 PR）。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│ [主模型]  输出  "<tts>今天天气真好呀</tts>"                   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [TTS Enhancer 插件]                                          │
│   1. 提取 <tts> 标签中的文本                                  │
│   2. 取最近 N 轮对话作为上下文窗口                            │
│   3. 构造 SubAgent 系统提示（含 Provider 能力说明书）         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [SubAgent]  调用 tts_enhance Function Tool                   │
│   输入：原文 + 对话上下文                                     │
│   输出：{ text, instruction, volume, rate, pitch,            │
│           language_hints }                                   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [Provider Adapter]  解析参数 → 调 API → 下载音频              │
│   - BailianQwenAudio3_0TTSAdapter                            │
│   - BailianCosyVoiceV3_5Adapter                              │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 安装

把仓库克隆到 AstrBot 的插件目录：

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/sch-chun/astrbot_plugin_tts_enhancer.git
```

或在 AstrBot Dashboard → 插件市场搜索 `astrbot_plugin_tts_enhancer` 一键安装。

### 2. 配置供应商

打开 **Dashboard → 插件配置 → TTS Enhancer**，在「供应商列表」中添加至少一个供应商：

- **百炼 Qwen Audio 3.0 TTS**：填入阿里云百炼 API Key + Workspace ID
- **百炼 CosyVoice v3.5**：同上（v3.5 不支持系统音色，请用复刻或设计生成的音色 ID）

> 💡 在阿里云百炼控制台 [开通 Speech Synthesizer 服务](https://help.aliyun.com/zh/model-studio/developer-reference/quick-start-of-tts) 即可获得 API Key。

### 3. 开始使用

主模型回复时只需把要转语音的文本用 `<tts>` 标签包裹：

> 用户：你今天心情怎么样？
>
> 模型：我感觉挺开心的~ `<tts>今天天气真好呀，要不要一起出去走走？</tts>`

插件会自动调用 SubAgent 根据上下文注入情感参数（开心、语速偏快、稍微抬音调），然后合成语音推给用户。

## 进阶用法

### 音色管理（Web UI）

Dashboard → 插件详情页 → "音色管理" 标签页，可视化创建/试听/删除音色：

- **声音复刻**：上传本地音频文件（需公网 IPv4 + 端口转发）或填入公网音频 URL
- **声音设计**：用自然语言描述声音特质（如 "低沉、磁性、青年男声"），自动生成新音色
- **预览试听**：任意文本即时合成试听，不消耗正式配额

### 多个供应商回退

配置多个供应商，按 `priority` 数字从小到大依次尝试，失败自动降级：

```
供应商 A (priority=0, 百炼 Qwen Audio 3.0)
  ↓ 失败
供应商 B (priority=1, 百炼 CosyVoice 3.5)
  ↓ 失败
降级为纯文本输出
```

### Tool 调用模式

插件自动注册 `send_voice_to_user` 函数工具，模型可主动决定发语音的时机和内容，而不需要 `<tts>` 标签。

### 双输出模式

在配置中开启 `dual_output`，TTS 段落会**同时保留文本和语音消息**——适合多模态场景（用户既能看也能听）。

## 配置项

```yaml
enable_enhance: true              # 启用 SubAgent 自动注入情感参数
enhance_llm_provider: ""          # 用于增强的 LLM 供应商（留空用当前会话模型）
context_window: 10                # 上下文窗口（最近几轮对话）
dual_output: false                # 同时输出文本和语音
tts_prompt: "当你想要发送语音时..."  # 注入主模型的 TTS 提示词
log_enhanced_params: false        # 打印 SubAgent 生成的增强参数
providers:                        # TTS 供应商列表
  - template: bailian_qwen_audio_3_0_tts
    display_name: "我的语音"
    priority: 0
    api_key: "sk-..."
    workspace_id: "ws-..."
    model: "flash"                # flash 或 plus
    voice: "longanhuan_v3.6"      # 系统音色 ID
    timeout: 60
    format: "wav"
    sample_rate: 24000
```

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 完整更新日志
- `providers/docs/bailian_qwen_audio_3_0_tts.md` — Qwen Audio 3.0 能力说明
- `providers/docs/bailian_qwen_audio_3_0_tts_design.md` — Qwen 声音设计专用文档
- `providers/docs/bailian_cosyvoice_v3_5.md` — CosyVoice v3.5 能力说明
- `providers/docs/bailian_cosyvoice_v3_5_design.md` — CosyVoice 声音设计专用文档

## 路线图

- [ ] 接入 Qwen-TTS（百炼平台第三条 TTS 线）
- [ ] 接入 MiniMax TTS / Edge TTS / GPT-SoVITS
- [ ] 音色共享 / 跨供应商音色导入
- [ ] SubAgent Prompt 模板化（不同场景用不同提示词）
- [ ] 流式合成（首字节延迟优化）

## 贡献

欢迎 PR！新增一个 TTS 供应商只需要：

1. 在 `providers/` 下新建 `<vendor>_<model>.py`，继承 `BailianSpeechSynthesizerAdapter` 或 `TTSProviderAdapter`
2. 在 `_conf_schema.json` 添加配置模板
3. 在 `pages/tts_manager/components/` 下新建前端组件（参考 `bailian_cosyvoice_v3_5.js`）
4. 在 `pages/tts_manager/app.js` 的 `componentMap` / `getDisplayName` 注册

## 许可

GNU Affero General Public License v3.0 — 详见 [LICENSE](LICENSE)
