# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.2.1] - 2026-09-04

### Added

- **新增百炼 Speech Synthesizer 通用前端组件**（`pages/tts_manager/components/bailian_speech_synthesizer.js`，1070 行）：
  - 统一支持上传（upload）、公网 URL（url）、声音设计（design）三种音色创建模式
  - 通过 `providerConfig` prop 适配不同供应商：`displayName` / `supportedLanguages` / `supportsSystemVoices` / `systemVoiceLinks` / `designHelpLink`
  - 内置 Toast 反馈机制（success / error，3 秒自动消失）
  - 内置独立预览模态框（与设计模式预览分离），支持自定义文本试听、保留或删除
  - 完整表单校验：upload 模式字段非空、URL 合法、design 模式字符数（汉字按 2 字符计，voice_prompt ≤ 500、preview_text 15~200）
  - 内置删除确认模态框，避免沙盒环境 `confirm()` 被拦截
- **新增 CosyVoice v3.5 前端组件**（`pages/tts_manager/components/bailian_cosyvoice_v3_5.js`）：作为通用组件的薄封装，声明 `displayName`、12 种支持语言、`supportsSystemVoices: false`（v3.5 不支持系统音色）、设计音色帮助链接
- **前端 app.js 接入 CosyVoice v3.5 选项卡**：组件映射表与显示名映射表新增 `bailian_cosyvoice_v3_5` 条目

### Changed

- **前端重构**：`bailian_qwen_audio_3_0_tts.js` 从 1030 行的内联实现改为 33 行的 `BailianSpeechSynthesizer` 包装层，仅声明 Qwen 特有的 `providerConfig`（16 种支持语言、系统音色列表、帮助链接）
- **Provider 工厂鲁棒性增强**（`providers/__init__.py`）：新增 `obj.__module__ == module.__name__` 检查，防止基类通过多继承方式被重复发现并注册到错误模块名下
- **适配器日志安全增强**（`providers/_bailian_speech_synthesizer.py`）：初始化时对 `entry` 字典做 `api_key` 脱敏（仅保留后 5 位，前缀 `*****`），避免 API Key 写入 debug 日志

## [0.2.0] - 2026-08-31

### Added

- **新增百炼 CosyVoice v3.5 适配器**（`bailian_cosyvoice_v3_5.py`）：
  - 支持 `cosyvoice-v3.5-flash` 和 `cosyvoice-v3.5-plus` 模型
  - 支持语言列表（12 种）：zh、en、fr、de、ja、ko、ru、pt、th、id、vi
  - 适配器仅需设置 `MODEL_NAME = "cosyvoice-v3.5"` 和 `VALID_LANGS`，即可复用基类所有能力
  - **注意**：CosyVoice v3.5 不支持系统音色，仅支持声音复刻与声音设计生成的定制音色

- **新增百炼 Speech Synthesizer 公共基类**（`_bailian_speech_synthesizer.py`，以下划线前缀防止自动发现注册）：
  - 抽取 Qwen-Audio-TTS 与 CosyVoice 的公共逻辑，消除重复代码
  - 通过 `MODEL_NAME` 类属性驱动模型名构造、音色过滤、设计音色判断，子类只需声明模型前缀即可接入
  - `get_docs_for_voice()` 自动根据 `MODEL_NAME` 分段计算 `vd` 位置，兼容 Qwen（8 段，vd 在索引 5）与 CosyVoice（6 段，vd 在索引 3）的设计音色 ID 格式差异
  - `_extract_model_from_voice_id()` 从音色 ID 中提取 `flash`/`plus` 后缀，供 `call_api()` 自动匹配模型版本
  - 统一管理工具 Schema、参数校验、API 调用、音频下载及音色管理（创建/列表/删除）逻辑
  - 补充缺失的 pitch 参数

- **配置 Schema 新增 `bailian_cosyvoice_v3_5` 模板**（`_conf_schema.json`）：
  - 新增供应商配置模板，`voice` 字段默认值为空并添加提示："CosyVoice v3.5 不支持系统音色，请使用声音复刻或声音设计生成的音色 ID"
  - `hint` 标注："不支持情感标签，支持指令控制（仅支持复刻/设计音色）"

- **新增 CosyVoice v3.5 能力文档**（`docs/bailian_cosyvoice_v3_5.md` 与 `docs/bailian_cosyvoice_v3_5_design.md`）：
  - 标准文档：移除情感标签与富语言标签相关内容，语言列表更新为 12 种，明确 v3.5 不支持系统音色
  - 设计专用文档：标注"该类音色不支持方言控制"，移除方言相关示例
  - 两个文档的"你的任务"部分均适配 CosyVoice 能力（仅通过 `instruction` 描述情感/角色，不添加标签）

### Changed

