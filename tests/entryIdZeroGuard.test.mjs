// MiniMax 组件：entry_id=0（单供应商）不能被真值判断当成「无条目」而跳过加载。
//
// 回归背景：providers 接口给每个供应商条目分配的 id 是数组索引（voice.py:55
// `item["id"] = idx`），单供应商时 id=0。JS 里 0 是 falsy，若用
// `if (!selectedEntryId.value)` / `if (newId)` 判断「是否已选」，进场、切换、
// 上传、克隆、设计等入口都会直接 return，页面永远不加载音色/文件列表。
// 修法与 StepFun 一致：用 null/undefined 判断（hasEntry）。
//
// 组件是内联 template 的 ES module、依赖 Vue 全局，无法在 node 里挂载实例；
// 这里用源码断言锁住「不得回退到真值判断」这条防线，能被 CI 的 node --test 执行。
// 运行：node --test tests/entryIdZeroGuard.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const COMPONENTS = {
    'bailian_minimax_speech_2_8.js': path.join(
        ROOT, 'pages', 'tts_studio', 'components', 'bailian_minimax_speech_2_8.js',
    ),
    'minimax_speech_2_8.js': path.join(
        ROOT, 'pages', 'tts_studio', 'components', 'minimax_speech_2_8.js',
    ),
};

// 会挡住 id=0 的裸真值判断；hasEntry 定义里的 !== null / !== undefined 不算。
const TRUTHY_GUARDS = [
    { re: /if\s*\(\s*!\s*selectedEntryId\.value\s*\)/, name: 'if (!selectedEntryId.value)' },
    { re: /if\s*\(\s*selectedEntryId\.value\s*\)/, name: 'if (selectedEntryId.value)' },
    { re: /if\s*\(\s*newId\s*\)/, name: 'if (newId)' },
    { re: /&&\s*selectedEntryId\.value\b/, name: '&& selectedEntryId.value' },
    { re: /\bnewId\s*&&/, name: 'newId &&' },
];

for (const [name, file] of Object.entries(COMPONENTS)) {
    const source = fs.readFileSync(file, 'utf-8');

    test(`${name}: 定义 null/undefined 语义的 hasEntry 守卫`, () => {
        assert.match(
            source,
            /const hasEntry\s*=\s*\(\)\s*=>[\s\S]*?selectedEntryId\.value\s*!==\s*null[\s\S]*?selectedEntryId\.value\s*!==\s*undefined/,
            'hasEntry 必须用 !== null && !== undefined 判断，不能用真值',
        );
    });

    test(`${name}: 不得有任何会挡住 id=0 的裸真值判断`, () => {
        // 去掉 hasEntry 定义本身（其 !== null && !== undefined 会命中 && 检查）
        const withoutHelper = source.replace(
            /const hasEntry\s*=\s*\(\)\s*=>[\s\S]*?selectedEntryId\.value\s*!==\s*undefined;/,
            '',
        );
        for (const { re, name: guard } of TRUTHY_GUARDS) {
            assert.doesNotMatch(
                withoutHelper,
                re,
                `仍存在 ${guard}，单供应商 id=0 时会被当成「无条目」而 return`,
            );
        }
    });

    test(`${name}: 关键入口都走 hasEntry()`, () => {
        const calls = source.match(/hasEntry\(\)/g) || [];
        // 1 处定义 + 至少 2 处调用（列表加载 guard、进场/切换/上传等入口）
        assert.ok(
            calls.length >= 3,
            `hasEntry() 调用点不足（找到 ${calls.length} 处），可能漏了加载/入口守卫`,
        );
        assert.match(
            source,
            /async function fetchVoiceList[\s\S]{0,80}?if\s*\(\s*!\s*hasEntry\(\)\s*\)\s*return/,
            'fetchVoiceList 必须先以 !hasEntry() 守卫',
        );
    });
}
