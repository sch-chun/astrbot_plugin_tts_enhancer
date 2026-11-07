// 前端 tab 选择逻辑的单测（node --test，无需浏览器 / Vue）。
// 运行：node --test tests/voiceTabs.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { selectVoiceTabs, firstUsableTab } from '../pages/tts_studio/voiceTabs.js';

// ---------- selectVoiceTabs：可见性由后端 capabilities.voice_management 决定 ----------
const GROUPS = [
    { template_key: 'a', capabilities: { voice_management: true } },
    { template_key: 'b', capabilities: { voice_management: false } },
    { template_key: 'c', capabilities: {} },            // 缺 voice_management → 视为不支持
    { template_key: 'd', capabilities: { voice_management: true } },
    { template_key: 'e' },                              // 完全缺 capabilities → 视为不支持
];

test('selectVoiceTabs 仅保留 voice_management=true 的组', () => {
    const got = selectVoiceTabs(GROUPS).map((g) => g.template_key);
    assert.deepEqual(got, ['a', 'd']);
});

test('selectVoiceTabs 对 undefined / 非数组输入安全返回空数组', () => {
    assert.deepEqual(selectVoiceTabs(undefined), []);
    assert.deepEqual(selectVoiceTabs(null), []);
    assert.deepEqual(selectVoiceTabs('nope'), []);
});

// ---------- firstUsableTab：默认 tab 必须「既有能力又有组件」，避免整页空白（P3）----------
const VISIBLE = [
    { template_key: 'a', capabilities: { voice_management: true } },
    { template_key: 'd', capabilities: { voice_management: true } },
];

test('firstUsableTab 返回第一个已注册组件的分组', () => {
    const components = new Set(['a', 'd']);
    const got = firstUsableTab(VISIBLE, (k) => components.has(k));
    assert.equal(got.template_key, 'a');
});

test('P3 回归：第一个可见分组未注册组件时，跳过它选下一个', () => {
    // 模拟「后端说支持、但前端还没注册组件」的未来 provider 排在首位：
    // 默认 tab 不应选它（否则整页空白），而应落到下一个有组件的。
    const visibleWithOrphan = [
        { template_key: 'future_voice', capabilities: { voice_management: true } }, // 无组件
        ...VISIBLE,
    ];
    const got = firstUsableTab(visibleWithOrphan, (k) => k === 'a' || k === 'd');
    assert.equal(got.template_key, 'a');
});

test('firstUsableTab 无任何可用组件时返回 null（而非空白 tab）', () => {
    const got = firstUsableTab(VISIBLE, () => false);
    assert.equal(got, null);
});

test('firstUsableTab 对空 / undefined 输入安全返回 null', () => {
    assert.equal(firstUsableTab([], () => true), null);
    assert.equal(firstUsableTab(undefined, () => true), null);
});
