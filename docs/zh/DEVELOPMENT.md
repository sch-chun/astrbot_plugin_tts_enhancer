# TTS Enhancer 开发指南

> 面向插件贡献者与维护者的实操手册。
> 配套文档：[架构文档](ARCHITECTURE.md) · [英文 README](../en/README.md) · [CHANGELOG](../../CHANGELOG.md)

本文以"如何新增一个 TTS 供应商"为主线，串起适配器、能力说明书、配置、前端、测试等全部环节。

---

## 1. 环境准备

### 1.1 运行 / 调试环境

- Python ≥ 3.10（与 AstrBot 一致）。
- 在 AstrBot 源码树内，把本插件目录软链或复制到 `data/plugins/astrbot_plugin_tts_enhancer/`，启动 AstrBot 后于 WebUI 启用插件。
- 后端依赖（异步 HTTP 等）随 AstrBot 主环境提供；适配器如需额外库，写入插件根目录的 `requirements.txt`（AstrBot 会安装）。

### 1.2 测试环境（pytest）

- 测试套件位于 `tests/`，`pytest.ini` 已设 `asyncio_mode = auto`。
- `requirements-tests.txt` 声明 `pytest` 与 `pytest-asyncio`，隔离主环境依赖。
- `tests/conftest.py` 会**向上探测 AstrBot 源码根目录**（不再硬编码层级），并用 `pytest.importorskip("astrbot.core.provider")`——脱离 AstrBot 源码时优雅跳过而非崩溃。

```bash
# 在插件根目录
pip install -r requirements-tests.txt
pytest                # 在 AstrBot 源码树内运行
```

### 1.3 前端（无需构建）

- 前端是原生 ES Module + 本地 Vue UMD，**没有打包步骤**，改完 JS 直接生效。
- 仅 `eslint.config.mjs` 提供可选 lint（开发期），依赖见 `pages/tts_manager/package.json` 的 `devDependencies`。
- 可选：`cd pages/tts_manager && npm install && npx eslint .`。

---

## 2. 目录结构

```
astrbot_plugin_tts_enhancer/
├── main.py                      # 插件入口：钩子 + Web 路由 + 安全校验
├── metadata.yaml                # 插件元信息（name/version/author/repo...）
├── _conf_schema.json            # 配置 Schema（含各供应商模板）
├── README.md / CHANGELOG.md
├── requirements-tests.txt       # 测试依赖（pytest / pytest-asyncio）
├── src/
│   ├── config.py                # TTSEnhancerConfig：配置加载/排序/去重
│   ├── tts_parser.py            # <tts> 标签解析
│   ├── tts_service.py           # 合成编排核心
│   ├── sub_agent.py             # SubAgent（Function Calling 参数生成）
│   └── tools.py                 # send_voice_to_user 主动语音工具
├── providers/
│   ├── __init__.py              # ProviderFactory（自动发现）
│   ├── base.py                  # TTSProviderAdapter 抽象基类
│   ├── _bailian_speech_synthesizer.py  # 百炼公共基类（下划线前缀，不被发现）
│   ├── <vendor>_<model>.py      # 具体适配器（即 template_key）
│   ├── utils/{http,audio}.py    # 公共 HTTP / 音频工具
│   └── docs/<docs_key>.md       # 能力说明书（含 *_design.md）
├── pages/tts_manager/           # 前端（Vue 3，无需构建）
│   ├── index.html / app.js / style.css
│   ├── components/common/       # 跨供应商共享组件
│   ├── components/*.js          # 各供应商组件
│   ├── composables/             # useAudioManager / useTextValidator ...
│   └── static/vue.global.prod.js
└── tests/                       # pytest 套件
```

---

## 3. 新增一个 TTS 供应商（清单）

