# TTS Enhancer Development Guide

> A hands-on manual for plugin contributors and maintainers.
> Companion docs: [Architecture Document](ARCHITECTURE.md) · [Known Limitations & Upstream Responsibility](KNOWN_LIMITATIONS.md) · [English README](../en/README.md) · [CHANGELOG](../../CHANGELOG.md)

This guide follows "how to add a new TTS provider" as its main thread, tying together adapters, capability docs, configuration, the frontend, testing, and every other link in the chain.

---

## 1. Environment Setup

### 1.1 Runtime / Debug Environment

- Python ≥ 3.10 (same as AstrBot).
- Within the AstrBot source tree, symlink or copy this plugin directory to `data/plugins/astrbot_plugin_tts_enhancer/`, then enable the plugin in the WebUI after starting AstrBot.
- Backend dependencies (async HTTP, etc.) come with the main AstrBot environment; if an adapter needs additional libraries, add them to `requirements.txt` in the plugin root (AstrBot will install them).

### 1.2 Test Environment (pytest)

- The test suite lives in `tests/`; `pytest.ini` already sets `asyncio_mode = auto`.
- `requirements-tests.txt` declares `pytest` and `pytest-asyncio`, isolating the main environment's dependencies.
- `tests/conftest.py` **probes upward for the AstrBot source root** (no longer hardcodes a level) and uses `pytest.importorskip("astrbot.core.provider")` — when run outside the AstrBot source tree it skips gracefully rather than crashing.

```bash
# in the plugin root
pip install -r requirements-tests.txt
pytest                # run within the AstrBot source tree
```

### 1.3 Frontend (No Build Step)

- The frontend uses native ES Modules + a local Vue UMD build, with **no bundling step** — JS changes take effect immediately.
- Only `eslint.config.mjs` provides optional linting (development only); its dependencies are listed under `devDependencies` in `pages/tts_studio/package.json`.
- Optional: `cd pages/tts_studio && npm install && npx eslint .`.

---

## 2. Directory Structure

```
astrbot_plugin_tts_enhancer/
├── main.py                      # Plugin entry: hooks + Web routes + security validation
├── metadata.yaml                # Plugin metadata (name/version/author/repo...)
├── _conf_schema.json            # Config schema (includes provider templates)
├── README.md / CHANGELOG.md
├── requirements-tests.txt       # Test dependencies (pytest / pytest-asyncio)
├── src/
│   ├── config.py                # TTSEnhancerConfig: config loading/sorting/deduplication
│   ├── tts_parser.py            # <tts> tag parsing
│   ├── tts_service.py           # Synthesis orchestration core
│   ├── sub_agent.py             # SubAgent (Function Calling param generation)
│   └── tools.py                 # send_voice_to_user proactive voice tool
├── providers/
│   ├── __init__.py              # ProviderFactory (auto-discovery)
│   ├── base.py                  # TTSProviderAdapter abstract base class
│   ├── _bailian_speech_synthesizer.py  # Bailian common base (underscore prefix, not discovered)
│   ├── <vendor>_<model>.py      # Concrete adapter (i.e. the template_key)
│   ├── utils/{http,audio}.py    # Shared HTTP / audio utilities
│   └── docs/<docs_key>.md       # Capability docs (including *_design.md)
├── pages/tts_studio/           # Frontend (Vue 3, no build step)
│   ├── index.html / app.js / style.css
│   ├── components/common/       # Components shared across providers
│   ├── components/*.js          # Per-provider components
│   ├── composables/             # useAudioManager / useTextValidator ...
│   └── static/vue.global.prod.js
└── tests/                       # pytest suite
```

---

## 3. Adding a New TTS Provider (Checklist)

| Step | Deliverable | Required? |
|------|-------------|-----------|
| 1. Write the adapter | `providers/<template_key>.py` | ✅ |
| 2. Write the capability doc | `providers/docs/<docs_key>.md` (possibly with `_design.md`) | ✅ (otherwise falls back to plain text) |
| 3. Config schema | Add a template under `providers.templates` in `_conf_schema.json` | ✅ |
| 4. Frontend integration | `pages/tts_studio/components/*.js` + registration in `app.js` | Only if a UI is needed |
| 5. Tests | Add cases under `tests/` | Strongly recommended |

> All new providers are **auto-discovered and loaded** by `ProviderFactory`, with no core code changes required. The file name (without `.py`) is the `template_key` and must match the `templates` key in `_conf_schema.json`.

