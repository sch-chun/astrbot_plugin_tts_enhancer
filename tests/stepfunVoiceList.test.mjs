// StepFun 音色预览组件：entry_id=0 必须能触发音色列表加载。
//
// 回归背景：providers 接口给每个供应商条目分配的 id 是数组索引（voice.py:55
// `item["id"] = idx`），单供应商时 id=0。JS 里 0 是 falsy，若用真值判断
// `if (selectedEntryId.value)` 决定要不要 fetchVoiceList，进场与切换都不会请求，
// 页面永远显示「暂无音色」。修法是用 null/undefined 判断（hasEntry）。
//
// 组件是内联 template 的 ES module、依赖 Vue 全局，无法在 node 里挂载实例；
// 这里用源码断言锁住「不得回退到真值判断」这条防线，能被 CI 的 node --test 执行。
// 运行：node --test tests/stepfunVoiceList.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const COMPONENT = path.join(
    ROOT,
    'pages',
    'tts_studio',
    'components',
    'stepfun_stepaudio_3_tts.js',
);
const source = fs.readFileSync(COMPONENT, 'utf-8');

test('StepFun 组件定义了 null/undefined 语义的 hasEntry 守卫', () => {
    assert.match(
        source,
        /const hasEntry\s*=\s*\(\)\s*=>[\s\S]*?selectedEntryId\.value\s*!==\s*null[\s\S]*?selectedEntryId\.value\s*!==\s*undefined/,
        'hasEntry 必须用 !== null && !== undefined 判断，不能用真值',
    );
});

test('进场/切换/请求 guard 三处都走 hasEntry，不用裸真值判断', () => {
    // 三处设计上应各有一次 hasEntry() 调用：fetch guard、watch、onMounted
    const calls = source.match(/hasEntry\(\)/g) || [];
    assert.ok(
        calls.length >= 4, // 1 定义体之外，至少 guard + watch + onMounted 三处调用
        `hasEntry() 调用点不足（找到 ${calls.length} 处），可能漏了 guard/watch/onMounted`,
    );
    // 不得出现会挡住 id=0 的裸真值判断
    assert.doesNotMatch(
        source,
        /if\s*\(\s*selectedEntryId\.value\s*\)\s*fetchVoiceList/,
        'onMounted 不得用 if (selectedEntryId.value)，id=0 时不会加载',
    );
    assert.doesNotMatch(
        source,
        /if\s*\(\s*newId\s*\)\s*fetchVoiceList/,
        'watch 不得用 if (newId)，id=0 时不会加载',
    );
});

test('表格展示官方 system_voices 全部字段（含推荐场景列）', () => {
    // 后端返回 voice_id / voice_name / description / recommended_scene；
    // 前端必须四者都渲染，不能漏掉 recommended_scene。
    for (const field of ['voice_name', 'voice_id', 'description', 'recommended_scene']) {
        assert.ok(
            source.includes(`v.${field}`) || source.includes(`v.recommended_scene`),
            `表格未渲染官方字段 ${field}`,
        );
    }
    // 推荐场景表头用了 i18n 键 sfColScene
    assert.match(source, /\{\{\s*t\.sfColScene\s*\}\}/, '推荐场景表头必须用 t.sfColScene');
    // splitScenes 按顿号/逗号拆分（官方用顿号分隔多个场景）
    assert.match(
        source,
        /\.split\(\s*\/\s*\[[^\]]*[、,，][^\]]*\]\s*\/\s*\)/,
        'splitScenes 必须按顿号/逗号拆分场景',
    );
    // 专属表格 class，避免影响其他供应商
    assert.ok(source.includes('sf-voice-table'), '表格必须带 sf-voice-table 专属 class');
});