| 步骤 | 产出 | 必需？ |
|------|------|--------|
| 1. 写适配器 | `providers/<template_key>.py` | ✅ |
| 2. 写能力说明书 | `providers/docs/<docs_key>.md`（可能含 `_design.md`） | ✅（否则降级纯文本） |
| 3. 配置 Schema | `_conf_schema.json` 的 `providers.templates` 新增模板 | ✅ |
| 4. 前端接入 | `pages/tts_manager/components/*.js` + `app.js` 注册 | 仅当需 UI |
| 5. 测试 | `tests/` 新增用例 | 强烈建议 |

> 所有新增供应商会被 `ProviderFactory` **自动发现并加载**，无需修改核心代码。文件名（去掉 `.py`）即 `template_key`，必须与 `_conf_schema.json` 的 `templates` key 一致。

---

## 4. 适配器开发详解

### 4.1 最小可运行适配器

```python
"""Example TTS 适配器"""

from .base import TTSProviderAdapter


class ExampleTtsAdapter(TTSProviderAdapter):
    """示例供应商适配器"""

    def get_subagent_system_prompt(self) -> str:
        docs = self.docs_content
        return (
            f"你是语音合成参数优化助手。参数说明：\n\n{docs}\n\n"
            "请直接调用 tts_enhance 工具，不要额外解释。"
        )

    def get_tool_schema(self):
        # 通过基类 build_enhance_tool 构造 tts_enhance 并自动挂上校验 handler
        # （见 base.py：固定工具名、统一 FunctionTool 构造与 _handle_enhance_tool 接线）
        return self.build_enhance_tool(
            description="将文本合成为语音所需的参数",
            parameters={...},  # 该适配器的参数 schema
        )

    async def call_api(self, text, raw_params, config, voice_id=None) -> str:
        # 1. 合并配置与 raw_params（工具参数优先）
        # 2. 构造请求、调用 API、下载音频
        # 3. 落盘并返回路径；失败返回 ""（不要抛未捕获异常到主流程）
        ...
```

### 4.2 必实现抽象方法

- `get_subagent_system_prompt() -> str`：拼接能力说明书，指导 SubAgent 产出参数。
- `get_tool_schema() -> FunctionTool | None`：通过基类 `build_enhance_tool` 返回 `tts_enhance` 工具（已挂上校验 handler）。返回 `None` 表示不支持 Function Calling（将走纯文本降级）。
- `call_api(text, raw_params, config, voice_id=None) -> str`：合成核心。返回音频文件路径；**失败返回空串**而非抛异常（主流程据此切换供应商）。`voice_id` 用于预览时显式覆盖音色。

### 4.3 可选能力（音色 / 文件管理）

默认 `raise NotImplementedError`，由 `main.py` 路由捕获后返回 `501`。实现后即被前端/路由调用：

- 音色：`create_voice(params)`、`list_voice(**kwargs)`、`delete_voice(**kwargs)`。
- 文件：`upload_file(file_path, **kwargs)`、`list_files(**kwargs)`、`get_file_content(file_id)`、`delete_file(file_id, **kwargs)`。

> 文件管理路由（`/file/*`）会把除 `entry_id`/`file_id` 外的参数以 `**kwargs` 透传给适配器，保持扩展弹性。

### 4.4 参数校验与清洗

- **范围/枚举校验**：覆盖 `validate_params(params) -> (bool, str)`。返回 `(False, msg)` 时 SubAgent 以 `role:"tool"` 结构化工具结果（含错误文本）回灌给 LLM 重试，末次失败转 `sanitize_params` 清洗兜底。
- **清洗**：覆盖 `sanitize_params(params) -> dict`，丢弃非法值、保留合法值（如把 LLM 以字符串返回的数字用 `_as_float`/`_as_int` 归一到数值，排除 `bool`）。
- **通用校验**：直接用基类的 `validate_voice_id()`、`validate_text_length()`（汉字=2 字符，与前端 `useTextValidator` 对齐），避免重复实现。
- **类型安全**：参数解析一律走 `_as_float` / `_as_int`，避免"拒字符串数字"且"漏掉 bool"。

