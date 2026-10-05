# 已知限制与上游责任

本文件记录经复核判定为「设计取舍 / 上游担保 / 不可达」、不再由本插件主动修复的行为。

对应测试原以 `@pytest.mark.xfail` 固化，二轮复核后降级为观察项。清理时按性质拆分：

- **设计取舍类**：转为断言「已接受实际行为」的普通绿测（命名去掉 `should_not` 的缺陷暗示），
  锁定当前契约，避免 xfail 持续发出「这是 bug」的误导信号，也避免 `strict=True` 在正常重构时误挂 CI。
- **不可达 / 上游担保类**：用例直接删除（无法构造真实入参，测不到本仓库代码），仅在此留档决策。

## 已删除用例（不可达 / 上游责任）

### 缺陷#6 — providers 误配为 dict 时缺校验（上游担保）

- 现象：`providers` 为非空 dict 时触发 `AttributeError`（配置结构被误配时缺乏校验）。
- 判定：`_conf_schema.json` 已要求 `providers` 为数组，经 WebUI 保存会被 AstrBot
  `validate_config()` 拒绝；仅手工编辑 `data/config/<plugin>_config.json` 绕过防线才可能触发，
  属使用者责任，非本仓库必修项。

### 缺陷#14 — 不可序列化参数中断 synthesize（不可达）

- 现象：`log_enhanced_params` 开启后 `json.dumps` 不在 `try` 内，遇不可序列化对象会中断整个
  `synthesize`。
- 判定：`api_params` 的三个来源（`sub_agent.py:117/129/131`）均为 JSON 原生类型，
  实际无法构造不可序列化入参，不可达，非必修项。

### 缺陷#15 — bool 通过 context_window 类型检查（上游担保）

- 现象：`isinstance(x, int)` 对 `True` 静默通过（`bool` 是 `int` 子类）。
- 判定：该入参来自配置且 schema 声明 `int`，属 AstrBot 校验范围；LLM 输出路径的
  `validate_params` 不受上游覆盖，应自行排 `bool`（对照 P3-3a）。配置侧归上游责任。

## 转为绿测的设计取舍（已接受行为）

- **缺陷#1**（空 / 纯空白 `<tts>` 标签返回空列表）：空标签无内容可念，整段被静默移除可接受。
- **缺陷#3**（嵌套 `<tts>` 标签不递归展开，内层残留）：嵌套属未定义输入，非递归解析器给出
  未定义输出可接受。
- **缺陷#5**（`_load_providers` 就地写入调用方 `raw_config` 的 `__resolved_name`）：仅去重显示名、
  非敏感信息，且 AstrBot 对 schema 外字段宽容、不污染保存流程，接受该行为。
