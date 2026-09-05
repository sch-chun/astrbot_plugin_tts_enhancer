# MiniMax Speech 2.8 TTS 能力说明

此文档用于指导 SubAgent 生成适合 **MiniMax Speech 2.8** 模型的语音合成参数。

---

## 支持的参数

| 参数名 | 类型 | 范围/枚举 | 说明 |
|--------|------|-----------|------|
| `text` | string | 必填 | 合成文本，可嵌入 `<#x#>` 控制停顿（x 为秒，0.01~99.99）和语气词标签（见下文） |
| `emotion` | string | `happy`, `sad`, `angry`, `fearful`, `disgusted`, `surprised`, `calm`, `fluent` | 情感标签（默认自动推断，一般无需指定） |
| `speed` | number | 0.5~2.0 | 语速倍率，默认 1.0 |
| `vol` | number | 0.0~10.0 | 音量，默认 1.0 |
| `pitch` | integer | -12~12 | 语调偏移，默认 0 |
| `language_boost` | string | 见下方列表或 `auto` | 增强指定语种识别（默认自动推断，一般无需指定） |
| `latex_read` | boolean | - | 朗读 LaTeX。开启后，`language_boost` 会被自动设为 `"Chinese"` (仅支持中文)，且公式必须用 `$$` 包裹 |

---

## 文本内联控制

- **语气词标签**（在文本中直接插入）：

| 标签 | 说明 |
|-----|-----|
| `(laughs)` | 笑声 |
| `(chuckle)` | 轻笑 |
| `(coughs)` | 咳嗽 |
| `(clear-throat)` | 清嗓子 |
| `(groans)` | 呻吟 |
| `(breath)` | 正常换气 |
| `(pant)` | 喘气 |
| `(inhale)` | 吸气 |
| `(exhale)` | 呼气 |
| `(gasps)` | 倒吸气 |
| `(sniffs)` | 吸鼻子 |
| `(sighs)` | 叹气 |
| `(snorts)` | 喷鼻息 |
| `(burps)` | 打嗝 |
| `(lip-smacking)` | 咂嘴 |
| `(humming)` | 哼唱 |
| `(hissing)` | 嘶嘶声 |
| `(emm)` | 嗯 |
| `(sneezes)` | 喷嚏 |

- **停顿控制**：在文本中增加 `<#x#>` 标记，x 为停顿时长（单位：秒），范围 [0.01, 99.99]，最多保留两位小数。文本间隔时间需设置在两个可以语音发音的文本之间，不可连续使用多个停顿标记。如 `<#1.5#>` 表示停顿 1.5 秒

---

## `language_boost` 可选值

`Chinese`, `Chinese,Yue` (粤语), `English`, `Arabic`, `Russian`, `Spanish`, `French`, `Portuguese`, `German`, `Turkish`, `Dutch`, `Ukrainian`, `Vietnamese`, `Indonesian`, `Japanese`, `Italian`, `Korean`, `Thai`, `Polish`, `Romanian`, `Greek`, `Czech`, `Finnish`, `Hindi`, `Bulgarian`, `Danish`, `Hebrew`, `Malay`, `Persian`, `Slovak`, `Swedish`, `Croatian`, `Filipino`, `Hungarian`, `Norwegian`, `Slovenian`, `Catalan`, `Nynorsk`, `Tamil`, `Afrikaans`, `auto`

---

## `latex_read` 参数

- 仅支持中文，开启该参数后，`language_boost` 参数会被强制设置为 `Chinese`
- 请求中的公式需要在公式的首尾加上 `$$`
- 请求中公式若有 `\`，需转义成 `\\`

示例：一元二次方程根的基本公式应表示为

`$$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$`

---

## 使用示例

### 示例 1：语气词标签

语气词标签可以直接在文本中插入，让语音更加自然生动。

```
文本：今天天气真好(laughs)，我们一起去公园散步吧(breath)，顺便拍些照片。
效果：在“真好”之后插入笑声，在“散步吧”之后插入换气声
```

---

### 示例 2：停顿控制

使用 `<#x#>` 标记控制文本之间的停顿时长，增强语义表达。

```
文本：各位观众朋友，欢迎收看今天的新闻节目。<#0.5#>首先为您播报头条。
效果：在 “朋友” 后模型自然停顿，在 “节目” 后额外停顿 0.5 秒
```

---

### 示例 3：语速与音量调节

通过 `speed` 和 `vol` 参数控制语音的节奏和响度。

```
text: 紧急通知！台风即将登陆，请各位居民做好防护准备。
speed: 1.3
vol: 1.5
效果：语速偏快、音量较高，营造紧迫感
```

---

### 示例 4：LaTeX 朗读

开启 `latex_read` 后，用 `$$` 包裹公式，模型会朗读公式内容。

```
text: 一元二次方程的求根公式是 $$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$ 
latex_read: true
效果：自动朗读公式，language_boost 被强制设为 "Chinese"
```

---

## 你的任务

根据对话上下文和待合成的原始文本，选择合适的参数：

1. **插入语气词标签**：在文本中适当位置插入 `(laughs)`、`(sighs)`、`(breath)` 等标签，增强自然度
2. **控制节奏**：如需较长停顿（如段落切换、强调），使用 `<#x#>` 插入停顿。
3. **调节参数**：根据场景调整 `speed`（快速/慢速）、`vol`（轻声/大声）、`pitch`（高亢/低沉）以匹配氛围。
4. **特殊需求**：若文本包含数学公式，开启 `latex_read`。

**输出方式**：直接调用 `tts_enhance` 工具，将参数填入对应字段。若某个参数不必要，可以省略（工具会使用默认值）。
