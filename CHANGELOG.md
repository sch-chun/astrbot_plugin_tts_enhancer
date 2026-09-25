# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.3.1] - 2026-09-25

### Added

- CosyVoice V3.5 增加 LaTex 支持

## [0.3.0] - 2026-09-24

### Added

- 新增小米 MiMo V2.5 TTS 供应商（`mimo_v2_5_tts`），通过 OpenAI 兼容的 `chat/completions` 端点调用
  - 新增后端适配器 `MimoV2_5TTSAdapter`，支持三种模型：预置音色（`mimo-v2.5-tts`）、文本设计音色（`mimo-v2.5-tts-voicedesign`）、音频复刻（`mimo-v2.5-tts-voiceclone`）
  - MiMo 音频复刻样本使用 `file` 类型配置项（复用 AstrBot 内置文件上传组件），上传后以相对路径 `files/...` 持久化
  - 能力说明书拆分为通用（`mimo_v2_5_tts.md`）与预置音色专用（`mimo_v2_5_tts_preset.md`）两份，预置音色文档额外包含唱歌标签（`(唱歌)`/`sing`/`singing`）说明，并仅对预置音色模型加载
  - 音频复刻样本在适配器初始化时预编码并落盘缓存至 `<plugin_data>/cache/mimo_voiceclone/`，缓存键含文件 mtime/size 实现变更自动失效，Base64 编码后超 10MB 的样本提前抛错
  - 端点硬编码为官方地址，输出格式支持 `wav`/`mp3`/`pcm`（`pcm` 即 `pcm16`）
  - `_conf_schema.json` 新增 `mimo_v2_5_tts` 模板，通过 `model` 下拉 + `condition` 按所选模型分派音色 / 设计描述 / 复刻样本字段

### Changed

- 所有供应商模板的 `api_key` 配置项新增 `"secret": true`，管理面板以密码框遮罩显示
- 主流程将 `_data_dir` 的注入提前到供应商适配器实例化之前（`src/tts_service.py`、`main.py`），使适配器在 `__init__` 中即可读取数据目录完成样本预编码，路径来源与其他供应商保持一致（均从配置注入，无硬编码）

## [0.2.9] - 2026-09-22

### Added
- 新增百炼 MiniMax Speech 2.8 供应商（`bailian_minimax_speech_2_8`），通过阿里云百炼平台调用 MiniMax Speech 2.8 模型
  - 新增后端适配器 `BailianMinimaxSpeech2_8Adapter`，支持 HD/Turbo 两种模型，实现语音合成、声音复刻、音色列表查询与删除
  - 声音复刻支持本地音频文件（自动转 Base64 Data URL）与公网 URL 两种方式
  - 支持可选示例音频（`clone_prompt`）、语言增强、降噪、音量归一化、AIGC 水印等复刻参数
  - 新增前端配置组件 `bailian_minimax_speech_2_8.js`，提供「上传音频文件 / 使用音频 URL / 音色列表」三个标签页
  - `_conf_schema.json` 新增 `bailian_minimax_speech_2_8` 模板，`app.js` 注册组件映射与显示名称
- 复刻成功后展示试听窗口，支持播放 `demo_audio` 试听音频
- 未激活音色管理：复刻音色通过 KV（`bailian_minimax_unactivated_list`）本地存储未激活列表，音色列表分区展示未激活/复刻/系统音色，支持「预览激活」与「删除」操作

### Changed
- **文档共享机制**：`TTSProviderAdapter` 新增 `DOCS_KEY` 类属性，供应商可显式指定复用的能力文档文件名，避免相同模型说明文档的重复拷贝
  - 百炼 MiniMax 通过 `DOCS_KEY = "minimax_speech_2_8"` 复用官方 MiniMax 2.8 文档，删除冗余副本 `bailian_minimax_speech_2_8.md`
- **音频解码播放逻辑抽取**：`useAudioManager` 新增 `base64ToBlobUrl(data, mime)` 与 `hexToBlobUrl(data, mime)` 两个纯函数，统一消除四处重复的「字节解码 → Blob → objectURL」链路
  - `voice_preview_modal.js`、`bailian_speech_synthesizer.js`、`minimax_speech_2_8.js` 均改用上述工具，删除 `minimax_speech_2_8.js` 内联的 `hexToUint8Array`
- 百炼 MiniMax 后端 voice_id 支持自动生成（未提供时生成 `Clone_时间戳` 格式）、完整格式校验（长度 8-256、首字母、字符集、末位字符）
- 百炼 MiniMax 后端补充 `latex_read` 校验、`voice_generation` 类型解析、`base_resp` 空值兜底
- 前端 `LANGUAGE_BOOST` 校验与 voice_id、试听文本校验对齐官方 MiniMax 逻辑
- 后端日志对 Data URL 做截断，避免 Base64 音频数据撑爆 Debug 日志

