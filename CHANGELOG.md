# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.1.5] - 2026-08-20

### Changed

- 未配置提供商时将不会注入 TTS 提示词
- 优化 bailian_qwen_audio_3_0_tts 模板布局减少重复代码

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