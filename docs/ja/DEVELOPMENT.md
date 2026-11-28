# TTS Enhancer 開発ガイド

> プラグインのコントリビューターとメンテナー向けの実践マニュアル。
> 関連ドキュメント：[アーキテクチャドキュメント](ARCHITECTURE.md) · [既知の制限と上流の責任](KNOWN_LIMITATIONS.md) · [English README](../en/README.md) · [CHANGELOG](../../CHANGELOG.md)

本文は「TTS プロバイダーを新規追加する方法」を主軸に、アダプター、ケイパビリティドキュメント、設定、フロントエンド、テストなどすべての段階を繋ぎます。

---

## 1. 環境準備

### 1.1 実行 / デバッグ環境

- Python ≥ 3.10（AstrBot と同じ）。
- AstrBot のソースツリー内で、本プラグインのディレクトリを `data/plugins/astrbot_plugin_tts_enhancer/` へシンボリックリンクまたはコピーし、AstrBot 起動後に WebUI でプラグインを有効化。
- バックエンドの依存（非同期 HTTP など）は AstrBot のメイン環境が提供；アダプターに追加ライブラリが必要な場合は、プラグインルートの `requirements.txt` に記述（AstrBot がインストール）。

### 1.2 テスト環境（pytest）

- テストスイートは `tests/` にあり、`pytest.ini` で `asyncio_mode = auto` が設定済み。
- `requirements-tests.txt` が `pytest` と `pytest-asyncio` を宣言し、メイン環境の依存から分離。
- `tests/conftest.py` は**上方向へ AstrBot のソースルートを探索**（階層をハードコードしない）し、`pytest.importorskip("astrbot.core.provider")` を使用——AstrBot ソースから切り離してもクラッシュせず優雅にスキップ。

```bash
# プラグインルートで
pip install -r requirements-tests.txt
pytest                # AstrBot ソースツリー内で実行
```

### 1.3 フロントエンド（ビルド不要）

- フロントエンドはネイティブ ES Module + ローカル Vue UMD で、**パッケージング手順はなし**。JS を変更すればそのまま反映。
- フロントエンドには `package.json` や ESLint 設定がないため、`npm install` / `npx eslint` などのツールチェーン手順は不要です。

---

## 2. ディレクトリ構造

```
astrbot_plugin_tts_enhancer/
├── main.py                      # プラグインエントリ：フック + Web ルート + セキュリティ検証
├── metadata.yaml                # プラグインのメタ情報（name/version/author/repo...）
├── _conf_schema.json            # 設定スキーマ（各プロバイダーのテンプレートを含む）
├── README.md / CHANGELOG.md
├── requirements-tests.txt       # テスト依存（pytest / pytest-asyncio）
├── src/
│   ├── config.py                # TTSEnhancerConfig：設定ロード / ソート / 重複排除
│   ├── tts_parser.py            # <tts> タグ解析
│   ├── tts_service.py           # 合成オーケストレーションの中核
│   ├── sub_agent.py             # SubAgent（Function Calling によるパラメータ生成）
│   └── tools.py                 # send_voice_to_user 能動音声ツール
├── providers/
│   ├── __init__.py              # ProviderFactory（自動検出）
│   ├── base.py                  # TTSProviderAdapter 抽象基底クラス
│   ├── _bailian_speech_synthesizer.py  # Bailian 共通基底（アンダースコア接頭辞、検出対象外）
│   ├── _fish_audio.py          # Fish Audio 共通基底（S2 / Drama 3 のリクエスト層を共有）
│   ├── <vendor>_<model>.py      # 具体アダプター（すなわち template_key）
│   ├── utils/{http,audio}.py    # 共通 HTTP / 音声ユーティリティ
│   └── docs/<docs_key>.md       # ケイパビリティドキュメント（*_design.md を含む）
├── pages/tts_studio/           # フロントエンド（Vue 3、ビルド不要）
│   ├── index.html / app.js / style.css
│   ├── components/common/       # プロバイダー間で共有するコンポーネント
│   ├── components/*.js          # 各プロバイダーのコンポーネント
│   ├── composables/             # useAudioManager / useTextValidator ...
│   └── static/vue.global.prod.js
└── tests/                       # pytest スイート
```

---

## 3. 新しい TTS プロバイダーの追加（チェックリスト）

