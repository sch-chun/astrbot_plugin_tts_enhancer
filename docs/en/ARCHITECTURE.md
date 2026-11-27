# TTS Enhancer Architecture Document

> This document is intended for developers and maintainers who wish to gain an in-depth understanding of the plugin's internal mechanisms.
> Companion docs: [Development Guide](DEVELOPMENT.md) · [Known Limitations & Upstream Responsibility](KNOWN_LIMITATIONS.md) · [English README](../en/README.md) · [CHANGELOG](../../CHANGELOG.md)

---

## 1. Design Goals and Positioning

AstrBot's main model (LLM) can only pass plain text to the TTS stage by default. Yet modern speech synthesis services have long supported rich capabilities such as emotion tags, natural-language instructions, dialects, voice cloning, and voice design. TTS Enhancer is positioned to **bridge the gap between "traditional text input" and "providers' rich capabilities"**, and to wire in any speech service in a **highly pluggable** way without modifying core code.

Core design principles:

- **Highly pluggable multi-provider architecture**: each provider is an independent adapter that never interferes with others; adding a provider is plug-and-play.
- **Capability Docs mechanism**: each provider ships a Markdown document describing its parameters and usage; the SubAgent uses it to dynamically generate optimal parameters that "never overstep boundaries".
- **On-demand frontend**: reusable management components are provided only for providers lacking an official web console; providers that already have a console simply link out, avoiding duplicated implementation.
- **Defensive boundaries**: explicit security constraints apply to file IDs, route parameters, upload extensions, API Key handling, and more.

---

## 2. Overall Architecture

