[中文](../../README.md) · English

# AstrBot TTS Enhancer

> **Let AstrBot's replies carry natural emotion, dialect, and a personalized voice —**
> closing the gap between "plain-text input" and the rich capabilities of modern TTS providers, with a highly pluggable architecture for wiring in any speech service.

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-blueviolet)](https://github.com/AstrBotDevs/AstrBot)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.3.8-green)](../../CHANGELOG.md)

---

## Why TTS Enhancer?

AstrBot by default can only pass plain text to the LLM. But modern TTS services are no longer content with "reading text" — they support volume, intonation and speed control, even emotion tags, multilingual and dialect support, voice cloning, and voice design…

The traditional calling style can only throw a single `text` parameter at them, wasting all those capabilities. Worse, many providers only ship an API with no easy-to-use UI for managing cloned voices and designs.

**TTS Enhancer exists for exactly this imbalance:**

- **Highly pluggable multi-provider architecture** — each provider is an independent adapter that never interferes with others.
- **Capability docs mechanism** — each provider ships a Markdown document describing its supported parameters and usage; the SubAgent uses it to intelligently generate optimal parameters.
- **On-demand frontend UI** — reusable management components for providers lacking a web console; providers with an official console can simply link out, with no need to re-implement.

---

## Core Design

### 1️⃣ Multi-Provider Adapters

Each TTS provider only needs to subclass `TTSProviderAdapter` (or an existing common base such as `BailianSpeechSynthesizerAdapter`) and implement:

- `get_tool_schema()` → defines the Function Calling parameter structure
- `get_subagent_system_prompt()` → injects the capability doc into the SubAgent
- `call_api()` → calls the real API
- `create_voice() / list_voice() / delete_voice()` → voice management

Adding a provider means writing one Python file plus one Markdown doc — the plugin discovers it automatically.

### 2️⃣ Capability Docs

Each provider ships a `providers/docs/{template_key}.md` document detailing:

- Which parameters it supports (`instruction`, `volume`, `rate`, `pitch`, `language_hints`…)
- Emotion tag lists, dialect lists, usage examples
- Parameter ranges and defaults

The SubAgent **reads this document dynamically** at synthesis time and generates provider-compliant parameters based on conversation context — never overstepping boundaries.

### 3️⃣ Frontend: reusable components + on-demand customization

The plugin provides **reusable frontend components** (`components/common/`) that encapsulate the standard voice-management interactions:

- `bailian_speech_synthesizer.js` — clone / design modes (clone audio is encoded as a Data URL in the browser), preview, listing, deletion
- `voice_preview_modal.js` — voice preview modal with listen / keep / delete
- `delete_confirm_modal.js` — delete confirmation modal (avoids `confirm()` being blocked in sandboxes)

Custom interactions per provider are also supported (e.g. MiniMax's "inactive → preview → activate" three-step flow).

Shared logic is extracted into `composables/`:

- `useAudioManager.js` — global audio playback singleton
- `useTextValidator.js` — text length validation (CJK char = 2 units)
- `useClipboard.js` — clipboard operations
- `useToast.js` — notifications

Per provider:

- **Needs a UI** → reuse common components + a thin customization; just register and configure `providerConfig` (language list, help links, etc.) in `app.js`.
- **Already has an official console** → configure an external link only; no reimplementation needed.
- **Has special interaction needs** → write a dedicated custom component (e.g. MiniMax audio list, hex decoding).

> The design intent: **fill the management gap for providers that only have an API and no UI**, rather than forcing uniformity.

---

## Supported Providers

| Provider | Model | Emotion | System Voice | Clone | Design | Dialect | Languages | LaTeX |
|---|---|---|---|---|---|---|---|---|
| **Bailian Qwen Audio 3.0 TTS** | Flash / Plus | Rich tags + NL instruction | ✅ | ✅ | ✅ | 21 | 16 | ❌ |
| **Bailian Qwen Audio 3.1 TTS** | Flash | Rich tags + NL instruction | ✅ | ✅ | ✅ | 21 | 16 | ❌ |
| **Bailian CosyVoice v3.5** | Flash / Plus | NL instruction | ❌ | ✅ | ✅ | 17 | 11 | ✅ |
| **MiniMax Speech 2.8** | HD / Turbo | Inline interjections | ✅ | ✅ | ✅ | Cantonese | 39 | ✅ |
| **Bailian MiniMax Speech 2.8** | HD / Turbo | Inline interjections | ✅ | ✅ | ✅ | Cantonese | 39 | ✅ |
| **Xiaomi MiMo V2.5 TTS** | Preset / Text-design / Audio-clone | Rich tags + NL instruction | ✅ | ✅ | ✅ | ✅ | Mostly zh | ❌ |

> Multiple providers can be **configured simultaneously and fall back by `priority`**; each entry can also bind to a specific persona via `persona_id`, enabling "different personas use different voices".

More providers (Edge TTS, GPT-SoVITS, etc.) are planned — community contributions welcome!

---

## Quick Start

1. **Install the plugin** — search and install from the AstrBot plugin marketplace.
2. **Configure a provider** — plugin config → add at least one provider.
3. **Make the model emit `<tts>` tags** — the main model wraps `<tts>text to synthesize</tts>` in its reply; the plugin handles it automatically and sends a voice message.
4. **Use the Tool** — the plugin registers the `send_voice_to_user` tool so the model can decide when to send voice proactively, without tags.

---

## Configuration (abridged)

```yaml
enable_enhance: true              # Enable SubAgent auto-enhancement
enhance_llm_provider: ""          # Model used for enhancement (a cheaper/free model is fine)
context_window: 10                # Context window (in turns)
dual_output: false                # Output both text and voice
log_enhanced_params: false        # Log generated parameters
page_background: []               # Management page background image (file type; blank = hidden)
page_background_opacity: 0.5       # Background opacity (0~1; only applies when an image is set)
page_background_blur: 0            # Background blur (0~30px; only applies when an image is set)
providers:                        # Provider list (multiple, with fallback)
  - __template_key: bailian_qwen_audio_3_0_tts
    display_name: "My Voice"
    priority: 0
    persona_id: ""                # Bind to a persona (optional; blank = universal fallback)
    api_key: "sk-..."
    workspace_id: "ws-..."
    model: "flash"
    voice: "longanhuan_v3.6"
    timeout: 60
```

See the help text in the plugin config page for the full list of configuration items.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ [Main Model]  outputs "<tts>Nice weather today</tts>"         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [TTS Enhancer Plugin]                                        │
│   1. Parse <tts> tags                                        │
│   2. Fetch recent context (window size configurable)         │
│   3. Build SubAgent prompt (with provider capability docs)    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [SubAgent]  calls tts_enhance tool                           │
│   outputs structured params: { text, instruction, volume,    │
│     rate, pitch, language_hints }                            │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [Provider Adapter]  validate → call API → download audio     │
│   - BailianQwenAudio3_0TTSAdapter                           │
│   - BailianQwenAudio3_1TTSAdapter                           │
│   - BailianCosyVoiceV3_5Adapter                             │
│   - MinimaxSpeech2_8Adapter                                 │
│   - BailianMinimaxSpeech2_8Adapter                          │
│   - MimoV2_5TTSAdapter                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Contributing

Adding a new TTS provider is easy:

1. **Write the adapter**: create `<vendor>_<model>.py` under `providers/`, subclassing `TTSProviderAdapter` or an existing common base.
2. **Write the capability doc**: create `providers/docs/<template_key>.md` describing parameters, tags, and examples in detail.
3. **Frontend (on demand)**:
   - Needs a UI: create a Vue component under `pages/tts_manager/components/`, reuse `components/common/` and configure `providerConfig`; register the mapping in `app.js`.
   - Has an official console: just configure an external link in `app.js`.
   - Has special interaction needs (e.g. MiniMax's "inactive → preview → activate" flow): write a dedicated custom component.
4. **Add a config template**: extend `_conf_schema.json` with the provider's config items.

All new providers are auto-discovered and loaded by the factory — no core code changes required.

---

## Documentation

- [中文架构文档](../../docs/zh/ARCHITECTURE.md) — system design, data flow, module breakdown, security.
- [中文开发指南](../../docs/zh/DEVELOPMENT.md) — how to add a provider, frontend, and tests.
- [CHANGELOG](../../CHANGELOG.md) — full version history.
- Capability doc examples: `providers/docs/*.md`.

## License

GNU Affero General Public License v3.0 — see [LICENSE](../../LICENSE).
</content>
</invoke>