---

## 4. Adapter Development in Detail

### 4.1 Minimal Working Adapter

```python
"""Example TTS adapter"""

from .base import TTSProviderAdapter


class ExampleTtsAdapter(TTSProviderAdapter):
    """Example provider adapter"""

    def get_subagent_system_prompt(self) -> str:
        docs = self.docs_content
        return (
            f"You are a speech-synthesis parameter optimization assistant. Parameter docs:\n\n{docs}\n\n"
            "Call the tts_enhance tool directly, with no extra explanation."
        )

    def get_tool_schema(self):
        # Build tts_enhance via the base class build_enhance_tool and auto-attach the validation handler
        # (see base.py: fixed tool name, unified FunctionTool construction, and _handle_enhance_tool wiring)
        return self.build_enhance_tool(
            description="Parameters needed to synthesize text into speech",
            parameters={...},  # this adapter's parameter schema
        )

    async def call_api(self, text, raw_params, config, voice_id=None) -> str:
        # 1. Merge config and raw_params (tool params take precedence)
        # 2. Build the request, call the API, download the audio
        # 3. Persist to disk and return the path; return "" on failure (never throw uncaught exceptions into the main flow)
        ...
```

### 4.2 Required Abstract Methods

- `get_subagent_system_prompt() -> str`: concatenates the capability doc to guide the SubAgent in producing params.
- `get_tool_schema() -> FunctionTool | None`: returns the `tts_enhance` tool via the base class `build_enhance_tool` (with the validation handler attached). Returning `None` means Function Calling is unsupported (plain-text fallback will be used).
- `call_api(text, raw_params, config, voice_id=None) -> str`: the synthesis core. Returns the audio file path; **return an empty string on failure** rather than throwing (the main flow uses this to switch providers). `voice_id` explicitly overrides the voice during preview.

### 4.3 Optional Capabilities (Voice / File Management)

By default these `raise NotImplementedError`, which the `main.py` routes catch and return `501` for. Once implemented they are called by the frontend/routes:

- Voice: `create_voice(params)`, `list_voice(**kwargs)`, `delete_voice(**kwargs)`.
- File: `upload_file(file_path, **kwargs)`, `list_files(**kwargs)`, `get_file_content(file_id)`, `delete_file(file_id, **kwargs)`.

> The file management routes (`/file/*`) pass through all parameters except `entry_id`/`file_id` to the adapter as `**kwargs`, keeping extension flexible.

### 4.4 Param Validation and Sanitization

- **Range/enum validation**: override `validate_params(params) -> (bool, str)`. When it returns `(False, msg)`, the SubAgent feeds a structured `role:"tool"` tool result (including the error text) back to the LLM for a retry; a final failure falls back to `sanitize_params` cleanup.
- **Sanitization**: override `sanitize_params(params) -> dict` to discard invalid values and keep valid ones (e.g. normalize numbers returned as strings by the LLM to numeric values via `_as_float`/`_as_int`, excluding `bool`).
- **Common validation**: use the base class `validate_voice_id()` and `validate_text_length()` directly (Chinese character = 2 units, aligned with the frontend `useTextValidator`) to avoid reimplementation.
- **Type safety**: always parse params through `_as_float` / `_as_int`, avoiding both "rejecting string numbers" and "missing bool".

### 4.5 Audio Persistence Convention

- Synthesis outputs are all persisted via `save_audio_bytes(data_dir, content, fmt)` in `providers/utils/audio.py` — it saves under `config["_data_dir"]` with a timestamp-based name and returns the path.
- `_data_dir` is injected into the entry dict by `TTSService`/`main.py` (value: `plugin_data/<name>/audio`); adapters **must not hardcode paths**.

### 4.6 Reusing Utils

- `providers/utils/http.py`: `bearer_headers(api_key, with_json=True)`, `extract_error_message(payload, fallback_text)` (tolerant of `message`/`error`/`detail`).
- `providers/utils/audio.py`: `save_audio_bytes(...)`, `get_audio_duration`, `validate_audio_duration`, `trim_audio_to_max`, `AudioConstraints` (duration constraint constants per platform).

### 4.7 `voice_id` Override Convention

The `voice_id` param of `call_api` is used to "explicitly override the voice during preview". Standard pattern:

