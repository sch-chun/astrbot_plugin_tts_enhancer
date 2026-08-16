# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.1.2] - 2026-08-16

### Added

- 新增 `src/` 模块化目录，将核心逻辑拆分为独立模块：
  - `src/config.py`：新增 `TTSEnhancerConfig` 配置管理类，负责供应商加载排序、条目命名与配置访问。
  - `src/tts_parser.py`：新增 `<tts>` 标签解析工具，导出 `split_by_tts_tags` 等函数，支持文本/TTS 分段与边界分隔符清理。
  - `src/sub_agent.py`：新的 `TTSSubAgent` 实现，基于 Function Calling 生成结构化参数，并保留纯文本降级路径。
- 为 `ProviderFactory`、`TTSProviderAdapter` 与 `BailianQwenAudio3_0TTSAdapter` 补充详细 docstring 与使用示例。
- 首次创建本 CHANGELOG 文件。

### Changed

- 删除根目录旧版 `sub_agent.py`，SubAgent 逻辑迁移至 `src/sub_agent.py`。
- `main.py` 改用模块化的配置管理与标签解析（不再内联 `_load_providers`、`_split_by_tts_tags` 等实现）。
- README 文案修订。

## [0.1.1] - 2026-08-15

### Added

- 新增百炼 Qwen Audio 3.0 TTS 适配器 `providers/bailian_qwen_audio_3_0_tts.py`，支持通过 Function Calling 接收增强参数（text/instruction/volume/rate/language_hints）。
- 新增对应能力说明书文档 `providers/docs/bailian_qwen_audio_3_0_tts.md`。
- `providers/base.py` 新增 `validate_params()` 与 `sanitize_params()` 方法，为参数校验与清洗提供基类支持。

### Changed

- `ProviderFactory` 改进：使用 `Optional` 类型标注，自动发现适配器并输出日志。
- `main.py` 重构为动态加载 providers，按优先级轮询并增强错误处理。
- `sub_agent.py` 适配新的 Provider 结构，支持结构化参数生成与错误处理。
- `_conf_schema.json` 引入新的 provider 结构（`template_list`），增强配置项（display_name/priority/seed/AIGC 标识等）。
- `.gitignore` 扩充，覆盖更多 Python 工具与环境目录。

### Removed

- 移除旧的 `ali_qwen_audio.py` 适配器，以及 `ali_cosyvoice`、`minimax` 适配器及其能力文档。
- 移除无用的 `.gitkeep` 文件。

## [0.1.0] - 2026-08-14

### Added

- 初始化仓库，建立基础文件结构（`main.py`、`sub_agent.py`、`providers/`、`_conf_schema.json`、`metadata.yaml`、`requirements.txt` 等）。
- 实现核心三层架构：主模型 `<tts>` 标签输出 → SubAgent LLM 增强 → Provider Adapter 调用 TTS API。
- 完成 Provider 适配器（阿里云系多引擎）、配置项与能力说明书文档。
