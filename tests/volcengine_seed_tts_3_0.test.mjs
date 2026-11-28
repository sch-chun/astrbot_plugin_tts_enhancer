import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const componentPath = path.join(root, 'pages', 'tts_studio', 'components', 'volcengine_seed_tts_3_0.js');
const source = fs.readFileSync(componentPath, 'utf8');

test('Seed UI labels use natural language instead of API field names', () => {
    const match = source.match(/const I18N_DEFS = (\{[\s\S]*?\n\});/);
    assert.ok(match);
    const labels = Function(`return ${match[1]}`)();
    const apiFields = [
        'entry_id', 'voice_id', 'speaker_id', 'custom_speaker_id', 'prompt_text',
        'prosody_boost', 'demo_text', 'enable_audio_denoise',
        'disable_volume_normalization', 'fee_confirmed',
    ];
    for (const field of apiFields) {
        assert.equal(Object.values(labels).some(value => value.includes(field)), false, field);
    }
});

test('Seed checkboxes stay compact and left-aligned', () => {
    const css = fs.readFileSync(path.join(root, 'pages', 'tts_studio', 'style.css'), 'utf8');
    assert.doesNotMatch(source, /class="checkbox-label"/);
    assert.match(source, /class="seed-checkbox-label"/);
    assert.match(css, /\.seed-checkbox-label \{ display: flex; align-items: center; gap: 8px;/);
    assert.match(css, /\.seed-checkbox-label input\[type="checkbox"\] \{[\s\S]*?width: 16px;[\s\S]*?flex: 0 0 auto;/);
});

test('Seed component keeps entry_id=0 usable', () => {
    assert.match(source, /const hasEntry = \(\) =>\s*selectedEntryId\.value !== null && selectedEntryId\.value !== undefined;/);
    assert.match(source, /entry_id: selectedEntryId\.value/);
    assert.doesNotMatch(source, /if \(selectedEntryId\.value\)/);
});

test('Seed component uses create/query/preview routes without unsupported list/delete', () => {
    assert.match(source, /apiPost\('voice\/create'/);
    assert.match(source, /apiPost\('voice\/query'/);
    assert.match(source, /<VoicePreviewModal/);
    assert.doesNotMatch(source, /voice\/(list|delete)/);
});

test('Seed component sends Base64 audio and only Seed advanced options', () => {
    assert.match(source, /audioData\.value = btoa\(binary\)/);
    assert.match(source, /audio: \{ data: audioData\.value, format: audioFormat\.value \}/);
    for (const field of ['prompt_text', 'prosody_boost', 'demo_text', 'enable_audio_denoise', 'disable_volume_normalization']) {
        assert.ok(source.includes(field), `missing ${field}`);
    }
    assert.match(source, /const volumeNormalization = ref\(true\)/);
    assert.match(source, /\['disable_volume_normalization', !volumeNormalization\.value\]/);
    assert.match(source, /v-model="volumeNormalization"/);
    assert.doesNotMatch(source, /voice_clone_denoise_model_id|voice_clone_enable_mss|enable_crop_by_asr/);
});

test('Seed component validates audio limits and mapped cloning languages', () => {
    assert.match(source, /MAX_AUDIO_BYTES = 10 \* 1024 \* 1024/);
    assert.match(source, /duration < 10 \|\| duration > 60/);
    assert.match(source, /audioFormat\.value === 'pcm' && buffer\.byteLength % 2 !== 0/);
    assert.match(source, /if \(!selectedLanguage\.value\) return showError\(t\.errLanguage\)/);
    assert.match(source, /language: selectedLanguage\.value\.id/);
    assert.match(source, /<select v-model="languageCode">/);
    assert.match(source, /v-for="item in CLONE_LANGUAGES" :key="item\.code" :value="item\.code"/);
    assert.ok(source.includes('{{ item.name }}（{{ item.id }} · {{ item.code }}）'));
    assert.doesNotMatch(source, /v-model="language" type="number"/);
});

test('Seed clone language mapping collapses Chinese variants and covers official IDs', () => {
    const match = source.match(/const CLONE_LANGUAGES = (\[[\s\S]*?\n\]);/);
    assert.ok(match);
    const languages = Function(`return ${match[1]}`)();
    assert.equal(languages.length, 102);
    assert.equal(new Set(languages.map(item => item.code)).size, 102);
    assert.equal(new Set(languages.map(item => item.id)).size, 102);
    assert.equal(languages.find(item => item.code === 'zh').id, 0);
    assert.equal(languages.some(item => item.code === 'yue'), false);
    assert.equal(languages.some(item => item.code.startsWith('zh-CN-x-')), false);
    assert.equal(languages.find(item => item.code === 'en').id, 1);
    assert.equal(languages.find(item => item.code === 'zu').id, 118);
    assert.equal(languages.find(item => item.code === 'sv').promptTextRequired, true);
    assert.equal(languages.find(item => item.code === 'sv').prosodySupported, false);
    assert.equal(languages.find(item => item.code === 'en-GB').prosodySupported, false);
});

test('Seed component enforces language-specific prompt text and prosody support', () => {
    assert.match(source, /promptTextRequired\.value \|\| !!promptText\.value\.trim\(\)/);
    assert.match(source, /if \(promptTextRequired\.value && !promptText\.value\.trim\(\)\) return showError\(t\.errPromptText\)/);
    assert.match(source, /watch\(prosodySupported, supported => \{/);
    assert.match(source, /if \(!supported\) prosodyBoost\.value = false/);
    assert.match(source, /<div v-if="prosodySupported" class="form-group">[\s\S]*?v-model="prosodyBoost"/);
    assert.doesNotMatch(source, /:disabled="!prosodySupported"/);
    assert.match(source, /promptTextRequired \? t\.promptTextRequired : t\.promptTextOptional/);
    assert.doesNotMatch(source, /prosodyUnsupported|该语种不支持韵律美化/);
});

test('Seed component places voice ID mode and input on the same responsive row', () => {
    assert.match(source, /display:grid;grid-template-columns:repeat\(auto-fit,minmax\(220px,1fr\)\);gap:12px/);
    assert.match(source, /<select v-model="idMode">[\s\S]*?<input v-model="speakerId"[\s\S]*?<input v-model="customSpeakerId"/);
});

test('Seed component groups audio with language and places denoise beside normalization', () => {
    assert.match(source, /display:grid;grid-template-columns:repeat\(auto-fit,minmax\(260px,1fr\)\);gap:12px/);
    assert.match(source, /<input type="file"[\s\S]*?<select v-model="languageCode"/);
    assert.match(source, /display:grid;grid-template-columns:repeat\(auto-fit,minmax\(220px,1fr\)\);gap:12px;margin-top:12px/);
    assert.match(source, /v-model="audioDenoise"[\s\S]*?v-model="volumeNormalization"/);
    assert.match(source, /<\/div>\s*<button class="btn btn-primary"[^>]*@click="submitClone"/);
});

test('Seed component provides hints and official voice resources', () => {
    for (const key of [
        'authConfigHint', 'idModeHint', 'prosodyHint', 'demoTextHint',
        'audioDenoiseHint', 'volumeNormalizationHint', 'queryIdHint',
    ]) {
        assert.ok(source.includes(`t.${key}`), `missing ${key}`);
    }
    assert.ok(source.includes('https://docs.volcengine.com/docs/doubao-voice/voice-list-3-0-1'));
    assert.ok(source.includes('https://console.volcengine.com/speech/new/experience/timbre'));
    assert.match(source, /target="_blank" rel="noopener noreferrer"/);
});

test('Seed component explains slot reuse and postpaid custom ID fees', () => {
    assert.match(source, /已有音色 ID 会复用账号下已购买或获赠的槽位，不收取槽位费/);
    assert.match(source, /自定义 ID 仅限后付费，首次正式合成时收取槽位费/);
    assert.match(source, /试听音色 7 天内未正式合成会被删除/);
    assert.match(source, /existingIdHint/);
    assert.match(source, /customIdHint/);
    assert.match(source, /v-model="feeConfirmed" type="checkbox"/);
    assert.match(source, /validCustomSpeakerId\(currentSpeakerId\(\)\) && feeConfirmed\.value/);
});

test('Seed component requires an ID and validates custom names and demo text', () => {
    assert.match(source, /if \(!currentSpeakerId\(\)\) return showError\(t\.errNoSpeakerId\)/);
    assert.match(source, /if \(!demoTextValid\(\)\) return showError\(t\.errDemoText\)/);
    assert.match(source, /demoText\.value\.trim\(\)\.length >= 4 && demoText\.value\.trim\(\)\.length <= 300/);
    assert.match(source, /minlength="4" maxlength="300"/);
    assert.match(source, /!\/\^\[a-z\]\{2\}_\/\.test/);
    assert.match(source, /CUSTOM_SPEAKER_RESERVED_RE/);
    assert.match(source, /CUSTOM_SPEAKER_SUFFIX_RE/);
    assert.match(source, /if \(!feeConfirmed\.value\) return showError\(t\.errFeeConfirm\)/);
    assert.match(source, /params\.fee_confirmed = true/);
});

test('Seed component prefers returned speaker IDs and queries custom names correctly', () => {
    assert.match(source, /queryId\.value = result\.value\.speaker_id && result\.value\.speaker_id !== 'custom_speaker_id'/);
    assert.match(source, /: \(params\.custom_speaker_id \|\| params\.speaker_id\)/);
    assert.match(source, /voice_id: queryCustomId\.value && queryId\.value\.trim\(\) === queryCustomId\.value/);
    assert.match(source, /\? 'custom_speaker_id'/);
    assert.match(source, /custom_speaker_id: queryCustomId\.value/);
    assert.match(source, /previewVoiceId\.value = displayVoiceId\(\)/);
    assert.match(source, /submitting, querying, queryId, result, previewModalVisible, previewVoiceId,/);
    assert.match(source, /:voice-id="previewVoiceId"/);
    assert.match(source, /:value="displayVoiceId\(\)"/);
    assert.doesNotMatch(source, /result\.speaker_id \|\| queryId/);
});
