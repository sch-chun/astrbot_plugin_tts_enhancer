<div align="center">
  <img src="../../logo.png" alt="TTS Enhancer" width="200"/>
</div>

[中文](../../README.md) · [English](../en/README.md) · [Русский](../ru/README.md) · 日本語

# AstrBot TTS Enhancer

> **AstrBot の返信に、自然な感情・方言・パーソナライズされた声を。**  
> 「従来のテキスト入力」と「TTS プロバイダーの豊富な機能」の間のアンバランスを解消し、高い拡張性を持つアーキテクチャで任意の音声サービスを容易に組み込みます。

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-blueviolet)](https://github.com/AstrBotDevs/AstrBot)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](../../LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v1.6.0-green)](../../CHANGELOG.md)

---

## なぜ必要か？

AstrBot はデフォルトでは LLM にテキストしか渡せません。しかし現代の TTS サービスはもはや「テキストを読み上げる」だけでは満足しません——音量、抑揚や話速の調整、さらには感情タグ、多言語・方言、ボイスクローニング、サウンドデザインなどをサポートしています。

従来の呼び出し方では `text` パラメータを 1 つ投げ込むだけであり、これらの機能はすべて無駄になっていました。さらに厄介なことに、多くのプロバイダーは API のみを提供し、ボイスクローンやデザインを管理するための使いやすい UI がありません。

**TTS Enhancer は、このような「アンバランス」のために生まれました：**

- **高い拡張性を持つマルチプロバイダーアーキテクチャ** – 各プロバイダーは独立したアダプターとして実装され、互いに干渉しません。
- **ケイパビリティドキュメント（Capability Docs）の仕組み** – 各プロバイダーに、サポートするパラメータと使い方を記述した Markdown ドキュメントが付属し、SubAgent はそれに基づいて最適なパラメータをインテリジェントに生成します。
- **オンデマンドなフロントエンド UI** – Web UI のないプロバイダー向けに再利用可能な管理コンポーネントを提供します。公式コンソールを持つプロバイダーは外部リンクを設定するだけで、重複実装は不要です。

---

## コアデザイン

### 1️⃣ マルチプロバイダーアダプター（Provider Adapter）

各 TTS プロバイダーは `TTSProviderAdapter` 抽象クラス（または既存の `BailianSpeechSynthesizerAdapter`、`FishAudioAdapter` などの共通基底クラス）を継承し、以下を実装するだけです：

- `get_tool_schema()` → Function Calling のパラメータ構造を定義
- `get_subagent_system_prompt()` → ケイパビリティドキュメントを SubAgent に注入
- `call_api()` → 実際の API を呼び出す
- `create_voice() / list_voice() / delete_voice()` → ボイス管理

プロバイダーを追加するには、Python ファイル 1 つと Markdown ドキュメント 1 つを書くだけで、プラグインが自動的に検出します。

### 2️⃣ ケイパビリティドキュメント（Capability Docs）

各プロバイダーには `providers/docs/{template_key}.md` ドキュメントが付属し、以下を詳しく説明します：

- サポートするパラメータ（`instruction`, `volume`, `rate`, `pitch`, `language_hints`……）
- 感情タグ一覧、方言一覧、使用例
- パラメータの範囲とデフォルト値

SubAgent は合成時に**このドキュメントを動的に読み取り**、会話のコンテキストに基づいてそのプロバイダーの機能に適合したパラメータを生成します。決して範囲を逸脱しません。

### 3️⃣ フロントエンド UI：再利用可能なコンポーネント + オンデマンドなカスタマイズ

プラグインは、**再利用可能なフロントエンドコンポーネント**（`components/common/`）を提供し、ボイス管理の標準的な操作フローをカプセル化しています：

- `bailian_speech_synthesizer.js` – ボイスクローン / サウンドデザインの 2 モード、試聴、一覧、削除
- `voice_preview_modal.js` – ボイスプレビューのモーダル。試聴と保持 / 削除に対応
- `delete_confirm_modal.js` – 削除確認モーダル。サンドボックス環境で `confirm()` がブロックされるのを回避

さらに各プロバイダーごとの**カスタム操作**（例：MiniMax の「未アクティベート音色 → プレビュー → アクティベート決定」の 3 段階フロー）にも対応しています。

共通ロジックは `composables/` に抽出されています：

- `useAudioManager.js` – グローバルな音声再生制御のシングルトン
- `useTextValidator.js` – テキストの文字数チェック（漢字 = 2 文字）
- `useClipboard.js` – クリップボード操作
- `useToast.js` – 通知トースト

ページレベルの操作の詳細：

- **グローバル音量バー** – 固定のトップバー。モーダルを開いている間も音量調整が可能で、モーダルを閉じずに試聴できます
- **出入りアニメーション** – ページ / タブのフェードイン、モーダルとトーストの軽やかなポップイン / アウト。`prefers-reduced-motion` 下ではすべて無効化
- **フローティングレイヤーアーキテクチャ** – モーダルのオーバーレイとトーストは常に body へ Teleport され、`vw/vh` で全画面表示。ページアニメーションの包含ブロック / 重ね合わせの副作用の影響を受けません

各プロバイダーごとに：

- **UI が必要** → 共通コンポーネントを再利用してカスタム拡張。`app.js` で登録し、`providerConfig`（言語一覧、ヘルプリンクなど）を設定するだけ
- **公式 Web コンソールあり** → 外部リンクを設定するだけ。重複実装は不要
- **特殊な操作ニーズあり** → 専用のカスタムコンポーネントを個別に作成（例：MiniMax の音声一覧、Hex デコードなど）

> この設計の狙いは、**API のみで UI のないプロバイダーの管理体験を補完すること**であり、強制的な統一ではありません。

---

## サポートするプロバイダー

| プロバイダー | モデル | 感情制御 | システムボイス | クローン | デザイン | 方言 | 言語 | LaTeX |
|---|---|---|---|---|---|---|---|---|
| **Bailian Qwen Audio 3.0 TTS** | Flash / Plus | 豊富なタグ + 自然言語指示 | ✅ | ✅ | ✅ | 21 種 | 16 種 | ✅ |
| **Bailian Qwen Audio 3.1 TTS** | Flash / Plus | 豊富なタグ + 自然言語指示 | ✅ | ✅ | ✅ | 21 種 | 16 種 | ✅ |
| **Bailian CosyVoice v3.5** | Flash / Plus | 自然言語指示 | ❌ | ✅ | ✅ | 17 種 | 11 種 | ✅ |
| **MiniMax Speech 2.8** | HD / Turbo | テキスト内の間投詞 | ✅ | ✅ | ✅ | 広東語 | 39 種 | ✅ |
| **Bailian MiniMax Speech 2.8** | HD / Turbo | テキスト内の間投詞 | ✅ | ✅ | ✅ | 広東語 | 39 種 | ✅ |
| **Xiaomi MiMo V2.5 TTS** | プリセット音色 / テキストデザイン / 音声クローン | 豊富なタグ + 自然言語指示 | ✅ | ✅ | ✅ | ✅ | 中国語中心 | ❌ |
| **Google Gemini 3.8 Flash TTS** | Flash / Flash-Lite | 自然言語スタイル + テキスト内の発声マーカー（`<laugh>`、`<sigh>`） | ✅ | ✅ | ✅ | ❌ | 多言語 | ❌ |
| **Fish Audio S2 Family** | s2.1-pro / s2.1-pro-free / s2-pro | 角括弧の感情・自然言語記述（71 個の参考タグ、文をまたいで切替） | ✅ | ✅ | ❌ | ❌ | 13 種 | ❌ |
| **Fish Audio Drama 3** | drama-3（固定） | 自然言語の演技指示 + 効果音・間 + 7 個の部分指定タグ | ✅ | ✅ | ❌ | ❌ | 多言語 | ❌ |
| **Eleven v4** | v4 / v4 Turbo | 角括弧の感情タグ + `/IPA/` 発音 + `<break>` による一時停止 | ✅ | ✅ | ✅ | 広東語 | 90 種 | ❌ |
| **StepFun StepAudio 3 TTS** | stepaudio-3-tts | `instruction` + テキスト内の `()` 指示 | ✅ | ✅ | ❌ | ❌ | 中国語中心 | ❌ |
| **Bailian Qwen Audio 3.1 TTS Next** | qwen-audio-3.1-tts-next | 自然言語によるシーン記述（声質 / 感情 / 効果音） | ❌ | ❌ | ❌ | ❌ | 中国語、英語 | ❌ |

> StepFun のクローン音色は**読み取り専用プレビュー**です（公式プレイグラウンドでクローンすると自動的に一覧表示）。音色デザインは公式スタジオで行い、プラグイン内では書き込み操作を行いません。

> Xiaomi MiMo V2.5 のクローン用サンプル（Base64 後 10MB 以下）は、超過時に**自動的に切り詰められ通知**されます（エラーにはなりません）。百錬の音声生成と同じキャッシュ機構を共有しています。

### 百錬の音声生成について（他のプロバイダーと異なる点）

`qwen-audio-3.1-tts-next` は従来の TTS ではなく**音声生成**です。1 回のリクエストで音声・効果音・環境音をまとめて生成し、完全なサウンドシーン（ナレーション、ラジオドラマ、ゲームのセリフなど）を構築できます。そのため上の表では特徴を伝えきれない部分があります。

- **入力はセリフではなくプロンプト**：`tts_enhance` ツールのメイン項目は `text_prompt` で、SubAgent が「何を話すか」と「どう／どのような場面で話すか」を一つの記述にまとめます。`volume` / `rate` はユーザーが明示的に調整を求めた場合のみ入力します。
- **単一話者**：このアダプターは単一話者モードのみを提供します。モデルは複数話者に対応していますが、複数キャラクターの演出は公開していません。
- **参照音声は設定項目で管理**：プロバイダー設定の `type: file` 項目から参照音声をアップロードします（wav/mp3/ogg、最長 30 秒、Base64 後 10MB 以下）。これが声質を決定し、**プリセット音色一覧や音色クローン／デザインの管理ページはありません**。参照音声の有無で SubAgent に渡す説明が変わり、ある場合は `@voice1` で話者を指し、ない場合は話者の身分と声質を文字で記述します。
- **過大な音声は自動処理**：長すぎる／大きすぎる参照音声は通知の上で自動的に切り詰められ、リクエストは失敗しません。
- **音質設定**：`format` / `sample_rate` / `channels` と MP3 のビットレート／音質は設定項目で指定します。`seed = -1` の場合は毎回ランダムな値が生成されます。

> 複数のプロバイダーを**同時に設定し、`priority` に従ってフォールバック**できます。各エントリは `persona_id` で**特定のペルソナにバインド**でき、「ペルソナごとに異なる音色を使う」ことが可能です。

より多くのプロバイダー（Edge TTS、GPT-SoVITS など）も計画中です。コミュニティからの貢献を歓迎します！

---

## 合成記録（オプション）

プラグインは TTS 合成の結果（チャット音声 / ボイスプレビュー / デザイン試聴 / Agent からの能動送信など）を 1 件ずつ「合成記録」としてディスクに保存します。統一管理ページ（`pages/tts_studio`）では、再生、メタデータの確認、個別削除、一括クリアができます。

- **ストレージの階層化（AstrBot 規約に準拠）**：メタデータ（ソース / プロバイダー / 時刻 / テキスト / 形式 / 再生時間 / サイズ / 拡張パラメータ）は公式 KV に保存（プラグインの名前空間で自動的に分離、単一キー `synthesis_index`）。音声バイナリは `plugin_data/synthesis_records/` に保存し、KV には入れません。
- **保持ポリシー**は設定項目 `synthesis_record_max` で制御します：`0` または負数で保存を無効化；正整数の場合は最新 N 件のみ保持（「無制限」は非対応）、超過分は最古の記録とその音声ファイルを自動的に淘汰します。

## 長期記憶検索（LivingMemory、オプション）

同じ AstrBot インスタンスに LivingMemory プラグインがインストール・有効化され、ベクトル埋め込みモデルが設定されている場合、TTS Enhancer は合成前に関連する長期記憶を呼び出し、音声スタイル判断の参考として SubAgent に注入できます（例：ユーザーの安定した音声の好み、会話の背景）。これにより音声に「記憶の感覚」を持たせます。

- `memory_retrieval_top_k`：1 回の検索で呼び出す件数。`0` = 無効（デフォルトは無効）。
- `memory_retrieval_query_strategy`：検索キーワードの取得元。`user_message` は合成対象テキストを使用；`prefix` は固定プレフィックスを使用（朗読とは無関係な合成テキストを検索に混ぜてノイズを取り込むのを回避）。
- `memory_retrieval_prefix`：固定検索プレフィックス。`prefix` 戦略の場合のみ表示・有効。
- 全体を通してグレースフルデグラデーション：LivingMemory が無効、Embedding Provider が存在しない、呼び出しが異常終了した場合などは自動的にスキップし、TTS 合成に影響しません。

## クイックスタート

1. **プラグインをインストール**  
   AstrBot のプラグインマーケットで検索してインストール
2. **プロバイダーを設定**  
   プラグイン設定 → 少なくとも 1 つのプロバイダーを追加。
3. **モデルに `<tts>` タグを出力させる**  
   メインモデルが返信内で `<tts>合成するテキスト</tts>` で包むと、プラグインが自動的に処理して音声メッセージを送信します。
4. **Tool 呼び出しを使う**  
   プラグインは `send_voice_to_user` ツールを登録済みで、モデルはタグなしで音声を送信するタイミングを自律的に決定できます。

---

## 設定項目（簡略版）

```yaml
enable_enhance: true              # SubAgent による自動拡張を有効化
enhance_llm_provider: ""          # 拡張に使用するモデル（節約のため、少し能力の劣る格安または無料モデルでも可）
context_window: 10                # コンテキストのターン数
dual_output: false                # テキストと音声を同時に出力
# ---- 長期記憶検索（LivingMemory、オプション）----
memory_retrieval_top_k: 0         # 検索件数（0=無効）
memory_retrieval_query_strategy: "user_message"  # キーワード取得元：user_message / prefix
memory_retrieval_prefix: "ユーザーの音声の好み"  # 固定検索プレフィックス（prefix 戦略のみ有効）
page_background: []               # 管理ページの背景画像（file 型、空=非表示）
page_background_opacity: 0.5       # 背景画像の不透明度（0~1、背景画像を設定した場合のみ有効）
page_background_blur: 0            # 背景画像のぼかし（0~30px、背景画像を設定した場合のみ有効）
synthesis_record_max: 50           # 合成記録の最大保持件数（0 または負数=無効；正整数=最新 N 件を保持；無制限は非対応）
providers:                        # プロバイダー一覧（複数設定してフォールバック可能）
  - __template_key: bailian_qwen_audio_3_0_tts
    display_name: "マイボイス"
    priority: 0
    persona_id: ""                # ペルソナにバインド（オプション、空=汎用フォールバック音色）
    api_key: "sk-..."
    workspace_id: "ws-..."
    model: "flash"
    voice: "longanhuan_v3.6"
    timeout: 60
```

設定項目の詳細については、プラグイン設定ページのヘルプ情報をご参照ください。

---

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────┐
│ [メインモデル]  "<tts>今日はいい天気ですね</tts>" を出力       │
│   - GoogleGemini3_8FlashTTSAdapter                          │
│   - FishAudioS2Adapter                                      │
│   - FishAudioDrama3Adapter                                  │
│   - ElevenLabsV4Adapter                                     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [TTS Enhancer プラグイン]                                    │
│   1. <tts> タグを解析                                        │
│   2. 直近のコンテキストを取得（ウィンドウサイズは設定可能）     │
│   3. SubAgent プロンプトを構築（プロバイダーの能力説明書を含む） │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [SubAgent]  tts_enhance ツールを呼び出し                      │
│   構造化パラメータを出力：{ text, instruction, volume, rate,  │
│                     pitch, language_hints }                  │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ [Provider Adapter]  パラメータ検証 → API 呼び出し → 音声ダウンロード │
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
└─────────────────────────────────────────────────────────────┘
```

---

## コントリビューションガイド

TTS プロバイダーの追加を歓迎します！手順はわずかです：

1. **アダプターを書く**：`providers/` の下に `<vendor>_<model>.py` を新規作成し、`TTSProviderAdapter` または既存の共通基底クラスを継承。
2. **能力説明書を書く**：`providers/docs/<template_key>.md` を作成し、パラメータ、タグ、例を詳しく記述。
3. **フロントエンド対応（必要に応じて）**：
   - UI が必要：`pages/tts_studio/components/` の下に Vue コンポーネントを新規作成し、`components/common/` の共通コンポーネントを参照して `providerConfig` を設定；`app.js` でマッピングを登録。
   - 公式コンソールあり：`app.js` で外部リンクを設定するだけ。
   - 特殊な操作ニーズあり（例：MiniMax の「未アクティベート → プレビュー → アクティベート」の 3 段階）：専用のカスタムコンポーネントを個別に作成。
4. **設定テンプレートを追加**：`_conf_schema.json` にプロバイダーの設定項目を補足。

追加されたすべてのプロバイダーはファクトリによって自動的に検出・ロードされ、コアコードの変更は不要です。

---

## ドキュメントと更新

- [CHANGELOG.md](../../CHANGELOG.md) – 完全なバージョン履歴
- **アーキテクチャドキュメント** [ARCHITECTURE.md](ARCHITECTURE.md) – 設計目標、全体の階層構造、リクエストライフサイクル、コアモジュール、アダプター体系、ペルソナルーティング、セキュリティ設計など
- **開発ガイド** [DEVELOPMENT.md](DEVELOPMENT.md) – 環境準備、プロバイダー追加チェックリスト、アダプター開発、フロントエンド対応、テスト規約、リリースフロー
- **既知の制限と上流の責任** [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) – 設計上の取舍 / 上流保証 / 到達不能項目の処理とグリーンテストガード
- 他の言語の README：[中文](../../README.md) · [English](../en/README.md) · [Русский](../ru/README.md)
- 能力説明書のサンプル：
  - `providers/docs/bailian_qwen_audio_3_0_tts.md`
  - `providers/docs/bailian_qwen_audio_3_1_tts.md`
  - `providers/docs/bailian_cosyvoice_v3_5.md`
  - `providers/docs/minimax_speech_2_8.md`
  - `providers/docs/mimo_v2_5_tts.md`
  - `providers/docs/mimo_v2_5_tts_preset.md`
  - [Fish Audio S2 能力説明](../../providers/docs/fish_audio_s2.md)
  - [Fish Audio Drama 3 能力説明](../../providers/docs/fish_audio_drama_3.md)

## ライセンス

GNU Affero General Public License v3.0 – 詳細は [LICENSE](../../LICENSE) をご覧ください。