## [0.2.8] - 2026-09-21

### Added
- 新增百炼 Qwen Audio 3.1 TTS 支持（`bailian_qwen_audio_3_1_tts`）
  - 新增后端适配器 `BailianQwenAudio3_1TTSAdapter`，复用现有 `BailianSpeechSynthesizerAdapter`
  - 新增声音复刻/声音设计能力文档 `bailian_qwen_audio_3_1_tts.md` 与 `bailian_qwen_audio_3_1_tts_design.md`
  - 新增前端配置组件 `bailian_qwen_audio_3_1_tts.js`
  - `_conf_schema.json` 新增 `bailian_qwen_audio_3_1_tts` 模板
  - `app.js` 注册新供应商组件映射与显示名称
- 公共前端组件 `bailian_speech_synthesizer.js` 支持 `availableModels` 配置，模型版本下拉动态渲染

### Changed
- Qwen Audio 3.1 仅提供 `flash` 模型版本，前端下拉不再展示 `plus`，避免误选导致 API 报错
- `currentEntry` 监听逻辑增加模型版本回退：当配置中的 model 不在当前供应商支持列表时，自动回退到第一个可用版本

## [0.2.7] - 2026-09-20

### Changed

- 前端重复复制逻辑抽提为 `pages/tts_manager/composables/useClipboard.js`，通知框抽提为 `pages/tts_manager/composables/useToast.js`

- **统一音频播放管理**：所有供应商组件（百炼、MiniMax）接入 `useAudioManager` 单例，实现跨组件共享播放状态与音量控制
  - 页面顶部新增 sticky 全局音量条，移除各组件内的独立音量条
  - 各播放按钮支持 toggle：正在播放时显示为「⏹ 停止」，点击可停止
  - 播放新音频时自动停止上一个音频，避免多音频同时播放
  - 列表预览同一音色正在播放时直接停止，不重复请求后端

- **`call_api` 新增 `voice_id` 显式参数**（`providers/base.py`、百炼、MiniMax 适配器）：
  - 抽象方法签名新增 `voice_id: Optional[str] = None`，用于在合成时显式覆盖配置中的音色 ID（典型场景：音色预览）
  - 百炼适配器：`voice = voice_id or config.get("voice")`，移除原先 `raw_params.get("voice")` 兼容分支
  - MiniMax 适配器：`voice_id = voice_id or config.get("voice_id")`，同上
  - 各供应商配置键名保持与上游 API 命名一致（百炼 `voice`、MiniMax `voice_id`），不强制统一

- **音色预览路由重构**（`main.py`）：
  - `/voice/preview` 改为通过 `call_api(..., voice_id=voice_id)` 显式传参
  - `raw_params` 语义收敛为「SubAgent 工具产出的增强参数」，调用方控制信号（如预览覆盖音色）不再注入其中

- **百炼配置冲突检查前移到 `__init__`**：
  - 原先在 `call_api` 中每次合成时检测 `config.model` 与 `voice` 解析出的 model 是否冲突，
    现改为初始化时检查一次并输出警告
  - 移除 `raw_params["_suppress_model_warning"]` 私有控制键，`raw_params` 不再混入调用方控制信号
  - `call_api` 签名保持与 base 一致，不引入百炼独有的参数

- **前端公共组件目录重组**：`pages/tts_manager/components/` 下新增 `common/` 子目录，集中收纳跨供应商共享的公共组件
  - `bailian_speech_synthesizer.js` 从 `components/` 移入 `components/common/`
  - 各供应商组件的导入路径同步调整为 `./common/xxx.js`（涉及 `bailian_qwen_audio_3_0_tts.js`、`bailian_cosyvoice_v3_5.js`、`minimax_speech_2_8.js`）
  - 百炼通用组件内部对 composables 的引用调整为 `../../composables/xxx.js`

- **抽取音色预览模态框为公共组件** (`pages/tts_manager/components/common/voice_preview_modal.js`)：
  - 封装「输入预览文本 → 调用 `voice/preview` → 播放 / 停止」的完整交互流程，内部使用 `useToast` / `useAudioManager`，与其它组件共享全局音频单例
  - props 支持 `visible`（v-model）/ `bridge` / `entryId` / `voiceId` / `initialText` / `idPrefix` / `defaultFormat` / `title`
  - `idPrefix` 用于隔离不同调用方的播放标识（避免「列表预览」与「设计预览」等按钮状态互相干扰）
  - 同一音色正在播放时点击「试听」→ 直接切换为停止，不重复请求后端（toggle 语义）
  - 通过 `previewed` 事件把预览结果通知父组件，便于激活未激活音色后刷新列表
  - 内置 `defaultFormat` 兜底：后端未返回 `format` 时按调用方指定格式构造 Blob
  - `bailian_speech_synthesizer.js` 与 `minimax_speech_2_8.js` 均改用该组件
    - 百炼（列表预览）：`id-prefix="list_preview"`、`default-format="mpeg"`
    - MiniMax：`id-prefix="preview"`，并监听 `@previewed="onVoicePreviewed"` 实现「未激活音色被激活后自动从本地列表移除」