| 手順 | 成果物 | 必須？ |
|------|--------|--------|
| 1. アダプターを書く | `providers/<template_key>.py`（`DISPLAY_NAME` も定義） | ✅ |
| 2. ケイパビリティドキュメントを書く | `providers/docs/<docs_key>.md`（必須セクション `## 你的任务` を含む） | ✅（なければプレーンテキストに降级） |
| 3. 設定スキーマ | `_conf_schema.json` の `providers.templates` にテンプレートを追加 | ✅ |
| 4. 4 言語の i18n を同期 | `.astrbot-plugin/i18n/{zh-CN,en-US,ja-JP,ru-RU}.json` | ✅ |
| 5. フロントエンド対応 | `pages/tts_studio/components/*.js` + `app.js` の `componentMap` に登録 | カスタム UI が必要な場合のみ |
| 6. テスト | `tests/` にケースを追加 | ✅ |

> 追加したプロバイダーはすべて `ProviderFactory` によって**自動的に検出・ロード**され、コアコードの変更は不要です。ファイル名（`.py` を除く）が `template_key` であり、`_conf_schema.json` の `templates` キーと一致している必要があります。
>
> **4 言語の i18n 同期は必須です。** 次の 4 ファイルすべてに同じキー構造で文言を追加し、翻訳の抜けを確認してください：
>
> - `.astrbot-plugin/i18n/zh-CN.json`
> - `.astrbot-plugin/i18n/en-US.json`
> - `.astrbot-plugin/i18n/ja-JP.json`
> - `.astrbot-plugin/i18n/ru-RU.json`

---

## 4. アダプター開発の詳細

### 4.1 最小限で動作するアダプター

```python
"""Example TTS 适配器"""

from .base import TTSProviderAdapter


class ExampleTtsAdapter(TTSProviderAdapter):
    """示例供应商适配器"""

    def get_subagent_system_prompt(self) -> str:
        docs = self.docs_content
        return (
            f"你是语音合成参数优化助手。参数说明：\n\n{docs}\n\n"
            "请直接调用 tts_enhance 工具，不要额外解释。"
        )

    def get_tool_schema(self):
        # 通过基类 build_enhance_tool 构造 tts_enhance 并自动挂上校验 handler
        # （见 base.py：固定工具名、统一 FunctionTool 构造与 _handle_enhance_tool 接线）
        return self.build_enhance_tool(
            description="将文本合成为语音所需的参数",
            parameters={...},  # 该适配器的参数 schema
        )

    async def call_api(self, text, raw_params, config, voice_id=None) -> str:
        # 1. 合并配置与 raw_params（工具参数优先）
        # 2. 构造请求、调用 API、下载音频
        # 3. 落盘并返回路径；失败返回 ""（不要抛未捕获异常到主流程）
        ...
```

### 4.2 実装必須の抽象メソッド

- `get_subagent_system_prompt() -> str`：ケイパビリティドキュメントを連結し、SubAgent にパラメータ生成を指示。
- `get_tool_schema() -> FunctionTool | None`：基底クラスの `build_enhance_tool` を経由して `tts_enhance` ツールを返す（検証ハンドラ接続済み）。`None` を返すと Function Calling 非対応を示し（プレーンテキスト降级へ）。
- `call_api(text, raw_params, config, voice_id=None) -> str`：合成の中核。音声ファイルのパスを返す；**失敗時は例外を投げず空文字を返す**（メインフローがこれを見てプロバイダーを切り替える）。`voice_id` はプレビュー時に音色を明示的に上書きするために使用。

### 4.3 任意機能（音色 / ファイル管理）

デフォルトは `raise NotImplementedError` で、`main.py` のルートがこれを捕捉して `501` を返す。実装すればフロントエンド / ルートから呼び出されます：

- 音色：`create_voice(params)`、`query_voice(voice_id, custom_speaker_id=None)`、`list_voice(**kwargs)`、`delete_voice(**kwargs)`。プロバイダーの API に合わせて必要な操作だけを実装してください（例：Seed TTS 3.0 は作成 / 照会のみ。プレビューは共通の `/voice/preview` ルートを使用）。
- ファイル：`upload_file(file_path, **kwargs)`、`list_files(**kwargs)`、`get_file_content(file_id)`、`delete_file(file_id, **kwargs)`。

> ファイル管理ルート（`/file/*`）は `entry_id`/`file_id` 以外の引数を `**kwargs` としてアダプターへ透過的に渡し、拡張の柔軟性を保持します。

### 4.4 パラメータの検証と清洗