On AstrBot's event pipeline, the plugin sits at the "result decoration" stage and is divided into four layers:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Main Model (LLM)                                                                              │
│  - Emits <tts>…</tts> tags (or invoked proactively via an Agent Tool)                          │
│  - on_llm_req injects the TTS trigger prompt                                                   │
└───────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────────────────────────┐
│  TTS Enhancer Plugin (main.py / src/*)                                                         │
│  - on_decorate parses tags → splits text segments and TTS segments                             │
│  - TTSService orchestrates synthesis, context, persona routing, multi-provider fallback        │
│  - SendVoiceTool provides the send_voice_to_user proactive voice tool                          │
│  - Web API routes (voice/file management, upload, KV)                                          │
└───────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────────────────────────┐
│  TTSSubAgent (src/sub_agent.py)                                                                │
│  - Calls the enhancement model Provider (optionally via enhance_llm_provider)                  │
│  - Injects capability docs + persona + context → emits structured params via tts_enhance       │
└───────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────────────────────────┐
│  Provider Adapter (providers/*)                                                                │
│  - Validate/sanitize params → call the real TTS API → download and persist audio               │
│  - Optional: voice management (clone/design/list/delete), file management                      │
│  - Auto-discovery + factory instantiation                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

A complete synthesis can also be viewed from a flow perspective:

```mermaid
flowchart TD
    A[Main model outputs text containing &lt;tts&gt;] --> B[on_decorate hook]
    B --> C[tts_parser splits text segments / TTS segments]
    C --> D[TTSService.synthesize]
    D --> E[Resolve current persona persona_id]
    E --> F[Provider partitioning: persona-bound + universal fallback]
    F --> G{Enhancement enabled AND docs available}
    G -- No --> H[Plain-text call_api fallback]
    G -- Yes --> I[SubAgent generates tts_enhance params<br/>(internally includes role:tool structured retry, ≤2 times)]
    I --> J{Valid params returned?}
    J -- Yes (with final invalid-cleanup fallback) --> M[call_api synthesis]
    J -- No (tool exceptions exhausted) --> Q[Fall back to plain-text synthesis (original text + empty params)]
    Q --> M
    H --> M
    M --> N[Record audio message]
    N --> O[Return message chain]
```

---

## 3. Request Lifecycle (End-to-End)

There are two trigger paths, both of which eventually converge on `TTSService.synthesize()`.

### 3.1 Tag Trigger Path (Default)

1. **`on_llm_req`**: if a provider is configured and `tts_prompt` is configured, the trigger prompt is appended to the system prompt, guiding the main model to wrap the text to synthesize in `<tts>…</tts>`.
2. **`on_decorate`** (`priority=13`): scans the `Plain` text components of the message chain; if a `<tts>` tag is present, it:
   - calls `tts_service.get_context_messages(event)` to fetch the most recent `context_window` turns of context;
   - calls `_process_tts_text()` on text containing tags, processing it segment by segment;
   - uses `split_by_tts_tags()` to split the text into `text` segments and `tts` segments — text segments remain `Plain`, while TTS segments are handed to `synthesize()`;
   - on success returns a `Record` component (optionally preserving the original text via `dual_output`); on failure falls back to `Plain` text.

### 3.2 Tool Trigger Path (Agent Loop)

1. The plugin registers the `send_voice_to_user` tool in `__init__` via `context.add_llm_tools(SendVoiceTool(...))` (defined in `src/tools.py`).
2. The model proactively calls this tool in the Agent loop, passing `text` (and an optional `session`).
3. The tool fetches context internally, calls `tts_service.synthesize()`, and then uses `star_context.send_message()` to send the audio message to the target session.

Both paths share the same `TTSService` instance (constructed in `main.py`, injected with `context / providers / config / audio_data_dir`).

---

## 4. Core Module Breakdown

### 4.1 `main.py` — Plugin Entry Point

Responsibilities: initialization, event hooks, Web API routes, and security validation.

- **`TTSEnhancerPlugin(Star)`**: lifecycle entry point. Initializes the data directories (`plugin_data/<name>/{uploads,audio}`), constructs `TTSService`, registers `SendVoiceTool`, and registers all Web routes.
- **Event hooks**:
  - `on_llm_req`: injects the TTS prompt.
  - `on_decorate`: parses and replaces `<tts>` tags.
- **Web API** (all mounted under the `/<plugin_name>/` prefix; see Section 10 on security design):
  - `GET /providers`: returns the provider list grouped by `template_key`, with `api_key` masked.
  - `POST /voice/{create,list,delete}`: voice management, routed to the adapter by `entry_id`.
  - `POST /upload`: local audio upload (extension whitelist).
  - `POST /voice/preview`: voice preview (returned as Base64).
  - `POST /kv/{set,get,delete}`: generic KV storage (used by the frontend/adapters to store metadata).
  - `POST /file/{upload,list,get,delete}`: provider file management (passes `**kwargs` through).
- **Security helpers**: `_SAFE_FILE_ID_RE`, `_validate_file_id()`, `_resolve_uploads_path()` (compares the parent directory after `resolve()` to prevent traversal), `_parse_entry_id()` (type and bounds checks, excluding `bool`).

### 4.2 `src/config.py` — Configuration Management

`TTSEnhancerConfig` loads and normalizes configuration:

- `_load_providers()`: stable sort by `priority` (smaller values take precedence); detects duplicate `priority` values and duplicate `display_name` values (duplicates automatically get `#2`, `#3` suffixes appended and are written to the private field `__resolved_name`).
- `get_providers()`: returns the sorted provider list.
- `get_entry_name(entry, index)`: resolves the display name (precedence: `__resolved_name` → `display_name` → `template_key (voice)` → `template_key #index` → `template_key`).
- `get(key, default)`: reads a top-level config item; `has_providers()`: whether any providers are configured.
- `_to_priority_int()`: falls back to `100` for non-numeric `priority` values and logs a warning, avoiding an `int/str` mixed-type `TypeError` during sorting.

### 4.3 `src/tts_parser.py` — Tag Parsing

`split_by_tts_tags(text)` splits text containing `<tts>…</tts>` into a list of `{type: 'text'|'tts', content}`:

- Non-string input returns an empty list directly (treated as "no content" rather than raising an exception).
- Handles orphaned closing tags, nesting/missing pairs, and similar cases; tag content is trimmed of boundary separators and whitespace.
- When there are no valid segments at all, falls back to plain text with the tags removed.
- Boundary separator constant: `BOUNDARY_SEPARATORS = "$"` (used to clean up residue at tag boundaries).

### 4.4 `src/tts_service.py` — Synthesis Orchestration

`TTSService` is the "conductor" of the synthesis flow:

- `get_context_messages(event)`: takes the most recent `context_window` **user** messages from `conversation_manager` as the window (counted by user), collects them in reverse order, then restores chronological order; any exception degrades to an empty list.
- `get_current_persona(event)`: resolves the persona in effect for the current session, returning `(prompt, persona_id)`; degrades to empty when `conversation_manager` / `persona_manager` are not ready.
- `synthesize(raw_text, event, context_messages)` (core):
  1. Resolves the persona → partitions providers into **persona-bound** (`persona_id` matches) and **universal fallback** (no `persona_id`), attempting them in order (bound first).
  2. When the candidate list is empty, only a Warning is logged rather than failing silently.
  3. For each entry: inject `_data_dir` → `ProviderFactory.get_adapter()` → determine `enable_enhance = config.enable_enhance and bool(docs_content)`.
  4. **No enhancement / no docs**: synthesize directly as plain text with `raw_params={}` (avoiding a wasted LLM call).
  5. **Enhancement path**: build a `ToolSet` via `adapter.get_tool_schema()` → call `sub_agent.call()` (with internal `max_attempts=2`):
     - The returned structure is validated by `adapter.validate_params()`; on validation failure or a tool execution exception, construct `[assistant(tool_calls), tool(tool_call_id, content)]` and feed it back to the LLM as a structured `role:"tool"` tool result (including the error text) via `provider.text_chat(tool_calls_result=...)` for a retry;
     - if the final validation fails and the adapter supports cleanup, `sub_agent.call()` returns params cleaned by `sanitize_params()`; if tool exceptions are exhausted it returns `None`, and `tts_service` falls back to plain-text synthesis (original text + empty params), switching to the next provider only if that plain-text synthesis also fails.
  6. When the SubAgent returns empty `text`, the original text is kept; on success `call_api()` returns `Record.fromFileSystem(path, text=...)`; on failure it switches to the next provider.

### 4.5 `src/sub_agent.py` — SubAgent

`TTSSubAgent.call(...)` invokes the LLM to generate structured TTS params:

- Resolves the enhancement model: if `enhance_llm_provider` is specified, fetch it by ID; otherwise use the current session Provider; if none is found, reports an error and returns `None`.
- Builds the user prompt: persona + context summary + text to synthesize.
- Calls `provider.text_chat(..., func_tool=tool_set)`; preferentially parses `tools_call_args` where `tools_call_name == 'tts_enhance'`;
- With no tool call, falls back to extracting from `completion_text` (containing only `text`); a final failure returns `None`.
- Retry mechanism: on validation failure or a tool execution exception, construct `[assistant(tool_calls), tool(tool_call_id, content)]` and feed it back structurally via `tool_calls_result` (a true `role:"tool"` object-level loop), rather than flattening it into the prompt; only when the model makes no tool call is a lightweight `role:"user"` hint used to ask it to call again.
- All exceptions are caught and logged, never propagated upward.

### 4.6 `src/tools.py` — Proactive Voice Tool

`SendVoiceTool(FunctionTool)` exposes `send_voice_to_user`:

- Params: `text` (required), `session` (optional, format `platform_id:message_type:session_id`).
- `__post_init__` verifies `tts_service` is non-empty; `call()` fetches context, calls `synthesize()`, and sends via `star_context.send_message()`.

### 4.7 `providers/` — Adapter System

See Section 5.

---

## 5. Provider Adapter System

### 5.1 Abstract Base Class Interface Contract (`providers/base.py`)

`TTSProviderAdapter(ABC)` defines the interfaces that all adapters must or may implement:

**Abstract methods (must implement):**

| Method | Description |
|------|------|
| `get_subagent_system_prompt() -> str` | Generates the system prompt injected into the SubAgent (usually concatenating the capability docs). |
| `get_tool_schema() -> FunctionTool \| None` | Returns the `tts_enhance` tool via the base class `build_enhance_tool` (with the validation handler attached); may return `None` when Function Calling is unsupported. |
| `call_api(text, raw_params, config, voice_id=None) -> str` | Synthesizes and returns the audio file path (or an empty string to indicate failure). `voice_id` is used to explicitly override the voice during preview. |

**Optional capabilities (default `raise NotImplementedError`):**

- Voice management: `create_voice(params)`, `list_voice(**kwargs)`, `delete_voice(**kwargs)`.
- File management: `upload_file(...)`, `list_files(**kwargs)`, `get_file_content(file_id)`, `delete_file(file_id, **kwargs)`.

**Common utilities (implemented in the base class, ready to use):**

- Type-safe conversion: `_as_float(value)`, `_as_int(value)` (tolerant of numbers returned as strings by the LLM, excluding `bool`).
- Validation: `validate_voice_id(...)` (length 8–256, first character, character set, and last-character constraints), `_count_text_chars(text)` (CJK/full-width/emoji count as 2), `validate_text_length(...)` (based on the above counting).
- Param handling: `validate_params(params) -> (bool, str)`, `sanitize_params(params) -> dict` (override in subclasses to implement concrete range/enum validation).

**Docs and metadata:**

- `DOCS_KEY` (optional class attribute): explicitly specifies which capability doc to reuse; falls back to `template_key` when absent.
- `docs_key` property, `_load_docs()`: reads the doc from `providers/docs/<docs_key>.md`.
- `get_docs_for_voice(voice)`: can dynamically select a doc by voice ID (e.g. `*_design.md` for designed voices).

### 5.2 Auto-Discovery and Factory (`providers/__init__.py`)

`ProviderFactory` implements "zero-configuration" pluggability:

- `_discover_adapters()`: scans `providers/*.py`, **skipping files that begin with an underscore and `base.py`**; dynamically imports them via `importlib`; collects concrete classes where `issubclass(obj, TTSProviderAdapter)` and `obj.__module__ == module.__name__` (the latter prevents the base class from being mistakenly registered under the wrong module name via multiple inheritance).
- `get_adapter(entry)`: uses `entry["__template_key"]` — the module file name without `.py` — as the mapping key; results are cached by class.

> `__template_key` is automatically injected by the AstrBot framework from the `template_list` config; the file name must match the `templates` key in the schema.

### 5.3 Common Base Class `BailianSpeechSynthesizerAdapter`

The shared base for Bailian-family adapters (`providers/_bailian_speech_synthesizer.py`, underscore-prefixed to avoid auto-discovery):

- Wraps the Alibaba Cloud Bailian SpeechSynthesizer endpoints, Bearer auth, request/response handling, and audio download.
- Driven by `MODEL_NAME` (e.g. `qwen-audio-3.0-tts`, `cosyvoice-v3.5`) and `VALID_LANGS`; subclasses only declare these two plus a few differences to wire in.
- Implements `get_tool_schema()` (`tts_enhance`: text/instruction/volume/rate/pitch/language_hints), `get_subagent_system_prompt()`, `call_api()`, `validate_params/sanitize_params`, `create_voice` (clone/design branches), `list_voice`, and `delete_voice`.
- `_extract_model_from_voice_id()`: parses `flash/plus` from a cloned voice ID to solve automatic model-version matching.
- Masks `api_key` in `entry` at initialization to avoid writing it into debug logs, and checks for conflicts between `model` and the value parsed from the voice ID.

Concrete Bailian adapters (e.g. `bailian_qwen_audio_3_0_tts.py`) are often just a few lines, declaring only differences such as `MODEL_NAME`.

### 5.4 Common Base Class `FishAudioAdapter`

The shared base for Fish Audio adapters (`providers/_fish_audio.py`, underscore-prefixed to avoid auto-discovery):

- Wraps `POST https://api.fish.audio/v1/tts`, Bearer authentication, and the `model` request header.
- Centralizes parameter validation/sanitization, proxies, text and language fields, `prosody` speed/volume, audio format and bitrate/sample-rate handling, sampling/chunk parameters, pronunciation-dictionary references, error handling, and audio persistence.
- `_resolve_model()`: a non-empty `MODEL_NAME` on a subclass returns that fixed model directly; S2 instead selects `s2.1-pro`, `s2.1-pro-free`, or `s2-pro` from config.
- `_resolve_reference_id()`: preview `voice_id` takes precedence; otherwise the single configured `reference_id` is used.
- `FishAudioS2Adapter` keeps the S2 tool schema and capability doc. `FishAudioDrama3Adapter` fixes `MODEL_NAME = "drama-3"`, disables `normalize_loudness` (S2-family only), and provides its own director-instruction tool schema and capability doc.

### 5.5 Capability Docs Mechanism

"Capability docs" are the basis on which the SubAgent intelligently generates params, and are stored at `providers/docs/<docs_key>.md`:

- Content should cover: a core parameter table (type/range/default), emotion tag / dialect / language enums, and usage examples.
- **Key section `## 你的任务`**: tells the SubAgent how to choose params based on context and how to call `tts_enhance`.
- Designed voices (which do not support dialects) use a separate `<docs_key>_design.md`, switched automatically by `get_docs_for_voice()` based on the voice ID.
- Providers using the same model can reuse one doc via the subclass `DOCS_KEY` (e.g. the Bailian MiniMax reuses the official MiniMax doc), avoiding redundant copies.

---

## 6. Multi-Provider Fallback and Persona Routing

`TTSService.synthesize()` provider selection strategy:

1. **Persona partitioning**: based on the current `persona_id`, split providers into `bound` (bound to that persona) and `unbound` (not bound), attempting `bound` first.
2. **Fallback semantics**: when all `bound` entries fail and `unbound` entries exist, log a Warning and fall back to the universal voice; when no voice is available at all, or a bound voice fails with no fallback, log a Warning and abandon this synthesis (return `None`).
3. **Intra-provider retry**: when SubAgent params are invalid or a tool execution throws, feed a structured `role:"tool"` tool result back to the LLM for a retry (up to 2 attempts built in); the final validation failure is cleaned up by `sanitize_params`; if tool exceptions are exhausted, fall back to plain-text synthesis (original text), and only switch to the next provider if that also fails.
4. **Plain-text fallback**: providers with enhancement disabled or missing docs synthesize directly as plain text, skipping the SubAgent.

---

## 7. SubAgent Enhancement Mechanism

Robustness design of the enhancement flow:

- **Structured output**: use `tts_enhance` Function Calling to have the model output a param object (text/instruction/volume/rate/pitch/language_hints, etc.) rather than free text.
- **Two-stage validation**: first `validate_params` (range/enum) → on final failure `sanitize_params` (discard invalid values, keep valid ones).
- **Context awareness**: inject the recent conversation and `persona` prompt into the SubAgent so that emotion / speed / language decisions fit the context.
- **Degradation chain**: tool call failure → text-parsing fallback → return `None` → the main flow switches provider or falls back to plain text.
- **No docs means plain text**: ensures a provider "missing capability docs" does not waste an LLM call.

---

## 8. Frontend Architecture (`pages/tts_studio/`)

The frontend is a **build-free** Vue 3 app:

- `index.html` loads the local `static/vue.global.prod.js` via `<script>` (UMD, works offline, no CDN dependency), and `app.js` is loaded with `type="module"`.
- `app.js`:
  - `bridge = window.AstrBotPluginPage`; all backend calls go through `bridge` (including `bridge.ready()`, `bridge.apiGet('providers')`, and `bridge.upload`), bypassing Pages' `asset_token` auth and cross-origin issues.
  - `componentMap`: maps `template_key` to the corresponding Vue component; `getDisplayName()` provides the Chinese labels.
  - Renders Tabs grouped by `template_key`; the current component is loaded dynamically via `<component :is>` and receives `entries / bridge / template-key`.
- **Component organization**:
  - `components/common/`: components shared across providers (`bailian_speech_synthesizer.js` for clone/design modes — clone audio is encoded by the browser as a Data URL before submission, `voice_preview_modal.js` preview modal, `delete_confirm_modal.js` delete confirmation).
  - `components/*.js`: thin wrappers per provider, referencing common components and configuring differences via `providerConfig` (language list, help links, whether system voices are supported, etc.).
  - `composables/`: `useAudioManager` (global audio singleton/volume), `useTextValidator` (Chinese character = 2 counting and validation), `useClipboard`, and `useToast`.
- Styles are centralized in `style.css`; the frontend has no build step or ESLint config, so no npm toolchain is required.
- **Configurable background image**: the management page supports uploading a single background image via the config item `page_background` (file type); the backend `/<plugin>/page-background` route reads the image as a base64 Data URL (avoiding binary bridging and cross-origin/external links); the frontend `applyPageBackground()` only renders the fixed `#page-bg` background layer when `data_url` is non-empty, applying opacity and blur per `page_background_opacity` / `page_background_blur`. Content cards and form fields are made semi-transparent/frosted so the background shows through.
- **Floating-layer architecture (modals / Toast / volume bar)**: the global volume bar, all modal overlays, and notification toasts are mounted under `body` via `<Teleport to="body">` (fixed + `100vw/100vh`). Page-level fade-in animations use `animation-fill-mode: both`, which leaves two kinds of persistent side effects on ancestor elements after completion — a compositor transform (the computed transform is an identity matrix rather than `none`, becoming the containing block for `position: fixed` descendants) and a compositing layer (i.e. a stacking context, locking z-index within the subtree); teleporting to `body` is immune to both, and new floating layers should follow this pattern.
- **Animation conventions**: one-shot enter/leave animations (modals, page/tab entry) always use `<Transition>` — animation classes are removed once finished, leaving no residue; continuous transitions (tab highlight bar) use transform compositor animations + `will-change` to avoid per-frame layout. All are disabled under `@media (prefers-reduced-motion: reduce)`.

> Design trade-off: only fill the management gap for providers that "have an API but no UI"; providers with an official console link out directly rather than reimplementing.

---

## 9. Configuration System (`_conf_schema.json`)

Top-level config items:

| Config item | Type | Default | Description |
|--------|------|------|------|
| `enable_enhance` | bool | true | Enable SubAgent param enhancement |
| `enhance_llm_provider` | string (`select_provider`) | "" | Enhancement model; blank uses the current session model |
| `context_window` | int | 10 | SubAgent context window (in user message count) |
| `dual_output` | bool | false | Output both text and voice |
| `tts_prompt` | text | trigger prompt | TTS trigger instructions injected into the main model |
| `page_background` | file | [] | Management page background image (blank = hidden) |
| `page_background_opacity` | float | 0.5 | Background opacity (0~1; only applies when a background image is set) |
| `page_background_blur` | int | 0 | Background blur (0~30px; only applies when a background image is set) |
| `providers` | `template_list` | — | Provider list (supports multiple entries with fallback) |

`providers` is a `template_list`: each template contains `name`/`hint`/`display_item`/`items`. `items` supports `_special` (`select_provider`/`select_persona`), `secret: true` (masked password field), `options`, and `condition` (conditional display based on other field values, e.g. MiMo switches voice/design/clone fields by `model`). The framework injects `__template_key` into each entry.

---

## 10. Security Design

- **File ID whitelist**: `_SAFE_FILE_ID_RE = ^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$`; the first character is restricted so that `.`/`..`/`.env` etc. are excluded; dots are allowed (since real file names look like `upload_<ts>.mp3`), but `/` and `\` are always excluded.
- **Path traversal second line of defense**: `_resolve_uploads_path()` compares the parent directory after `Path.resolve()` to ensure the resolved result does not escape `uploads`.
- **Route param validation**: `_parse_entry_id()` validates the type (excluding `bool`) and bounds; invalid values return `None` → 404.
- **Upload extension whitelist**: `upload_file` only allows `wav/mp3/m4a/aac/ogg/flac`; abnormal suffixes never reach disk.
- **API Key masking**: both `/providers` and adapter initialization mask `api_key` as `***** + last 5 chars` to avoid leaking it in logs.
- **Audio submission method**: voice-clone audio is encoded into a Data URL (Base64) in the browser by the management page and submitted directly to the create endpoint, exposing neither a public URL nor an internal listening port.

---

## 11. Data Directory and Persistence

Plugin data root: `get_astrbot_data_path() / "plugin_data" / <plugin_name>`, with the following subdirectories:

- `uploads/`: user-uploaded reference/clone audio (`upload_<millisecond timestamp>.<ext>`).
- `audio/`: synthesis outputs (`tts_<timestamp>.<fmt>`), injected into adapters via `_data_dir`.
- `cache/mimo_voiceclone/`: base64 pre-encoding cache for MiMo audio-clone samples (the key includes mtime/size and is auto-invalidated on change).

KV storage (`/kv/*`) is provided by the AstrBot framework for the frontend/adapters to save metadata (e.g. MiniMax's inactive voice list `bailian_minimax_unactivated_list`, clone `prompt_text`, etc.).

> **Persistence principle**: all plugin runtime data is written under `plugin_data/`, never into the plugin's own directory (to avoid loss on update/reinstall).