- **抽取删除确认模态框为公共组件** (`pages/tts_manager/components/common/delete_confirm_modal.js`)：
  - 受控组件，通过 `v-model:visible` 控制显隐；props 支持 `title` / `message` / `confirmText` / `cancelText` / `maxWidth`
  - 点击遮罩或「取消」按钮 → `emit('cancel')` 并自动关闭；点击「确认」按钮 → `emit('confirm')`，**不自动关闭**（便于父组件在异步删除失败时保留弹窗让用户重试）
  - 提供默认插槽以承载自定义消息内容（如内嵌加粗的 `voice_id`）
  - `bailian_speech_synthesizer.js` 与 `minimax_speech_2_8.js` 均改用该组件，移除各自内联的删除确认模态框实现
    - 百炼：使用默认插槽渲染「确定要删除音色 **{voice_id}** 吗？」
    - MiniMax：通过 `message` prop 传入动态消息，删除逻辑保留在 `deleteModal.onConfirm` 回调中
  - 调用方业务逻辑保持不变（`deleteModalVisible` / `deleteTargetId` / `deleteModal` 等状态与 `deleteVoice` / `confirmDelete` / `cancelDelete` 方法签名保持原样）
  - `style.css` 新增 `.delete-confirm-body` 与 `.delete-confirm-actions` 类，保持原有视觉样式

- **抽取文本字数校验为公共 composable** (`pages/tts_manager/composables/useTextValidator.js`)：
  - 新增 `countChars(text)`（汉字按 2 字符、其余按 1 字符）与 `validateText(text, options)` 两个导出
  - `validateText` 支持 `label` / `min` / `max` / `required` 参数，返回 `{ valid, error, count }`，便于同时驱动「红框 / 提示文案 / 字符计数 / 提交按钮禁用」四项 UI 状态
  - **统一报错文案**：
    - 必填未填 → `{label}不能为空`
    - 低于下限 → `{label}不能少于 {min} 字符（当前 {count} 字符）`
    - 超出上限 → `{label}不能超过 {max} 字符（当前 {count} 字符）`
  - 仅保留 Voice ID / 音色前缀等厂商规则差异较大的校验在各供应商组件内本地实现，其余文本长度校验全部接入 `useTextValidator`
  - `bailian_speech_synthesizer.js`：`voice_prompt`（≤ 500）、`preview_text`（15 ~ 200）改为基于 `validateText` 的 `voicePromptValidation` / `previewTextValidation` computed，并向下暴露 `voicePromptError` / `previewTextError` 供模板渲染
  - `minimax_speech_2_8.js`：`cloneParams.text`（≤ 1000）、`cloneParams.text_validation`（≤ 200）、`designForm.preview_text`（≤ 500）、`designForm.prompt`（新增必填校验）改为基于 `validateText` 的 computed
  - 后端 `providers/base.py` 已有的 `_count_text_chars` / `validate_text_length` 保持不变，前后端计数规则（汉字 = 2 字符）继续对齐

- **MiniMax 声音设计 hint 补充字数上限说明**：
  - 「预览文本」的 hint 由原来的「试听音频的合成将收取 2 元/万字符的费用」调整为「最大 500 字符（汉字按 2 字符计算）；试听音频的合成将收取 2 元/万字符的费用」

### Fixed

- **修复百炼声音设计「预览文本」为空时不报错的 bug** (`pages/tts_manager/components/common/bailian_speech_synthesizer.js`)：
  - 原模板对 `preview_text` 的 `:class="{'input-error': ...}"` 与 `v-if="..."` 均带有 `&& designForm.preview_text` 条件，导致用户清空输入框后既无红框也无错误提示，仅「设计音色」按钮被禁用，无法得知原因
  - 现统一改为直接基于 `!isPreviewTextValid` / `previewTextError` 渲染，空值时正确显示红框与「⚠️ 预览文本不能为空」
  - 「声音描述」字段同步做相同处理，`voice_prompt` 为空时也会立刻给出红框与提示