- **範囲 / 列挙検証**：`validate_params(params) -> (bool, str)` をオーバーライド。`(False, msg)` を返すと SubAgent が `role:"tool"` の構造化ツール結果（エラーテキストを含む）を LLM へ再注入してリトライし、最終失敗時に `sanitize_params` による清洗フォールバックへ移行。
- **清洗**：`sanitize_params(params) -> dict` をオーバーライドし、不正値を破棄して合法値を保持（例：LLM が文字列で返した数値を `_as_float`/`_as_int` で数値に正規化し、`bool` を除外）。
- **汎用検証**：基底クラスの `validate_voice_id()`、`validate_text_length()` をそのまま利用（漢字 = 2 文字、フロントエンドの `useTextValidator` と整合）。重複実装を避ける。
- **型安全**：引数の解析は必ず `_as_float` / `_as_int` を経由。「文字列の数値を拒否」かつ「bool を見逃す」を回避。

### 4.5 音声の落盤規約

- 合成結果は一律で `providers/utils/audio.py` の `save_audio_bytes(data_dir, content, fmt)` を使って落盤——`config["_data_dir"]` 下にタイムスタンプ付きで保存し、パスを返す。
- `_data_dir` は `TTSService`/`main.py` が entry 辞書へ注入（値は `plugin_data/<name>/audio`）。アダプターは**パスをハードコードしない**。

### 4.6 utils の再利用

- `providers/utils/http.py`：`bearer_headers(api_key, with_json=True)`、`extract_error_message(payload, fallback_text)`（`message`/`error`/`detail` に対応）。
- `providers/utils/audio.py`：`save_audio_bytes(...)`、`get_audio_duration`、`validate_audio_duration`、`trim_audio_to_max`、`AudioConstraints`（プラットフォームごとの再生時間制約定数）。

### 4.7 `voice_id` の上書き規約

`call_api` の `voice_id` 引数は「プレビュー時に音色を明示的に上書き」に使用。標準的な書き方：

```python
voice = voice_id or config.get("voice") or config.get("voice_id")
if not voice:
    raise ValueError("未提供音色 ID，无法合成语音")
```

各プロバイダーの設定キー名は上流 API と一致させる（Bailian は `voice`、MiniMax は `voice_id`）。強制統一はしない。

---

## 5. ケイパビリティドキュメントの記述規約

ファイル：`providers/docs/<docs_key>.md`。SubAgent が直接読み取って注入します。推奨構成：

1. **概要**：モデルの出所と位置づけ。
2. **コアパラメータ表**：必須 / 任意パラメータ（型、範囲、デフォルト値、説明）。
3. **列挙**：言語、感情タグ、方言など。
4. **使用例**：完全な `tts_enhance` パラメータ例を含む。
5. **`## 你的任务`（必須）**：SubAgent に、コンテキストに基づいてパラメータを選択する方法と `tts_enhance` を呼び出すタイミングを明示的に伝える。この見出しを省略しないでください。
   - 例：「コンテキストの口調に応じて text に制御タグを追加；instruction/rate/volume で詳細を制御；直接 tts_enhance を呼び出す。」

ある種の音色（例：デザイン音色）の機能が制限されている場合（方言非対応）、`<docs_key>_design.md` に個別に記述し、アダプターの `get_docs_for_voice(voice)` で音色 ID に応じて自動切り替え；同じモデルではサブクラスの `DOCS_KEY` でドキュメントを再利用できます。

---

## 6. 設定スキーマの拡張

`_conf_schema.json` の `providers.templates` 下に `template_key` をキーとしたテンプレートを追加：

```json
"my_provider": {
  "name": "我的供应商",
  "hint": "一句话能力说明",
  "display_item": "display_name",
  "items": {
    "display_name": { "description": "显示名称", "type": "string", "default": "我的供应商" },
    "priority":     { "description": "优先级（越小越优先）", "type": "int", "default": 0 },
    "persona_id":   { "description": "绑定人格", "type": "string", "_special": "select_persona", "default": "" },
    "api_key":      { "description": "API Key", "type": "string", "secret": true },
    "model":        { "description": "模型", "type": "string", "options": ["a", "b"], "default": "a" }
  }
}
```

ポイント：

- `_special: select_provider` / `select_persona`：ドロップダウン選択として描画。
- `secret: true`：パスワード欄のマスキング。
- `options`：固定列挙ドロップダウン；`condition`：他のフィールド値による条件表示（例：MiMo は `model` に応じて音色 / デザイン / クローンのフィールドを切り替え）。
- フレームワークが `__template_key` と `display_item` で指定された表示名を自動注入。