```python
voice = voice_id or config.get("voice") or config.get("voice_id")
if not voice:
    raise ValueError("No voice ID provided; cannot synthesize speech")
```

Config key names stay consistent with each upstream API (Bailian `voice`, MiniMax `voice_id`) and are not forcibly unified.

---

## 5. Capability Doc Authoring Guidelines

File: `providers/docs/<docs_key>.md`, read and injected directly by the SubAgent. Recommended structure:

1. **Overview**: the model's origin and positioning.
2. **Core parameter table**: required/optional params (type, range, default, description).
3. **Enums**: languages, emotion tags, dialects, etc.
4. **Usage examples**: including a complete `tts_enhance` param example.
5. **`## 你的任务`** (key section): explicitly tell the SubAgent how to choose params from context and when to call `tts_enhance`.
   - Example: "Add control tags to text according to the context tone; use instruction/rate/volume to control the details; call tts_enhance directly."

If a class of voices (e.g. designed voices) has limited capabilities (no dialect support), describe it separately in `<docs_key>_design.md` and switch automatically by voice ID in the adapter via `get_docs_for_voice(voice)`; providers using the same model can set the subclass `DOCS_KEY` to reuse a doc.

---

## 6. Extending the Config Schema

Add a template keyed by `template_key` under `providers.templates` in `_conf_schema.json`:

```json
"my_provider": {
  "name": "My Provider",
  "hint": "One-line capability description",
  "display_item": "display_name",
  "items": {
    "display_name": { "description": "Display name", "type": "string", "default": "My Provider" },
    "priority":     { "description": "Priority (smaller values take precedence)", "type": "int", "default": 0 },
    "persona_id":   { "description": "Bound persona", "type": "string", "_special": "select_persona", "default": "" },
    "api_key":      { "description": "API Key", "type": "string", "secret": true },
    "model":        { "description": "Model", "type": "string", "options": ["a", "b"], "default": "a" }
  }
}
```

Key points:

- `_special: select_provider` / `select_persona`: renders as a dropdown selector.
- `secret: true`: masked password field.
- `options`: fixed-enum dropdown; `condition`: show conditionally based on other field values (e.g. MiMo switches voice/design/clone fields by `model`).
- The framework automatically injects `__template_key` and the display name specified by `display_item`.

---

## 7. Frontend Integration

### 7.1 When a Frontend Is Needed

- **Already has an official console**: just add a display name in `getDisplayName` in `app.js` and configure an external link in `providerConfig` — **no component needed**.
- **API only**: write a component under `components/`, reuse the shared components in `components/common/`, and register it in `componentMap` in `app.js`.

### 7.2 Component Registration (`app.js`)

```js
import MyProvider from './components/my_provider.js';
// add to componentMap: 'my_provider': MyProvider
// add to getDisplayName: 'my_provider': 'My Provider'
```

### 7.3 providerConfig and Shared Components

Bailian-family providers directly reuse `components/common/bailian_speech_synthesizer.js`; the thin wrapper declares only the differences:

```js
export default {
  components: { BailianSpeechSynthesizer },
  // providerConfig: { displayName, supportedLanguages, supportsSystemVoices, systemVoiceLinks, designHelpLink }
};
```

The shared component already encapsulates clone/design modes (clone audio is encoded into a Data URL by the browser and submitted directly), preview, listing, deletion, as well as `voice_preview_modal` / `delete_confirm_modal` (replacing `confirm()` in sandboxes).

### 7.4 Bridge API

All backend calls go through `window.AstrBotPluginPage` (`bridge`):

- `await bridge.ready()`: ensure the bridge is ready.
- `await bridge.apiGet('providers')`: fetch the grouped provider list.
- `bridge.upload(...)`: file upload (bypasses `asset_token` auth and cross-origin issues).
- All other routes are called as `bridge.apiPost('<route>', payload)` (e.g. `voice/create`, `file/upload`, `kv/set`, etc.).

### 7.5 Composables

- `useAudioManager`: global audio playback singleton (shared volume, cross-component toggle).
- `useTextValidator`: `countChars` (Chinese character = 2), `validateText({label,min,max,required})` → `{valid,error,count}`.
- `useClipboard`, `useToast`: clipboard and notifications.

### 7.6 Floating Layers and Animation Conventions