- **修复 MiniMax 声音设计「音色描述」为空时无任何提示的问题** (`pages/tts_manager/components/minimax_speech_2_8.js`)：
  - 新增 `designPromptError` computed（基于 `validateText(designForm.prompt, { label: '音色描述', required: true })`），并在模板中以 `:class` / `error-hint` 形式接入，为空时显示红框与「⚠️ 音色描述不能为空」
  - `isDesignEnabled` 改为直接基于 `!designPromptError && !designTextError && isDesignVoiceIdValid`，去掉原先单独判断 `designForm.prompt.trim().length > 0` 的分支，避免校验分散
  - `performDesign()` 的前置校验改为直接复用 `designPromptError.value` / `designTextError.value`，与模板展示的文案保持一致

- **统一 logger 获取方式** (`src/file_server.py`、`providers/utils/audio.py`、`main.py`、`src/config.py`、`src/sub_agent.py`、`src/tts_service.py`、`providers/*`)：
  - 移除内置 `logging` 模块的 `import logging` / `logging.getLogger(__name__)` 用法（涉及 `src/file_server.py`、`providers/utils/audio.py`）
  - 全部 `from astrbot.core import logger` 统一改为 `from astrbot.api import logger`
  - 修复后全量检索无 `logging.getLogger` / `astrbot.core import logger` 残留