### 4.5 音频落盘约定

- 合成产物统一用 `providers/utils/audio.py` 的 `save_audio_bytes(data_dir, content, fmt)` 落盘——它会在 `config["_data_dir"]` 下以时间戳命名保存，并返回路径。
- `_data_dir` 由 `TTSService`/`main.py` 注入到 entry 字典（值为 `plugin_data/<name>/audio`），适配器**不要硬编码路径**。

### 4.6 复用 utils

- `providers/utils/http.py`：`bearer_headers(api_key, with_json=True)`、`extract_error_message(payload, fallback_text)`（兼容 `message`/`error`/`detail`）。
- `providers/utils/audio.py`：`save_audio_bytes(...)`、`get_audio_duration`、`validate_audio_duration`、`trim_audio_to_max`、`AudioConstraints`（各平台时长约束常量）。

### 4.7 `voice_id` 覆盖约定

`call_api` 的 `voice_id` 参数用于"预览时显式覆盖音色"。标准写法：

```python
voice = voice_id or config.get("voice") or config.get("voice_id")
if not voice:
    raise ValueError("未提供音色 ID，无法合成语音")
```

各供应商配置键名保持与上游 API 一致（百炼 `voice`、MiniMax `voice_id`），不强制统一。

---

## 5. 能力说明书编写规范

文件：`providers/docs/<docs_key>.md`，会被 SubAgent 直接读取并注入。建议结构：

1. **概述**：模型来源与定位。
2. **核心参数表**：必填/可选参数（类型、范围、默认值、说明）。
3. **枚举**：语言、情感标签、方言等。
4. **使用示例**：含完整 `tts_enhance` 参数示例。
5. **`## 你的任务`**（关键）：明确告知 SubAgent 如何根据上下文选择参数、何时调用 `tts_enhance`。
   - 例："根据上下文语气在 text 中添加控制类标签；用 instruction/rate/volume 控制细节；直接调用 tts_enhance。"

若某类音色（如设计音色）能力受限（不支持方言），用 `<docs_key>_design.md` 单独描述，并在适配器中通过 `get_docs_for_voice(voice)` 按音色 ID 自动切换；相同模型可设子类 `DOCS_KEY` 复用文档。

---

## 6. 配置 Schema 扩展

在 `_conf_schema.json` 的 `providers.templates` 下新增以 `template_key` 为键的模板：

```json
"my_provider": {
  "name": "我的供应商",
  "hint": "一句话能力说明",
  "display_item": "display_name",
  "items": {
    "display_name": { "description": "显示名称", "type": "string", "default": "我的供应商" },
    "priority":     { "description": "优先级（越小越优先）", "type": "int", "default": 0 },
    "persona_id":   { "description": "绑定人格", "type": "string", "_special": "select_persona", "default": "" },
    "api_key":      { "description": "API Key", "type": "string", "secret": true },
    "model":        { "description": "模型", "type": "string", "options": ["a", "b"], "default": "a" }
  }
}
```

要点：

- `_special: select_provider` / `select_persona`：渲染为下拉选择器。
- `secret: true`：密码框遮罩。
- `options`：固定枚举下拉；`condition`：按其他字段值条件显示（如 MiMo 按 `model` 切换音色/设计/复刻字段）。
- 框架自动注入 `__template_key` 与 `display_item` 指定的显示名。

---

## 7. 前端接入

### 7.1 何时需要前端

- **已有官方控制台**：仅在 `app.js` 的 `getDisplayName` 增加显示名，`providerConfig` 配外链即可，**无需写组件**。
- **只有 API**：在 `components/` 下写组件，复用 `components/common/` 公共组件，并在 `app.js` 的 `componentMap` 注册。

### 7.2 组件注册（`app.js`）

```js
import MyProvider from './components/my_provider.js';
// componentMap 增加：'my_provider': MyProvider
// getDisplayName 增加：'my_provider': '我的供应商'
```

