<div align="center">
  <img src="../../logo.png" alt="TTS Enhancer" width="200"/>
</div>

[中文](../../README.md) · [Русский](../ru/README.md) · [日本語](../ja/README.md) · English

# AstrBot TTS Enhancer

> **Let AstrBot's replies carry natural emotion, dialect, and a personalized voice —**
> closing the gap between "plain-text input" and the rich capabilities of modern TTS providers, with a highly pluggable architecture for wiring in any speech service.

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-blueviolet)](https://github.com/AstrBotDevs/AstrBot)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](../../LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v1.7.0-green)](../../CHANGELOG.md)

---

## Why TTS Enhancer?

AstrBot by default can only pass plain text to the LLM. But modern TTS services are no longer content with "reading text" — they support volume, intonation and speed control, even emotion tags, multilingual and dialect support, voice cloning, and voice design…

The traditional calling style can only throw a single `text` parameter at them, wasting all those capabilities. Worse, many providers only ship an API with no easy-to-use UI for managing cloned voices and designs.

**TTS Enhancer exists for exactly this imbalance:**

- **Highly pluggable multi-provider architecture** — each provider is an independent adapter that never interferes with others.
- **Capability docs mechanism** — each provider ships a Markdown document describing its supported parameters and usage; the SubAgent uses it to intelligently generate optimal parameters.
- **On-demand frontend UI** — reusable management components for providers lacking a web console; providers with an official console can include console/resource links without reimplementing that console.

---

## Core Design

### 1️⃣ Multi-Provider Adapters

Each TTS provider only needs to subclass `TTSProviderAdapter` (or an existing common base such as `BailianSpeechSynthesizerAdapter` or `FishAudioAdapter`) and implement:

- `get_tool_schema()` → defines the Function Calling parameter structure
- `get_subagent_system_prompt()` → injects the capability doc into the SubAgent
- `call_api()` → calls the real API
- Voice management (optional) → implement only the supported operations: `create_voice()`, `query_voice()`, `list_voice()`, `delete_voice()`. Seed TTS 3.0 provides create/query plus the shared preview route, with no list or delete operation.

One Python adapter plus one Markdown capability doc enables adapter discovery. Complete provider integration also requires a `_conf_schema.json` template, synchronized four-language i18n, tests, and, when custom UI is needed, frontend component registration in `componentMap`.

### 2️⃣ Capability Docs

Each provider ships a `providers/docs/{template_key}.md` document detailing:

- Which parameters it supports (`instruction`, `volume`, `rate`, `pitch`, `language_hints`…)
- Emotion tag lists, dialect lists, usage examples
- Parameter ranges and defaults

The SubAgent **reads this document dynamically** at synthesis time and generates provider-compliant parameters based on conversation context — never overstepping boundaries.

### 3️⃣ Frontend: reusable components + on-demand customization

The plugin provides **reusable frontend components** (`components/common/`) for standard voice-management interactions, plus provider-specific components (`components/`):

- `bailian_speech_synthesizer.js` — clone / design modes (clone audio is encoded as a Data URL in the browser), preview, listing, deletion
- `voice_preview_modal.js` — voice preview modal with listen / keep / delete
- `delete_confirm_modal.js` — delete confirmation modal (avoids `confirm()` being blocked in sandboxes)
- `volcengine_seed_tts_3_0.js` — Seed TTS 3.0 manual cloning, single-voice status queries, slot-billing guidance, and official resource links

Custom interactions per provider are also supported (e.g. MiniMax's "inactive → preview → activate" three-step flow).

Shared logic is extracted into `composables/`:

- `useAudioManager.js` — global audio playback singleton
- `useTextValidator.js` — text length validation (CJK char = 2 units)
- `useClipboard.js` — clipboard operations
- `useToast.js` — notifications

Page-level interaction details:

- **Global volume bar** — a fixed top bar that stays adjustable while a modal is open (tweak volume during preview without closing the modal)
- **Enter/leave animations** — page and tab fade-ins, modal and toast pop-in/out; all disabled under `prefers-reduced-motion`
- **Floating-layer architecture** — modal overlays and toasts are always teleported to `body` and sized with `vw/vh`, immune to the containing-block / stacking side effects of page-level animations

Per provider:

- **Display names** come from the backend adapter's `DISPLAY_NAME`, not a frontend label map.
- **Tab visibility** comes from backend `capabilities.voice_management`; `ui_component` identifies the frontend component by the `template_key` convention, and `componentMap` resolves the actual Vue component. Any provider with voice management must register its component there.
- **Needs standard management UI** → reuse common components and keep provider-specific options in the component.
- **Has special interaction needs** → write a dedicated custom component (e.g. MiniMax audio list or hex decoding).
- **Seed TTS 3.0** uses a custom clone/query/preview component plus official voice-list and design-console links. An official console may be linked from a provider component; it does not replace required plugin UI automatically.

> The design intent: **fill the management gap for providers that only have an API and no UI**, rather than forcing uniformity.

---

## Supported Providers

| Provider | Model | Emotion | System Voice | Clone | Design | Dialect | Languages | LaTeX |
|---|---|---|---|---|---|---|---|---|
| **Bailian Qwen Audio 3.0 TTS** | Flash / Plus | Rich tags + NL instruction | ✅ | ✅ | ✅ | 21 | 16 | ✅ |
| **Bailian Qwen Audio 3.1 TTS** | Flash / Plus | Rich tags + NL instruction | ✅ | ✅ | ✅ | 21 | 16 | ✅ |
| **Bailian CosyVoice v3.5** | Flash / Plus | NL instruction | ❌ | ✅ | ✅ | 17 | 11 | ✅ |
| **MiniMax Speech 2.8** | HD / Turbo | Inline interjections | ✅ | ✅ | ✅ | Cantonese | 39 | ✅ |
| **Bailian MiniMax Speech 2.8** | HD / Turbo | Inline interjections | ✅ | ✅ | ✅ | Cantonese | 39 | ✅ |
| **Xiaomi MiMo V2.5 TTS** | Preset / Text-design / Audio-clone | Rich tags + NL instruction | ✅ | ✅ | ✅ | ✅ | Mostly zh | ❌ |
| **Google Gemini 3.8 Flash TTS** | Flash / Flash-Lite | NL style + inline vocal tags (`<laugh>`, `<sigh>`) | ✅ | ✅ | ✅ | ❌ | Multilingual | ❌ |
| **Fish Audio S2 Family** | s2.1-pro / s2.1-pro-free / s2-pro | Bracket emotions / free-form descriptions (71 reference tags, switch across sentences) | ✅ | ✅ | ❌ | ❌ | 13 | ❌ |
| **Fish Audio Drama 3** | drama-3 (fixed) | Natural-language direction + sound/pause cues + 7 scoped tags | ✅ | ✅ | ❌ | ❌ | Multilingual | ❌ |
| **Eleven v4** | v4 / v4 Turbo | Bracket emotion tags + `/IPA/` pronunciation + `<break>` pause | ✅ | ✅ | ✅ | Cantonese | 90 | ❌ |
| **StepFun StepAudio 3 TTS** | stepaudio-3-tts | `instruction` + inline `()` directives | ✅ | ✅ | ❌ | ❌ | Mostly zh | ❌ |
| **Volcengine Seed TTS 3.0** | doubao-seed-tts-3.0 (fixed) | Inline Tags + natural-language instructions | ✅ | ✅ | ✅ (official console) | 16 | 119 + auto | ❌ |
| **Bailian Qwen Audio 3.1 TTS Next** | qwen-audio-3.1-tts-next | Natural-language scene description (voice / emotion / effects) | ❌ | ❌ | ❌ | ❌ | Chinese, English | ❌ |

> StepFun's cloned voices are **read-only preview** (clone in the official playground and they appear automatically); voice design is done at the official studio — the plugin performs no write operations.

> Seed TTS 3.0 reuses an existing account slot when an existing voice ID is supplied. A custom voice ID is a postpaid slot whose fee is charged on the first formal synthesis. The plugin supports manual cloning and single-voice status queries, while voice design opens the official console. Purchased Mega voice-slot listing is not integrated because it uses different OpenAPI authentication.

> Xiaomi MiMo V2.5 clone samples (under 10MB Base64-encoded) are **trimmed automatically** with a notice when over the limit, rather than rejected; they share the same cache mechanism as Bailian audio generation.

### About Bailian Audio Generation (different from other providers)

`qwen-audio-3.1-tts-next` is not a traditional TTS — it is **audio generation**: a single call produces speech, sound effects and ambience together, enabling complete sound scenes (narration, radio drama, game lines, etc.). Its usage cannot be fully captured by the table above, so note:

- **The input is a prompt, not a line of text**: the `tts_enhance` tool's main field is `text_prompt`, where the SubAgent writes both "what to say" and "how / in what scene to say it" in one description. `volume` / `rate` are filled only when the user explicitly asks for an overall adjustment.
- **Single speaker**: this adapter exposes single-speaker mode only; multi-character orchestration is not exposed even though the model supports it.
- **Reference audio lives in config**: upload a reference sample via the `type: file` field in the provider config (wav/mp3/ogg, up to 30 s and 10 MB Base64-encoded). It determines the voice — **there is no system voice list and no voice clone / design management page**. The SubAgent receives different writing guidance depending on whether a sample is set: use `@voice1` to refer to the speaker when one is present; otherwise describe the speaker's identity and timbre in words.
- **Oversized samples are handled automatically**: an over-long or over-large reference sample is trimmed with a notice instead of failing the request.
- **Audio quality**: `format` / `sample_rate` / `channels` and MP3 bitrate / quality options are set in config; `seed = -1` generates a new random value each time.

> Multiple providers can be **configured simultaneously and fall back by `priority`**; each entry can also bind to a specific persona via `persona_id`, enabling "different personas use different voices".

More providers (Edge TTS, GPT-SoVITS, etc.) are planned — community contributions welcome!

---

## Synthesis Records (optional)

The plugin persists every TTS synthesis result (chat voice / voice preview / design audition / Agent-sent, etc.) as a "synthesis record". From the unified management page (`pages/tts_studio`) you can replay them, inspect metadata (source / provider / time / text / format / duration / size / enhanced params), and delete individual records or clear them all.

- **Storage layering (per AstrBot convention)**: metadata goes to the official KV (auto-isolated by plugin namespace, single key `synthesis_index`); audio binaries land in `plugin_data/synthesis_records/` and stay out of KV.
- **Retention policy** is controlled by the `synthesis_record_max` config: `0` or negative disables persistence; a positive integer keeps only the latest N records, evicting the oldest (and its audio file) beyond the limit. Unlimited retention is **not** supported (to avoid filling the disk without bound).

## Long-term Memory Retrieval (LivingMemory, optional)

If the same AstrBot instance has the LivingMemory plugin installed and enabled, and a vector embedding model is configured, TTS Enhancer can recall related long-term memories before synthesis and inject them into the SubAgent as a reference for judging speech style (e.g. the user's stable voice preferences or conversation background), giving the voice a sense of "memory".

- `memory_retrieval_top_k`: number of memories to recall; `0` = disabled (default).
- `memory_retrieval_query_strategy`: query source. `user_message` uses the text to synthesize; `prefix` uses a fixed prefix (avoids feeding unrelated synthesis text into retrieval and pulling in noise).
- `memory_retrieval_prefix`: fixed retrieval prefix, shown and used only under the `prefix` strategy.
- Fully graceful degradation: when LivingMemory is disabled, the Embedding Provider is missing, or a call fails, retrieval is silently skipped without affecting TTS synthesis.

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
# ---- Long-term memory retrieval (LivingMemory, optional) ----
memory_retrieval_top_k: 0         # Recall count (0 = disabled)
memory_retrieval_query_strategy: "user_message"  # Query source: user_message / prefix
memory_retrieval_prefix: "User voice preference"  # Fixed prefix (only used under prefix strategy)
page_background: []               # Management page background image (file type; blank = hidden)
page_background_opacity: 0.5       # Background opacity (0~1; only applies when an image is set)
page_background_blur: 0            # Background blur (0~30px; only applies when an image is set)
synthesis_record_max: 50           # Max synthesis records to keep (0 or negative = off; positive integer = keep latest N; unlimited not supported)
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
│   - GoogleGemini3_8FlashTTSAdapter                          │
│   - FishAudioS2Adapter                                      │
│   - FishAudioDrama3Adapter                                  │
│   - ElevenLabsV4Adapter                                     │
│   - StepfunStepaudio3TtsAdapter                             │
│   - VolcengineSeedTts30Adapter                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Contributing

Adding a new TTS provider is easy:

1. **Write the adapter**: create `<template_key>.py` under `providers/`, subclassing `TTSProviderAdapter` or an existing common base, and declare `DISPLAY_NAME`.
2. **Write the capability doc**: create `providers/docs/<docs_key>.md` describing parameters, tags, and examples, including the required `## 你的任务` section.
3. **Add a config template**: extend `_conf_schema.json` with the provider's config items.
4. **Synchronize i18n (mandatory)**: update `.astrbot-plugin/i18n/zh-CN.json`, `en-US.json`, `ja-JP.json`, and `ru-RU.json` together.
5. **Frontend (on demand)**:
   - Set backend `capabilities.voice_management` through the voice-management capability contract; do not hardcode frontend visibility.
   - For custom UI, create a Vue component under `pages/tts_studio/components/`, reuse `components/common/`, and register the mapping in `componentMap` in `app.js`.
   - Include official console/resource links where useful; an external link alone is not component registration.
6. **Add tests**: cover the adapter, routes/contracts, and any custom frontend behavior under `tests/`.

Adapter discovery is automatic, but complete integration still requires the schema, all four i18n locales, tests, and `componentMap` registration for custom UI.

---

## Documentation

- [CHANGELOG](../../CHANGELOG.md) — full version history.
- **Architecture doc** [ARCHITECTURE.md](ARCHITECTURE.md) — design goals, layering, request lifecycle, core modules, adapter system, persona routing, security.
- **Development guide** [DEVELOPMENT.md](DEVELOPMENT.md) — environment setup, provider checklist, adapter development, frontend, testing, release flow.
- **Known limitations & upstream responsibility** [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — design trade-offs / upstream guarantees / handling of unreachable items & green-test guards.
- Other READMEs: [中文](../../README.md) · [Русский](../ru/README.md) · [日本語](../ja/README.md).
- Capability doc examples:
  - `providers/docs/bailian_qwen_audio_3_0_tts.md`
  - `providers/docs/bailian_qwen_audio_3_1_tts.md`
  - `providers/docs/bailian_cosyvoice_v3_5.md`
  - `providers/docs/minimax_speech_2_8.md`
  - `providers/docs/mimo_v2_5_tts.md`
  - `providers/docs/mimo_v2_5_tts_preset.md`
  - [Fish Audio S2 capability guide](../../providers/docs/fish_audio_s2.md)
  - [Fish Audio Drama 3 capability guide](../../providers/docs/fish_audio_drama_3.md)
  - [Volcengine Seed TTS 3.0 capability guide](../../providers/docs/volcengine_seed_tts_3_0.md)

## License

GNU Affero General Public License v3.0 — see [LICENSE](../../LICENSE).