- **修复临时文件服务器的路径穿越风险** (`main.py`)：
  - `start_file_server` / `stop_file_server` / `file_upload` 原先将用户可控的 `file_id` 直接与 `self.plugin_data_path / 'uploads'` 拼接，含 `../` 的 `file_id` 可越权读取或 `unlink` uploads 之外的文件
  - 新增模块级 `_validate_file_id()`：以白名单正则 `^[A-Za-z0-9_\-]{1,128}$` 从字符集上排除 `.`、`/`、`\` 等一切路径分隔符
  - 新增 `TTSEnhancerPlugin._resolve_uploads_path()`：在 `Path.resolve()` 后再次比较父目录，作为防御性编程，确保解析结果不逃逸出 `uploads`
  - 三个路由在入口处校验，非法 `file_id` 返回 `400 非法 file_id: ...`，不再触达文件系统
  - `upload_file` 顺带对上传文件扩展名做白名单（wav / mp3 / m4a / aac / ogg / flac），避免异常后缀文件落入 `uploads` 目录

## [0.2.6] - 2026-09-18

### Changed

- 删除职责被拆分完全的 parse_subagent_response 函数
- 百炼现在会将 MODEL_NAME 拼接进 get_subagent_system_prompt
- **抽取供应商后端公共逻辑到 `providers/utils/`**：
  - 新增 `providers/utils/http.py`：
    - `bearer_headers()`：统一构造 Bearer 认证请求头，支持可选 `Content-Type: application/json`
    - `extract_error_message()`：统一从响应 JSON 提取错误信息（`message` → `error` → `detail` → 回退文本）
  - `providers/utils/audio.py` 新增 `save_audio_bytes()`：统一音频字节落盘逻辑（校验 `_data_dir`、创建目录、时间戳命名、写入文件）
  - 百炼适配器：5 处请求头构造、3 处错误信息提取、`_download_audio()` 落盘逻辑改为复用上述工具
  - MiniMax 适配器：9 处请求头构造、`call_api()` 落盘逻辑改为复用上述工具
  - MiniMax 适配器新增 `_check_base_resp()` 私有方法，收敛 8 处重复的 `base_resp.status_code` 状态检查，各调用点保留原有失败处理语义（抛异常 / 记录日志并返回）

## [0.2.5] - 2026-09-07

### Added

- **基类新增通用校验工具** (`providers/base.py`)：
  - `validate_voice_id()`：校验音色 ID 格式（长度 8 ~ 256，首字母英文字母，仅允许字母/数字/-/_，末位不可为 - 或 _）
  - `_count_text_chars()`：默认 CJK 统一汉字按 2 字符计数，其他字符按 1 字符，与前端 `countChars` 逻辑保持一致
  - `validate_text_length()`：基于 `_count_text_chars` 进行文本长度校验，支持 `min_len`/`max_len`/`field_name` 参数
  - 各适配器可直接调用基类方法，无需重复实现校验逻辑

- 增补 Doc strings

### Changed

- **MiniMax Speech 2.8 适配器** (`providers/minimax_speech_2_8.py`)：
  - `_create_voice_by_clone()` 中：
    - 调用 `validate_voice_id()` 校验自定义 `voice_id`（若提供），校验失败抛出 `ValueError`
    - 调用 `validate_text_length()` 校验 `text`（试听文本，≤ 1000 字符）和 `text_validation`（ASR 验证文本，≤ 200 字符）
    - 增加 `accuracy` 范围校验 (0 ~ 1)，超出范围时自动回退为默认值 0.7 并记录警告
  - `_create_voice_by_design()` 中调用 `validate_text_length()` 校验 `preview_text`（≤ 500 字符）
  - 移除原有的硬编码长度检查 (`len(preview_text) > 500`)，统一使用基类 `_count_text_chars` 计数规则

- **百炼 Speech Synthesizer 适配器** (`providers/_bailian_speech_synthesizer.py`)：
  - `_create_voice_by_clone()` 中增加 `max_prompt_audio_length` 范围校验 (3.0 ~ 30.0)，若不在范围内抛出 `ValueError`
  - `_create_voice_by_design()` 中调用 `validate_text_length()` 校验 `voice_prompt`（≤ 500 字符）和 `preview_text`（15 ~ 200 字符）
  - 确保设计模式下的文本校验规则与前端一致

- **前端组件** (`pages/tts_manager/components/*.js`)：
  - 无功能性变更，但后端校验规则已与前端对齐，消除字符计数不一致的潜在问题

### Fixed

- **修复前后端校验不一致问题**：
  - 原后端使用 Python `len()` 按 Unicode 码点计数 (中文 = 1)，前端使用汉字 = 2 字符计数，现统一为汉字 = 2 字符
  - MiniMax 试听文本（`text`）和 ASR 验证文本（`text_validation`）后端补全长度校验，防止超长文本导致 API 失败
  - 百炼 `voice_prompt` 和 `preview_text` 补全长度校验，与前端限制保持一致
  - `accuracy` 和 `max_prompt_audio_length` 补全数值范围校验，避免无效参数传递到 API

## [0.2.4] - 2026-09-06

### Added

- 添加 logo.png

### Changed

- 更新 README.md

## [0.2.3] - 2026-09-06

### Added

- **新增 MiniMax Speech 2.8 完整前端管理界面** (`pages/tts_manager/components/minimax_speech_2_8.js`)：
  - 支持复刻音频（主音频）与示例音频的文件管理：上传 (含自定义文件名)、列表展示、播放、删除
  - 支持音色复刻（克隆）与声音设计两种创建模式，完全遵循 MiniMax API 规范
  - 集成全局音频播放控制：统一管理播放实例，点击播放/停止切换，音量滑条实时调节
  - 前端表单校验 (汉字按 2 字符，其他按 1 字符)：
    - Voice ID：长度 8-256，首字母英文字母，仅允许字母/数字/-/_，末位不可为 - 或 _
    - 试听文本：≤ 1000 字符
    - ASR 验证文本：≤ 200 字符
    - 声音设计预览文本：≤ 500 字符
    - 上传按钮、复刻/设计按钮在条件不满足时自动禁用
  - 自定义删除确认模态框（替代 `confirm()`，适配 iframe 沙箱）
  - 音色列表分区展示：自定义音色（克隆/设计）和系统音色，系统音色显示名称与描述且不可删除
  - 未激活音色管理 (`minimax_unactivated_list` KV 存储)：
    - 复刻/设计成功后提供 “删除”（调用 API 删除服务端音色）与 “保留”（存入本地 KV）选项
    - 音色列表新增 “未激活音色” 分区，显示本地保留的未激活音色
    - 点击 “预览 (激活)” 调用语音合成接口激活音色，激活后自动从本地移除并刷新服务端列表
    - 仅在存在未激活音色时显示提示横幅
  - 重要通知横幅：补充临时音色说明、预览扣费提示、定价文档复制链接
  - 文件上传流程重构：先调用 `/upload` 上传到本地，再调用 `/file/upload` 透传给适配器，适配器处理校验与裁剪

- **前端组件注册** (`pages/tts_manager/app.js`)：
  - 将 `MinimaxSpeech2_8` 组件映射到 `minimax_speech_2_8` 模板键

- **通用路由增强** (`main.py`)：
  - `/file/upload` 改为纯透传：仅提取 `entry_id` 和 `file_id`，其余参数（含 `purpose`、`filename` 等）全部透传给适配器
  - `/upload` 简化为仅保存文件，不再包含校验逻辑，保持单一职责

### Changed

- **适配器文件上传增强** (`minimax_speech_2_8.py`)：
  - `upload_file()` 支持 `filename` 参数，允许用户自定义上传文件名（自动补全扩展名）
  - 文件大小限制由 15MB 恢复为 20MB（与 MiniMax 官方一致）

- **前端交互优化**：
  - 示例音频上传：文件选择、自定义文件名、源文本输入、上传按钮布局调整（源文本与上传按钮同排）
  - 音色列表列调整：自定义音色新增“描述”列，系统音色新增“名称”和“描述”列
  - 播放按钮动态样式：播放时变为红色 (`btn-danger`)，停止时恢复默认
  - 表格内操作按钮增加间距（CSS 全局规则 `td .btn-sm { margin-right: 6px; }`）
  - 试听模型版本与语言增强选项仅在试听文本非空时显示

- **未激活音色删除逻辑**：
  - 删除未激活音色时同步调用 MiniMax API 删除服务端音色 (`/voice/delete`)，确保两端一致

## [0.2.2] - 2026-09-05

### Added

- **新增 MiniMax Speech 2.8 适配器** (`providers/minimax_speech_2_8.py`)：
  - 支持 `speech-2.8-hd` 和 `speech-2.8-turbo` 模型
  - 支持情感标签 (`emotion`)、语速 (`speed`)、音量 (`vol`)、语调 (`pitch`)、语言增强（`language_boost`）
  - 支持 LaTeX 朗读 (`latex_read`)，自动强制 `language_boost=Chinese`
  - 支持文本内联语气词标签（`(laughs)`、`(sighs)` 等）和停顿控制（`<#x#>`）
  - 实现文件管理：`upload_file()`、`list_files()`、`get_file_content()`、`delete_file()`
  - 实现音色管理：`create_voice()` (克隆/设计)、`list_voice()`、`delete_voice()`

- **新增通用音频工具模块** (`src/audio_utils.py`)：
  - `get_audio_duration()`：基于 `pydub` 获取音频时长
  - `validate_audio_duration()`：校验音频时长是否在指定范围内
  - `trim_audio_to_max()`：超长音频自动裁剪（保留开头部分）
  - `AudioConstraints`：定义各供应商的时长约束常量

- **新增供应商文件管理路由** (`main.py`)：
  - `POST /file/upload`：上传文件到供应商，支持 `**kwargs` 透传
  - `POST /file/list`：列出供应商文件
  - `POST /file/get`：获取文件内容（Base64 音频）
  - `POST /file/delete`：删除供应商文件

- **新增通用 KV 存储路由** (`main.py`)：
  - `POST /kv/set`：存储键值对
  - `POST /kv/get`：获取键值对
  - `POST /kv/delete`：删除键值对

- **配置 Schema 新增 `minimax_speech_2_8` 模板** (`_conf_schema.json`)：
  - 认证配置：`api_key`、`voice_id`
  - 模型版本：`HD` / `Turbo`
  - 音频参数：`sample_rate`、`format`、`bitrate`、`channel`
  - 文本规范化：`text_normalization`（默认开启）

- **新增 MiniMax 能力文档** (`docs/minimax_speech_2_8.md`)：
  - 支持的参数与枚举值说明
  - 文本内联控制（语气词标签、停顿标记）
  - 功能示例与完整调用示例
  - SubAgent 参数生成指引

### Changed

- **通用上传路由升级** (`main.py /upload`)：
  - 新增可选的时长校验参数：`min_sec`、`max_sec`、`auto_trim`
  - 超长音频支持自动裁剪 (`auto_trim=true`)，保留 `max_sec - 0.5s` 的前段

- **适配器文件管理方法统一为 `**kwargs` 风格** (`minimax_speech_2_8.py`)：
  - 移除硬编码 `purpose` 参数，统一使用 `**kwargs` 接收扩展参数
  - 提升可扩展性，支持未来新增文件用途

- **路由参数透传优化** (`main.py`)：
  - 文件管理路由使用 `{k: v for k, v in data.items() if k not in ['file', 'entry_id']}` 透传所有未知参数
  - 适配器调用处添加 `# type: ignore` 注释，消除 Pylance 静态检查警告

## [0.2.1] - 2026-09-04

### Added

- **新增百炼 Speech Synthesizer 通用前端组件** (`pages/tts_manager/components/bailian_speech_synthesizer.js`，1070 行)：
  - 统一支持上传 (upload)、公网 URL (url)、声音设计（design）三种音色创建模式
  - 通过 `providerConfig` prop 适配不同供应商：`displayName` / `supportedLanguages` / `supportsSystemVoices` / `systemVoiceLinks` / `designHelpLink`
  - 内置 Toast 反馈机制（success/error，3 秒自动消失）
  - 内置独立预览模态框 (与设计模式预览分离)，支持自定义文本试听、保留或删除
  - 完整表单校验：upload 模式字段非空、URL 合法、design 模式字符数（汉字按 2 字符计，voice_prompt ≤ 500、preview_text 15 ~ 200）
  - 内置删除确认模态框，避免沙盒环境 `confirm()` 被拦截
- **新增 CosyVoice v3.5 前端组件** (`pages/tts_manager/components/bailian_cosyvoice_v3_5.js`)：作为通用组件的薄封装，声明 `displayName`、12 种支持语言、`supportsSystemVoices: false` (v3.5 不支持系统音色)、设计音色帮助链接
- **前端 app.js 接入 CosyVoice v3.5 选项卡**：组件映射表与显示名映射表新增 `bailian_cosyvoice_v3_5` 条目

### Changed

- **前端重构**：`bailian_qwen_audio_3_0_tts.js` 从 1030 行的内联实现改为 33 行的 `BailianSpeechSynthesizer` 包装层，仅声明 Qwen 特有的 `providerConfig`（16 种支持语言、系统音色列表、帮助链接）
- **Provider 工厂鲁棒性增强** (`providers/__init__.py`)：新增 `obj.__module__ == module.__name__` 检查，防止基类通过多继承方式被重复发现并注册到错误模块名下
- **适配器日志安全增强** (`providers/_bailian_speech_synthesizer.py`)：初始化时对 `entry` 字典做 `api_key` 脱敏 (仅保留后 5 位，前缀 `*****`)，避免 API Key 写入 debug 日志

## [0.2.0] - 2026-08-31

### Added

- **新增百炼 CosyVoice v3.5 适配器** (`bailian_cosyvoice_v3_5.py`)：
  - 支持 `cosyvoice-v3.5-flash` 和 `cosyvoice-v3.5-plus` 模型
  - 支持语言列表 (12 种)：zh、en、fr、de、ja、ko、ru、pt、th、id、vi
  - 适配器仅需设置 `MODEL_NAME = "cosyvoice-v3.5"` 和 `VALID_LANGS`，即可复用基类所有能力
  - **注意**：CosyVoice v3.5 不支持系统音色，仅支持声音复刻与声音设计生成的定制音色

- **新增百炼 Speech Synthesizer 公共基类** (`_bailian_speech_synthesizer.py`，以下划线前缀防止自动发现注册)：
  - 抽取 Qwen-Audio-TTS 与 CosyVoice 的公共逻辑，消除重复代码
  - 通过 `MODEL_NAME` 类属性驱动模型名构造、音色过滤、设计音色判断，子类只需声明模型前缀即可接入
  - `get_docs_for_voice()` 自动根据 `MODEL_NAME` 分段计算 `vd` 位置，兼容 Qwen（8 段，vd 在索引 5）与 CosyVoice（6 段，vd 在索引 3）的设计音色 ID 格式差异
  - `_extract_model_from_voice_id()` 从音色 ID 中提取 `flash`/`plus` 后缀，供 `call_api()` 自动匹配模型版本
  - 统一管理工具 Schema、参数校验、API 调用、音频下载及音色管理（创建/列表/删除）逻辑
  - 补充缺失的 pitch 参数

- **配置 Schema 新增 `bailian_cosyvoice_v3_5` 模板** (`_conf_schema.json`)：
  - 新增供应商配置模板，`voice` 字段默认值为空并添加提示："CosyVoice v3.5 不支持系统音色，请使用声音复刻或声音设计生成的音色 ID"
  - `hint` 标注："不支持情感标签，支持指令控制 (仅支持复刻/设计音色)"

- **新增 CosyVoice v3.5 能力文档** (`docs/bailian_cosyvoice_v3_5.md` 与 `docs/bailian_cosyvoice_v3_5_design.md`)：
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
  - 字符数校验：汉字按 2 字符计算，voice_prompt ≤ 500 字符，preview_text 15 ~ 200 字符
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

- 新增临时文件服务器 `src/file_server.py` (基于 aiohttp)：`TempFileServer` 绑定 `0.0.0.0:internal_port` 提供单文件下载服务，支持按扩展名返回对应 MIME 类型（wav/mp3/m4a 等）
- `main.py` 新增 Web API：
  - `POST /upload`：上传音频文件 (仅允许 wav/mp3/m4a)，以 `upload_{时间戳}{扩展名}` 生成唯一 file_id 返回。
  - `POST /start_file_server`：按 `file_id` + `internal_port` 启动临时文件服务器。
  - `POST /stop_file_server`：停止服务器并删除对应的临时上传文件。
  - `POST /voice/preview`：音色试听——用指定 voice_id 合成语音，以 Base64 返回音频数据。
- 前端 `bailian_qwen_audio_3_0_tts.js` 新增音色创建双模式选项卡：上传音频文件（需公网 IPv4 + 端口转发）与公网音频 URL，两块表单独立校验。
- 前端新增音色预览模态框：输入自定义文本，调用 `/voice/preview` 获取 Base64 音频并直接播放。
- `providers/bailian_qwen_audio_3_0_tts.py` 支持从 `raw_params` 覆盖 voice，并从音色 ID 自动推断模型版本（flash/plus）

### Changed

- 前端改用 Vue 的 UMD 版本，直接通过 `<script>` 标签引入避免 CDN 加载问题。
- 前端所有 Web API 调用统一走 `AstrBotPluginPage` bridge (含文件上传 `bridge.upload`)，绕开 Pages 的 asset_token 鉴权与跨域限制。
- `main.py` 的音频下载目录改为插件数据目录 `plugin_data/tts_enhancer/audio`，由 `_data_dir` 注入适配器。
- 上传文件的唯一文件名不再包含原始文件名，避免 URL 编码问题。
- 修正 `start_file_server` 路由描述与实际行为的一致性。
- 优化 `list_voices`/`delete_voice`/`preview_voice` 的错误提示（"无法创建适配器" → "无法创建适配器，请检查配置"）

## [0.1.3] - 2026-08-18

### Added

- 新增音色管理 Web API 路由 (`main.py`)：
  - `GET /tts_enhancer/providers`：按 `template_key` 分组返回已配置的供应商列表，API Key 脱敏。
  - `POST /tts_enhancer/voice/create`：创建音色，按 `entry_id` 路由到对应适配器的 `create_voice()`。
  - `POST /tts_enhancer/voice/list`：查询音色列表，路由至适配器的 `list_voice()`。
  - `POST /tts_enhancer/voice/delete`：删除音色，路由至适配器的 `delete_voice()`。
- `providers/base.py` 新增音色管理抽象方法：`create_voice()`、`list_voice()`、`delete_voice()`，默认抛出 `NotImplementedError`，由各供应商适配器自行实现。
- `providers/bailian_qwen_audio_3_0_tts.py` 实现百炼音色管理：
  - `create_voice()`：调用百炼 `voice-enrollment` / `create_voice` API，支持 `audio_url`、`prefix`、`language_hints`、`enable_volume_normalization`、`enable_preprocess` 等参数。
  - `list_voice()`：调用 `list_voice` API，仅返回 `qwen-audio-3.0-tts` 开头的音色列表。
  - `delete_voice()`：调用 `delete_voice` API 删除指定音色。
- 新增音色管理 Pages 前端 (`pages/tts_manager/`)：
  - `index.html`：Vue 3 应用骨架，动态渲染供应商选项卡。
  - `app.js`：应用入口，按供应商模板分组配置，管理当前编辑的供应商。
  - `components/bailian_qwen_audio_3_0_tts.js`：百炼专属配置组件，包含 `audio_url`、`prefix`、`enable_preprocess` 等字段，并支持音色列表查询。

## [0.1.2] - 2026-08-16

### Changed

- `main.py` 精简为入口层 (`__init__` / `_register_routes`)，业务逻辑拆到 `src/config.py`、`src/tts_parser.py`、`src/sub_agent.py`。
- 为 `on_llm_req`、`on_decorate`、`_get_context_messages`、`_synthesize`、`_process_tts_text` 补充了符合 PEP 257 的 docstring，明确 Args / Returns。

## [0.1.1] - 2026-08-16

### Added

- 引入百炼 Qwen Audio 3.0 TTS 适配器 (`providers/bailian_qwen_audio_3_0_tts.py`)：
  - 继承 `BaseProviderAdapter`，基于 OpenAI 兼容协议调用 `qwen-audio-3.0-tts-*` 模型。
  - 在 `call_api()` 中调用 `validate_params` / `sanitize_params` 过滤非法参数（speed/pitch/volume 范围、voice 前缀）
  - `get_subagent_system_prompt()` 输出百炼专属 SubAgent 提示词。
- 新增 `providers/base.py`：定义 `BaseProviderAdapter` 抽象基类，提供 `call_api`、`validate_params`、`sanitize_params`、`parse_subagent_response` 等统一接口。
- 新增 `providers/__init__.py`：`ProviderFactory` 按 `__template_key` 自动实例化适配器。
- 新增 `docs/qwen_audio_3_0_tts.md`：百炼模型官方参数文档（speed/pitch/volume 范围、voice 枚举、voice_clone 配置）

### Changed

- 移除旧引擎 (`providers/tts_engine.py`)，统一改为 Adapter 架构。
- `_synthesize()` 调用链：`validate_params` 校验 → 失败时 `sanitize_params` 兜底清理 → SubAgent 上下文反馈重试。

## [0.1.0] - 2026-08-15

### Added

- 初始三层架构：主模型（LLM + TTS 提示词）→ SubAgent（tts_enhance 工具 + 文档）→ Provider Adapter（API 调用）
- `main.py` 实现事件钩子：`on_llm_req` (追加 TTS 提示词)、`on_decorate`（解析 `<tts>` 标签触发合成）
- `_synthesize()` 多供应商优先级遍历、降级逻辑 (无文档 → 纯文本)。
- `_get_context_messages()` 上下文窗口提取 (最近 N 条历史)。
- `src/config.py`：`TTSEnhancerConfig` 配置类（`tts_prompt`、`enable_enhance`、`context_window`、`dual_output` 等）
- `src/tts_parser.py`：`split_by_tts_tags()` 解析 `<tts>...</tts>` 标签。
- `src/sub_agent.py`：`TTSSubAgent` 调用 AstrBot 内置 Agent 框架。
- 支持 `Record.fromFileSystem` 音频消息输出。