- 重命名 `bailian_speech_synthesizer.py` 为 `_bailian_speech_synthesizer.py`，避免基类被 `ProviderFactory` 自动发现并误注册为独立适配器
- `bailian_qwen_audio_3_0_tts.py` 改为继承 `BailianSpeechSynthesizerAdapter`，仅声明 `MODEL_NAME = "qwen-audio-3.0-tts"`，移除重复代码

## [0.1.9] - 2026-08-29

### Changed

- 历史对话改为按照 x 条 user 消息获取，替换原先粗糙地按照 2x 条消息获取
- 完善 Doc Strings 和类型注解
- 修改插件名为标准格式

## [0.1.8] - 2026-08-24

### Added

- 百炼 Qwen Audio 3.0 TTS 支持**声音设计**（Voice Design）功能：
  - 新增声音设计专用文档 `docs/bailian_qwen_audio_3_0_tts_design.md`，去除方言支持说明（设计音色不支持方言）
  - `create_voice()` 支持 `mode` 参数，区分 `clone`（声音复刻）与 `design`（声音设计）
  - 实现 `_create_voice_by_design()` 调用百炼 `voice-enrollment` / `create_voice` API
  - 音色识别改用精确 split 判断：设计音色 ID 按 `-` 分割后长度为 8 且第 6 段为 `vd`，避免复刻音色 prefix 含 `vd` 时被误判
- 前端音色管理页新增 **"🎨 声音设计"** 选项卡：
  - 支持自然语言声音描述（voice_prompt）和预览文本（preview_text）输入
  - 字符数校验：汉字按 2 字符计算，voice_prompt ≤ 500 字符，preview_text 15~200 字符
  - 创建成功后弹出预览模态框，支持在线试听、保留或删除
  - 预览模态框内嵌删除确认流程，避免沙盒环境 `confirm()` 被拦截
- 声音描述输入框添加帮助链接，点击复制链接到剪贴板
- 恢复音色列表的独立预览功能（与设计模式预览分离）

### Changed

- `base.py` 新增 `get_docs_for_voice()` 默认方法，供适配器根据音色 ID 动态选择文档
- `tts_service.py` 在合成时调用 `get_docs_for_voice()` 获取对应文档
- 前端按钮样式优化：新增 `btn-success` 和 `btn-secondary` 类，悬停有反馈
- 公网 IPv4 提示框适配深色模式
- 音色列表中的设计音色显示 "设计" 标签

## [0.1.7] - 2026-08-24

### Added

- 向提示词中加入人格信息

## [0.1.6] - 2026-08-22

### Added

- 提供函数工具方式调用 TTS

### Changed

- 重构 `main.py`，将 TTS 逻辑拆分到 `src/tts_service.py` 中，避免 tools.py 回调 main.py

## [0.1.5] - 2026-08-20

### Changed

- 未配置提供商时将不会注入 TTS 提示词
- 优化 bailian_qwen_audio_3_0_tts 模板布局减少重复代码
- 增强 bailian_qwen_audio_3_0_tts 模板配置项的校验
- 引入 ESLint 提供代码质量检查

## [0.1.4] - 2026-08-19

### Added

- 新增临时文件服务器 `src/file_server.py`（基于 aiohttp）：`TempFileServer` 绑定 `0.0.0.0:internal_port` 提供单文件下载服务，支持按扩展名返回对应 MIME 类型（wav/mp3/m4a 等）。
- `main.py` 新增 Web API：
  - `POST /upload`：上传音频文件（仅允许 wav/mp3/m4a），以 `upload_{时间戳}{扩展名}` 生成唯一 file_id 返回。
  - `POST /start_file_server`：按 `file_id` + `internal_port` 启动临时文件服务器。
  - `POST /stop_file_server`：停止服务器并删除对应的临时上传文件。
  - `POST /voice/preview`：音色试听——用指定 voice_id 合成语音，以 Base64 返回音频数据。
- 前端 `bailian_qwen_audio_3_0_tts.js` 新增音色创建双模式选项卡：上传音频文件（需公网 IPv4 + 端口转发）与公网音频 URL，两块表单独立校验。
- 前端新增音色预览模态框：输入自定义文本，调用 `/voice/preview` 获取 Base64 音频并直接播放。
- `providers/bailian_qwen_audio_3_0_tts.py` 支持从 `raw_params` 覆盖 voice，并从音色 ID 自动推断模型版本（flash/plus）。

### Changed

- 前端改用 Vue 的 UMD 版本，直接通过 `<script>` 标签引入避免 CDN 加载问题。
- 前端所有 Web API 调用统一走 `AstrBotPluginPage` bridge（含文件上传 `bridge.upload`），绕开 Pages 的 asset_token 鉴权与跨域限制。
- `main.py` 的音频下载目录改为插件数据目录 `plugin_data/tts_enhancer/audio`，由 `_data_dir` 注入适配器。
- 上传文件的唯一文件名不再包含原始文件名，避免 URL 编码问题。
- 修正 `start_file_server` 路由描述与实际行为的一致性。
- 优化 `list_voices`/`delete_voice`/`preview_voice` 的错误提示（"无法创建适配器" → "无法创建适配器，请检查配置"）。