test('已复刻音色表：独立拉取、有才显示、置顶于系统音色表之上', () => {
    // 独立 voice_type=cloned 拉取，缓存键与系统音色隔离
    assert.match(
        source,
        /voice_type:\s*['"]cloned['"]/,
        '复刻音色必须用 voice_type=cloned 单独拉取',
    );
    // 空则不显示：整块 v-if="clonedVoiceList.length"
    assert.match(
        source,
        /v-if="clonedVoiceList\.length"/,
        '复刻音色表必须 v-if clonedVoiceList.length（无复刻音色时整块隐藏）',
    );
    // 三列官方字段都渲染：voice_id / file_id / created_at
    for (const field of ['voice_id', 'file_id', 'created_at']) {
        assert.ok(
            source.includes(`v.${field}`),
            `复刻音色表未渲染官方字段 ${field}`,
        );
    }
    assert.match(
        source,
        /formatCreatedAt\(\s*v\.created_at\s*\)/,
        'created_at 需经 formatCreatedAt 转为可读时间',
    );
    // 顺序：复刻表（sfClonedTitle）必须在系统音色表（voiceListTitle）之前
    const clonePos = source.indexOf('{{ t.sfClonedTitle }}');
    const sysPos = source.indexOf('{{ t.voiceListTitle }}');
    assert.ok(clonePos > -1, '模板缺少复刻音色标题');
    assert.ok(clonePos < sysPos, '复刻音色表必须置于系统音色表之上');
    // 专属表格 class，避免影响系统音色表列宽
    assert.ok(source.includes('sf-clone-table'), '复刻表需带 sf-clone-table class');
});

test('CSS 含复刻表专属列宽', () => {
    const css = fs.readFileSync(
        path.join(ROOT, 'pages', 'tts_studio', 'style.css'),
        'utf-8',
    );
    assert.ok(css.includes('.sf-clone-table'), 'style.css 缺少 .sf-clone-table');
    for (const cls of ['sf-clone-col-id', 'sf-clone-col-file', 'sf-clone-col-created']) {
        assert.ok(css.includes(`.${cls}`), `style.css 缺少复刻表列宽 ${cls}`);
    }
});

test('复刻/设计外链通知位于音色列表标题之前（置顶）', () => {
    // template 里 sfCloneTip 必须出现在 voiceListTitle 之前，不能埋在列表底部
    const tipPos = source.indexOf('{{ t.sfCloneTip }}');
    const titlePos = source.indexOf('{{ t.voiceListTitle }}');
    assert.ok(tipPos > -1, '模板缺少复刻/设计通知');
    assert.ok(titlePos > -1, '模板缺少音色列表标题');
    assert.ok(tipPos < titlePos, '复刻/设计通知必须置顶（在音色列表标题之前）');
});

test('style.css 含 StepFun 专属表格样式与 reduced-motion 兜底', () => {
    const css = fs.readFileSync(
        path.join(ROOT, 'pages', 'tts_studio', 'style.css'),
        'utf-8',
    );
    for (const cls of [
        '.sf-table-wrap',
        '.sf-voice-table',
        '.scene-tag',
        '[data-theme="dark"] .scene-tag',
    ]) {
        assert.ok(css.includes(cls), `style.css 缺少样式 ${cls}`);
    }
    // 表头用实色背景（--bg），与页面底色一致
    assert.match(
        css,
        /\.sf-voice-table thead th\s*\{[\s\S]*?background:\s*var\(--bg\)/,
        '表头必须用实色 var(--bg) 背景',
    );
    // 音色列表不嵌套纵向滚动：.sf-table-wrap 不得设 max-height / overflow:auto（横向兜底 overflow-x 允许）
    const wrapRule = css.match(/\.sf-table-wrap\s*\{[^}]*\}/)?.[0] || '';
    assert.doesNotMatch(wrapRule, /max-height\s*:/, '音色表容器不得设 max-height（不嵌套纵向滚动）');
    assert.doesNotMatch(wrapRule, /overflow\s*:\s*auto/, '音色表容器不得设 overflow:auto（改为直接铺开）');
    assert.doesNotMatch(css, /\.sf-voice-table thead th\s*\{[^}]*position\s*:\s*sticky/, '表头不再需要 sticky');
    // reduced-motion 块里关闭表格行 transition
    assert.match(
        css,
        /prefers-reduced-motion:\s*reduce[\s\S]*?\.sf-voice-table tbody tr\s*\{\s*transition:\s*none/,
        '表格行 transition 必须在 reduced-motion 块里关闭',
    );
});