### 7.3 providerConfig 与通用组件

百炼系供应商直接复用 `components/common/bailian_speech_synthesizer.js`，薄封装只声明差异：

```js
export default {
  components: { BailianSpeechSynthesizer },
  // providerConfig: { displayName, supportedLanguages, supportsSystemVoices, systemVoiceLinks, designHelpLink }
};
```

通用组件已封装复刻/设计两模式（复刻音频经浏览器编码为 Data URL 直接提交）、试听、列表、删除，以及 `voice_preview_modal` / `delete_confirm_modal`（沙箱下替代 `confirm()`）。

### 7.4 bridge API

所有后端调用走 `window.AstrBotPluginPage`（`bridge`）：

- `await bridge.ready()`：确保 bridge 就绪。
- `await bridge.apiGet('providers')`：取分组供应商列表。
- `bridge.upload(...)`：文件上传（绕开 `asset_token` 鉴权与跨域）。
- 其余路由以 `bridge.apiPost('<route>', payload)` 形式调用（如 `voice/create`、`file/upload`、`kv/set` 等）。

### 7.5 composables

- `useAudioManager`：全局音频播放单例（共享音量、跨组件 toggle）。
- `useTextValidator`：`countChars`（汉字=2）、`validateText({label,min,max,required})` → `{valid,error,count}`。
- `useClipboard`、`useToast`：剪贴板与通知。

---

## 8. 测试规范

### 8.1 运行测试

```bash
pip install -r requirements-tests.txt
pytest                 # 在 AstrBot 源码树内
pytest tests/test_xxx.py -k "case"   # 单文件/单用例
```

### 8.2 conftest 约定

- 自动探测 AstrBot 源码根目录，`importorskip` 缺失依赖时跳过。
- 提供测试夹具（fixture）便于构造 `entry`、mock Provider 等（详见 `tests/conftest.py`）。

### 8.3 xfail 约定（重要）

- 已知缺陷/设计取舍/上游担保/不可达路径，**用 `@pytest.mark.xfail` 固化**为回归信号，而非写"写死现状"的普通用例挡住后续修复。
- 修复对应缺陷后，将 xfail 转为普通回归用例。
- 编写新用例后，**回退改动确认该用例会失败**，避免假阳性测试。

---

## 9. 代码风格与注释

- 注释与日志默认**中文**（第三方个人插件；仅给 AstrBot 主仓库提 PR 才用英文）。
- Docstring 遵循 **Google 风格**（`Args`/`Returns`/`Raises`），详见现有模块。
- 日志统一 `from astrbot.api import logger`，禁止使用内置 `logging`。
- 遵循 KISS：避免不必要的抽象与 helper；能内联的逻辑不抽函数。
- 路径处理用 `pathlib.Path`，不要字符串拼接。

---

## 10. 发布与版本

1. **代码改动** → 2. **版本号**（`metadata.yaml` 的 `version`，保持 `vX.Y.Z`）→ 3. **README/CHANGELOG** 更新 → 4. **分支 + 提交** → 5. **推送**（个人 GitHub 账号，PAT）。
2. `CHANGELOG.md` 遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) + 语义化版本。
3. 多轮任务以"wrap-up 验证 + CHANGELOG 条目"收尾。

---

## 11. 常见陷阱

- **不要在插件自身目录持久化数据**：写到 `plugin_data/` 下，否则更新/重装会丢。
- **`call_api` 失败返回空串而非抛异常**：主流程依赖空串判定切换供应商。
- **参数解析用 `_as_float/_as_int`**：LLM 常以字符串返回数字，且需排除 `bool`。
- **`template_key`、`_conf_schema.json` 模板键、适配器文件名三者必须一致**。
- **能力说明书缺失 → 该供应商自动降级为纯文本**（不报错，但失去增强能力）。
</content>
</invoke>