## [0.1.3] - 2026-08-18

### Added

- 新增音色管理 Web API 路由（`main.py`）：
  - `GET /tts_enhancer/providers`：按 `template_key` 分组返回已配置的供应商列表，API Key 脱敏。
  - `POST /tts_enhancer/voice/create`：创建音色，按 `entry_id` 路由到对应适配器的 `create_voice()`。
  - `POST /tts_enhancer/voice/list`：查询音色列表，路由至适配器的 `list_voice()`。
  - `POST /tts_enhancer/voice/delete`：删除音色，路由至适配器的 `delete_voice()`。
- `providers/base.py` 新增音色管理抽象方法：`create_voice()`、`list_voice()`、`delete_voice()`，默认抛出 `NotImplementedError`，由各供应商适配器自行实现。
- `providers/bailian_qwen_audio_3_0_tts.py` 实现百炼音色管理：
  - `create_voice()`：调用百炼 `voice-enrollment` / `create_voice` API，支持 `audio_url`、`prefix`、`language_hints`、`enable_volume_normalization`、`enable_preprocess` 等参数。
  - `list_voice()`：调用 `list_voice` API，仅返回 `qwen-audio-3.0-tts` 开头的音色列表。
  - `delete_voice()`：调用 `delete_voice` API 删除指定音色。
- 新增音色管理 Pages 前端（`pages/tts_manager/`）：
  - `index.html`：Vue 3 应用骨架，动态渲染供应商选项卡。
  - `app.js`：应用入口，按供应商模板分组配置，管理当前编辑的供应商。
  - `components/bailian_qwen_audio_3_0_tts.js`：百炼专属配置组件，包含 `audio_url`、`prefix`、`enable_preprocess` 等字段，并支持音色列表查询。

## [0.1.2] - 2026-08-16

### Changed

- `main.py` 精简为入口层（`__init__` / `_register_routes`），业务逻辑拆到 `src/config.py`、`src/tts_parser.py`、`src/sub_agent.py`。
- 为 `on_llm_req`、`on_decorate`、`_get_context_messages`、`_synthesize`、`_process_tts_text` 补充了符合 PEP 257 的 docstring，明确 Args / Returns。

## [0.1.1] - 2026-08-16

### Added

- 引入百炼 Qwen Audio 3.0 TTS 适配器（`providers/bailian_qwen_audio_3_0_tts.py`）：
  - 继承 `BaseProviderAdapter`，基于 OpenAI 兼容协议调用 `qwen-audio-3.0-tts-*` 模型。
  - 在 `call_api()` 中调用 `validate_params` / `sanitize_params` 过滤非法参数（speed/pitch/volume 范围、voice 前缀）。
  - `get_subagent_system_prompt()` 输出百炼专属 SubAgent 提示词。
- 新增 `providers/base.py`：定义 `BaseProviderAdapter` 抽象基类，提供 `call_api`、`validate_params`、`sanitize_params`、`parse_subagent_response` 等统一接口。
- 新增 `providers/__init__.py`：`ProviderFactory` 按 `__template_key` 自动实例化适配器。
- 新增 `docs/qwen_audio_3_0_tts.md`：百炼模型官方参数文档（speed/pitch/volume 范围、voice 枚举、voice_clone 配置）。

### Changed

- 移除旧引擎（`providers/tts_engine.py`），统一改为 Adapter 架构。
- `_synthesize()` 调用链：`validate_params` 校验 → 失败时 `sanitize_params` 兜底清理 → SubAgent 上下文反馈重试。

## [0.1.0] - 2026-08-15

### Added

- 初始三层架构：主模型（LLM + TTS 提示词） → SubAgent（tts_enhance 工具 + 文档） → Provider Adapter（API 调用）。
- `main.py` 实现事件钩子：`on_llm_req`（追加 TTS 提示词）、`on_decorate`（解析 `<tts>` 标签触发合成）。
- `_synthesize()` 多供应商优先级遍历、降级逻辑（无文档 → 纯文本）。
- `_get_context_messages()` 上下文窗口提取（最近 N 条历史）。
- `src/config.py`：`TTSEnhancerConfig` 配置类（`tts_prompt`、`enable_enhance`、`context_window`、`dual_output` 等）。
- `src/tts_parser.py`：`split_by_tts_tags()` 解析 `<tts>...</tts>` 标签。
- `src/sub_agent.py`：`TTSSubAgent` 调用 AstrBot 内置 Agent 框架。
- 支持 `Record.fromFileSystem` 音频消息输出。