---

## 7. フロントエンド対応

### 7.1 フロントエンドが必要な場合

- **表示名**：バックエンドのアダプターに `DISPLAY_NAME` を定義します。`GET /providers` が返す `display_name` をフロントエンドが表示するため、フロントエンドでの表示名のハードコードは不要です。
- **タブの表示可否**：音色管理機能を持つアダプターは `VoiceManageable` を継承します。`GET /providers` の `capabilities.voice_management` がタブ表示の単一のデータソースです。
- **カスタム UI**：`components/` 下にコンポーネントを書き、必要に応じて `components/common/` の共通コンポーネントを再利用して、`app.js` の `componentMap` に登録します。登録しないと、バックエンドが音色管理対応と宣言してもタブを選択できません。
- **公式コンソールの補完**：音色デザインやスロット購入など、プラグインが操作を提供しない機能はコンポーネント内から公式コンソールへリンクします。外部リンクだけでプロバイダー統合が完了するわけではありません。

### 7.2 コンポーネント登録（`app.js`）

```js
import MyProvider from './components/my_provider.js';
// componentMap に追加：'my_provider': MyProvider
// 表示名はバックエンドの DISPLAY_NAME、タブ表示は capabilities.voice_management に従う
```

### 7.3 共通コンポーネントとカスタム UI の例

Bailian 系プロバイダーは `components/common/bailian_speech_synthesizer.js` を再利用し、薄いラッパーはプロバイダー固有の違いだけを実装します。共通コンポーネントはクローン / デザインの 2 モード（クローン音声はブラウザで Data URL にエンコードして直接送信）、試聴、一覧、削除、および `voice_preview_modal` / `delete_confirm_modal`（サンドボックス下で `confirm()` の代替）をカプセル化済みです。

Seed TTS 3.0 は一覧 / 削除を提供しないため、Bailian 系の共通 UI をそのまま使わず、`volcengine_seed_tts_3_0.js` にクローン / 単一音色の照会 / プレビュー専用のカスタム UI を実装しています。公式音色リストと音色デザインコンソールへのリンクもこのコンポーネントが提供します。

### 7.4 bridge API

すべてのバックエンド呼び出しは `window.AstrBotPluginPage`（`bridge`）を経由：

- `await bridge.ready()`：bridge の準備を確認。
- `await bridge.apiGet('providers')`：グループ化されたプロバイダー一覧を取得。
- `bridge.upload(...)`：ファイルのアップロード（`asset_token` 認証とクロスオリジンを回避）。
- その他のルートは `bridge.apiPost('<route>', payload)` 形式で呼び出し（例：`voice/create`、`file/upload`、`kv/set` など）。

### 7.5 composables

- `useAudioManager`：グローバルな音声再生シングルトン（音量共有、コンポーネント間の toggle）。
- `useTextValidator`：`countChars`（漢字 = 2）、`validateText({label,min,max,required})` → `{valid,error,count}`。
- `useClipboard`、`useToast`：クリップボードと通知。

### 7.6 浮層とアニメーションの規約

- **モーダル / Toast は必ず body へ Teleport**：`<Teleport to="body"><Transition name="modal"><div class="modal-overlay">…`。ページレベルのフェードインアニメーション（`animation-fill-mode: both`）終了後、Chrome は祖先に 2 種類の副作用を残します——単位行列の変換（`position: fixed` の子孫の包含ブロックとなり、浮層をアニメーション祖先のボックスに固定）と合成レイヤー（すなわち重ね合わせコンテキストで、サブツリーの z-index を固定）。body への Teleport が唯一の堅牢解。オーバーレイのサイズには `100%` ではなく `100vw/100vh` を使用（古典的なスクロールバーの問題）。
- **出入りには CSS animation ではなく `<Transition>` を使用**：Transition の enter/leave クラスは再生後に削除され、要素は通常状態に戻る；`animation-fill-mode: both` は変換 / 合成レイヤーを要素に永続的に残す（上記 2 種類の副作用の根源）。
- **継続的なトランジションには transform を使用**：例：タブのハイライトバー `translateX + scaleX` + `will-change`。コンポジターを通し、メインスレッドの毎フレームのレイアウトを回避。
- **reduced-motion**：すべてのアニメーションは `@media (prefers-reduced-motion: reduce)` 内で `transition/animation: none` とする。
- **テーマ属性 / CSS 変数は `html` / `body` にのみ設定し、`#app` には設定しない**：Teleport 後の浮層（音量バー、すべてのモーダル、トースト）は `#app` のサブツリーを離れており、継承できるのは `:root` / `html` レベルの定義のみ。現在テーマ変数はすべて `:root` にあるため浮層は安全だが、これは**暗黙の契約**であり、将来テーマ属性や変数を `#app` に移すと、すべての浮層がエラーなく静かにテーマを失います。

