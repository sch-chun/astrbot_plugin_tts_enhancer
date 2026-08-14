# astrbot_tts_enhancer

多供应商智能 TTS（语音合成）插件，支持 SubAgent 模式自动注入情感标签与指令控制。

> 当前版本：**v0.1.0** · 最低 AstrBot 版本：**>= 3.4.0**

## 架构

```
[主模型] 输出 <tts>文本</tts>
    ↓
[插件] 提取文本 + 对话上下文
    ↓
[SubAgent] 根据当前 Provider 能力说明书调用 LLM 生成增强参数
    ↓
[Provider Adapter] 解析参数 → 调用 TTS API → 返回音频
```

## 支持的供应商

- **ali_qwen_audio**: Qwen-Audio-TTS，24 种情感标签 + 7 种拟声标签
- **ali_cosyvoice**: CosyVoice，自然语言指令控制
- **minimax**: MiniMax，结构化 JSON 情感控制

## 配置

在 AstrBot Dashboard → 插件配置中设置 API Key、Workspace ID 和选择供应商。

## 许可

MIT