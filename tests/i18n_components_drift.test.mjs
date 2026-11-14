// 校验脚本：前端组件级 i18n 的 JS defs 与 .astrbot-plugin/i18n/zh-CN.json 的
// views.tts_studio.components 段保持同步，避免「中文存两份、手工同步漂移」的隐患。
//
// 背景：所有组件（minimax_speech_2_8 / bailian_minimax_speech_2_8 的命名 const，
// 以及 common/ 下三个组件的内联 defs）都把键汇入同一个扁平命名空间
// views.tts_studio.components.*。defs 的值本身即为 zh-CN 兜底文案，也是生成器
// 生成 zh-CN.json 的来源。本测试确保二者不会漂移。
//
// 运行：node --test tests/i18n_components_drift.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const COMPONENTS_DIR = path.join(ROOT, 'pages', 'tts_studio', 'components');
const ZH_CN = path.join(ROOT, '.astrbot-plugin', 'i18n', 'zh-CN.json');

// ---- 注释/引号感知的对象字面量提取器 ----
// 从 source 中 startIndex 指向的 '{' 开始，做括号计数；遇到字符串（单/双/模板）
// 与注释（// 与 /* */）时跳过其中的括号，返回从 '{' 到匹配 '}' 的原文切片。
function extractObjectLiteral(source, startIndex) {
    let i = startIndex;
    let depth = 0;
    let inSingle = false;
    let inDouble = false;
    let inTemplate = false;
    let inLineComment = false;
    let inBlockComment = false;

    for (; i < source.length; i++) {
        const c = source[i];
        const next = source[i + 1];

        if (inLineComment) {
            if (c === '\n') inLineComment = false;
            continue;
        }
        if (inBlockComment) {
            if (c === '*' && next === '/') {
                inBlockComment = false;
                i++;
            }
            continue;
        }
        if (inSingle) {
            if (c === '\\') { i++; continue; }
            if (c === "'") inSingle = false;
            continue;
        }
        if (inDouble) {
            if (c === '\\') { i++; continue; }
            if (c === '"') inDouble = false;
            continue;
        }
        if (inTemplate) {
            if (c === '\\') { i++; continue; }
            if (c === '`') inTemplate = false;
            continue;
        }

        if (c === '/' && next === '/') { inLineComment = true; i++; continue; }
        if (c === '/' && next === '*') { inBlockComment = true; i++; continue; }
        if (c === "'") { inSingle = true; continue; }
        if (c === '"') { inDouble = true; continue; }
        if (c === '`') { inTemplate = true; continue; }
        if (c === '{') { depth++; continue; }
        if (c === '}') {
            depth--;
            if (depth === 0) {
                return source.slice(startIndex, i + 1);
            }
        }
    }
    throw new Error('unbalanced braces while extracting i18n defs');
}

function readDefsObject(source, mode, name) {
    let marker;
    if (mode === 'const') {
        marker = `const ${name} = {`;
    } else {
        marker = 'useComponentI18n(props.bridge, {';
    }
    const idx = source.indexOf(marker);
    if (idx < 0) throw new Error(`cannot locate i18n defs (${mode}${name ? ' ' + name : ''})`);
    const brace = source.indexOf('{', idx);
    const literal = extractObjectLiteral(source, brace);
    // 纯数据对象字面量（值为字符串），直接求值即可得到真实 JS 对象
    return new Function(`return ${literal}`)();
}

// 五个 defs 来源：两个命名 const + 三个内联对象
const SOURCES = [
    { file: 'minimax_speech_2_8.js', mode: 'const', name: 'MM_I18N_DEFS' },
    { file: 'bailian_minimax_speech_2_8.js', mode: 'const', name: 'BLMM_I18N_DEFS' },
    { file: path.join('common', 'bailian_speech_synthesizer.js'), mode: 'inline' },
    { file: path.join('common', 'delete_confirm_modal.js'), mode: 'inline' },
    { file: path.join('common', 'voice_preview_modal.js'), mode: 'inline' },
];

function loadAllDefs() {
    const perSource = [];
    for (const s of SOURCES) {
        const src = fs.readFileSync(path.join(COMPONENTS_DIR, s.file), 'utf8');
        perSource.push({ file: s.file, defs: readDefsObject(src, s.mode, s.name) });
    }
    return perSource;
}

function loadZhComponents() {
    const json = JSON.parse(fs.readFileSync(ZH_CN, 'utf8'));
    const comp = json?.views?.tts_studio?.components;
    assert.ok(comp, `zh-CN.json 缺少 views.tts_studio.components 段`);
    return comp;
}

test('JS 组件 i18n defs 与 zh-CN.json components 双向一致（无漂移）', () => {
    const perSource = loadAllDefs();
    const zh = loadZhComponents();

    // 合并所有来源的键（同名键在两处值必须一致，见下方冲突检测）
    const merged = {};
    for (const { defs } of perSource) {
        for (const [k, v] of Object.entries(defs)) {
            merged[k] = v;
        }
    }

    const missingInZh = [];
    const valueMismatch = [];
    for (const [k, v] of Object.entries(merged)) {
        if (!(k in zh)) {
            missingInZh.push(k);
        } else if (zh[k] !== v) {
            valueMismatch.push({ key: k, js: v, zh: zh[k] });
        }
    }

    const orphanInZh = [];
    for (const k of Object.keys(zh)) {
        if (!(k in merged)) {
            orphanInZh.push(k);
        }
    }

    assert.deepStrictEqual(missingInZh, [], `JS defs 中存在但 zh-CN.json 缺失的键: ${missingInZh.join(', ')}`);
    assert.deepStrictEqual(orphanInZh, [], `zh-CN.json 中存在但 JS defs 缺失的键（孤儿键）: ${orphanInZh.join(', ')}`);
    assert.deepStrictEqual(
        valueMismatch,
        [],
        `JS defs 与 zh-CN.json 值不一致的键:\n` +
            valueMismatch.map((m) => `  ${m.key}: js=${JSON.stringify(m.js)} zh=${JSON.stringify(m.zh)}`).join('\n'),
    );
});

test('扁平命名空间内同名键在不同来源之间值一致（防静默串味）', () => {
    const perSource = loadAllDefs();

    // key -> 出现过的不同值集合
    const keyValues = new Map();
    for (const { file, defs } of perSource) {
        for (const [k, v] of Object.entries(defs)) {
            if (!keyValues.has(k)) keyValues.set(k, new Map());
            const bucket = keyValues.get(k);
            if (!bucket.has(v)) bucket.set(v, []);
            bucket.get(v).push(file);
        }
    }

    const conflicts = [];
    for (const [k, bucket] of keyValues) {
        if (bucket.size > 1) {
            conflicts.push({ key: k, variants: [...bucket.entries()] });
        }
    }

    assert.deepStrictEqual(
        conflicts,
        [],
        `同一扁平命名空间内同名键存在不同值（改一处会静默影响其它组件）:\n` +
            conflicts
                .map((c) => {
                    const detail = c.variants
                        .map(([val, files]) => `    ${JSON.stringify(val)} <- ${files.join(', ')}`)
                        .join('\n');
                    return `  ${c.key}:\n${detail}`;
                })
                .join('\n'),
    );
});