---

## 8. テスト規約

### 8.1 テストの実行

```bash
pip install -r requirements-tests.txt
pytest                 # AstrBot ソースツリー内で
pytest tests/test_xxx.py -k "case"   # 単一ファイル / 単一ケース
```

### 8.2 conftest の規約

- AstrBot のソースルートを自動検出し、依存が欠けている場合は `importorskip` でスキップ。
- `entry` の構築や Provider の mock などに便利なテストフィクスチャを提供（詳細は `tests/conftest.py`）。

### 8.3 xfail の規約（重要）

- 既知の缺陷 / 設計上の取舍 / 上流保証 / 到達不能な経路は、**`@pytest.mark.xfail` で回帰シグナルとして固化**する。「現状を書き切った」普通のケースで後の修正をブロックしないように。
- 該当する缺陷を修正したら、xfail を普通の回帰ケースへ変換。
- 新しいケースを書いた後、**変更を戻してそのケースが失敗することを確認**し、偽陽性テストを避ける。
- **复核後**（前の行の「xfail で固化」の一時段階を受けて）：観察項目が 2 次复核で「もう修正しない」と判定された場合、**xfail を長期にわたって残すべきではなく**、性質に応じて処理し `docs/zh/KNOWN_LIMITATIONS.md` に記録する：
  - 設計取舍类 → 「受け入れた挙動」をアサートする普通のグリーンテストへ変換（命名から `should_not` の缺陷示唆を外す）、現在の契約をロック。
  - 上流保証 / 不可達类 → **グリーンテストガードとして保持**（現在の挙動をロックし回帰センチネルを残す、削除しない）；「不可達」の論拠がリファクタリング後に無効になり得る場合（#14 など）は、さらに 1 行の極小なコード補強を行う。

---

## 9. コードスタイルとコメント

- コメントとログはデフォルトで**中国語**（サードパーティの個人プラグイン；AstrBot 本家リポジトリへ PR を出す場合のみ英語）。
- Docstring は **Google スタイル**（`Args`/`Returns`/`Raises`）に従う。既存モジュールを参照。
- ログは `from astrbot.api import logger` に統一し、組み込みの `logging` は使用禁止。
- KISS に従う：不要な抽象化や helper を避け、インライン化できるロジックを関数に切り出さない。
- パス処理は `pathlib.Path` を使用し、文字列連結しない。

---

## 10. リリースとバージョン

1. **コード変更** → 2. **バージョン番号**（`metadata.yaml` の `version`、`vX.Y.Z` 形式を維持）→ 3. **README / CHANGELOG の更新** → 4. **ブランチ + コミット** → 5. **プッシュ**（個人 GitHub アカウント、PAT）。
2. `CHANGELOG.md` は [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) とセマンティックバージョニングに従う。
3. **4 言語すべての README を同期**：ルートの `README.md`（中国語）、`docs/en/README.md`（英語）、`docs/ja/README.md`（日本語）、`docs/ru/README.md`（ロシア語）のバージョンバッジとプロバイダーテーブルを同じリリース内容に更新してください。
4. **`CHANGELOG.md` も同期**：README のバージョンと機能説明に合わせて変更内容を追記します。
5. 複数ラウンドのタスクは「wrap-up 検証 + CHANGELOG エントリ」で締める。

---

## 11. よくある落とし穴

- **プラグイン自身のディレクトリにデータを永続化しない**：`plugin_data/` 下に書く。でないと更新 / 再インストールで失われる。
- **`call_api` の失敗は例外ではなく空文字を返す**：メインフローが空文字でプロバイダー切り替えを判定する。
- **引数解析には `_as_float/_as_int` を使用**：LLM は数値を文字列で返すことが多く、`bool` も除外する必要がある。
- **`template_key`、`_conf_schema.json` のテンプレートキー、アダプターのファイル名は 3 者一致させる**。
- **ケイパビリティドキュメントが欠けていると、そのプロバイダーは自動的にプレーンテキストへ降级**（エラーは出ないが拡張機能を失う）。

</content>
</invoke>