- **Always Teleport modals / toasts to body**: `<Teleport to="body"><Transition name="modal"><div class="modal-overlay">…`. After a page-level fade-in (`animation-fill-mode: both`) finishes, Chrome leaves two kinds of side effects on ancestors — an identity-matrix transform (becoming the containing block for fixed descendants, anchoring floating layers to the animated ancestor's box) and a compositing layer (i.e. a stacking context, locking z-index in the subtree); teleporting to `body` is the only robust fix. Size overlays with `100vw/100vh`, not `100%` (the classic scrollbar issue).
- **Use `<Transition>` for enter/leave, not CSS animation**: a Transition's enter/leave classes are removed once finished, returning the element to its normal state; `animation-fill-mode: both` permanently leaves the transform / compositing layer on the element (the root of the two side effects above).
- **Use transform for continuous transitions**: e.g. the tab highlight bar `translateX + scaleX` + `will-change`, which runs on the compositor and avoids per-frame layout on the main thread.
- **reduced-motion**: all animations set `transition/animation: none` under `@media (prefers-reduced-motion: reduce)`.
- **Theme attributes / CSS variables must be attached only to `html` / `body`, never to `#app`**: teleported floating layers (volume bar, all modals, toasts) are outside the `#app` subtree, so the only definitions they can inherit are at the `:root` / `html` level. Currently theme variables are all on `:root`, so floating layers are safe; but this is an **implicit contract** — if theme attributes or variables are moved onto `#app` in the future, all floating layers will silently lose their theme without any error.

---

## 8. Testing Conventions

### 8.1 Running Tests

```bash
pip install -r requirements-tests.txt
pytest                 # within the AstrBot source tree
pytest tests/test_xxx.py -k "case"   # single file / single case
```

### 8.2 conftest Conventions

- Auto-detect the AstrBot source root and skip via `importorskip` when dependencies are missing.
- Provide fixtures for constructing `entry` objects, mocking Providers, etc. (see `tests/conftest.py`).

### 8.3 xfail Conventions (Important)

- For known bugs / design trade-offs / upstream guarantees / unreachable paths, **pin them with `@pytest.mark.xfail`** as a regression signal, rather than writing ordinary tests that "hardcode the status quo" and block future fixes.
- After fixing the corresponding bug, convert the xfail into an ordinary regression test.
- After writing a new test, **revert the change to confirm the test fails**, avoiding false-positive tests.
- **After review** (following the temporary "pin with xfail" stage above): once an observed item is judged "will not be fixed" after a second review, **xfail should not be kept long-term**; handle it according to its nature and record it in `docs/zh/KNOWN_LIMITATIONS.md`:
  - Design trade-offs → convert to an ordinary green test asserting the "accepted behavior" (remove the `should_not` bug implication from the name), locking the current contract.
  - Upstream guarantees / unreachable paths → **keep as a green-test guard** (still lock the current behavior and retain the regression sentinel; do not delete it); if the "unreachable" argument may become invalid after refactoring (e.g. #14), add one line of minimal code hardening.

---

## 9. Code Style and Comments

- Comments and logs default to **Chinese** (a third-party personal plugin; English is used only when submitting a PR to the main AstrBot repo).
- Docstrings follow the **Google style** (`Args`/`Returns`/`Raises`); see existing modules.
- Logging uniformly uses `from astrbot.api import logger`; do not use the built-in `logging`.
- Follow KISS: avoid unnecessary abstractions and helpers; do not extract functions for logic that can be inlined.
- Use `pathlib.Path` for path handling; do not concatenate strings.

---

## 10. Release and Versioning

1. **Code changes** → 2. **Version number** (`version` in `metadata.yaml`, kept as `vX.Y.Z`) → 3. **README/CHANGELOG** update → 4. **Branch + commit** → 5. **Push** (personal GitHub account, PAT).
2. `CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) + Semantic Versioning.
3. Multi-round tasks end with "wrap-up verification + a CHANGELOG entry".

---

## 11. Common Pitfalls

- **Do not persist data in the plugin's own directory**: write under `plugin_data/`, or it will be lost on update/reinstall.
- **`call_api` returns an empty string on failure rather than throwing**: the main flow relies on the empty string to decide switching providers.
- **Parse params with `_as_float/_as_int`**: the LLM often returns numbers as strings, and `bool` must be excluded.
- **`template_key`, the `_conf_schema.json` template key, and the adapter file name must all match**.
- **Missing capability doc → that provider automatically falls back to plain text** (no error, but enhancement is lost).
