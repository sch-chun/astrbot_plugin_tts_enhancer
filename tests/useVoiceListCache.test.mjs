// 音色列表前端缓存的单测（node --test，无需浏览器 / Vue）。
// 运行：node --test tests/useVoiceListCache.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { getVoiceList, setVoiceList, voiceListCacheKey } from '../pages/tts_studio/composables/useVoiceListCache.js';

const A_ITEMS = [{ voice_id: 'a1' }, { voice_id: 'a2' }];
const B_ITEMS = [{ voice_id: 'b1' }];

test('未写入时 getVoiceList 返回 null（触发回源）', () => {
    assert.equal(getVoiceList({ entry_id: 999, page_size: 50 }), null);
});

test('写入后可命中，且返回同一份引用', () => {
    const params = { entry_id: 1, page_size: 50 };
    setVoiceList(params, A_ITEMS);
    const got = getVoiceList(params);
    assert.ok(Array.isArray(got));
    assert.deepEqual(got, A_ITEMS);
    assert.equal(got, A_ITEMS); // 同一引用，避免无谓拷贝
});

test('不同 entry_id 的缓存互相隔离', () => {
    setVoiceList({ entry_id: 1, page_size: 50 }, A_ITEMS);
    setVoiceList({ entry_id: 2, page_size: 50 }, B_ITEMS);
    assert.deepEqual(getVoiceList({ entry_id: 1, page_size: 50 }), A_ITEMS);
    assert.deepEqual(getVoiceList({ entry_id: 2, page_size: 50 }), B_ITEMS);
});

test('page_size 与 voice_type 作为区分符，百炼与 MiniMax 列表不串味', () => {
    // 同一 entry_id，但请求参数不同：百炼用 page_size、MiniMax 用 voice_type='all'。
    setVoiceList({ entry_id: 7, page_size: 50 }, A_ITEMS);
    setVoiceList({ entry_id: 7, voice_type: 'all' }, B_ITEMS);
    assert.deepEqual(getVoiceList({ entry_id: 7, page_size: 50 }), A_ITEMS);
    assert.deepEqual(getVoiceList({ entry_id: 7, voice_type: 'all' }), B_ITEMS);
    // 键确实不同
    assert.notEqual(
        voiceListCacheKey({ entry_id: 7, page_size: 50 }),
        voiceListCacheKey({ entry_id: 7, voice_type: 'all' }),
    );
});

test('voiceListCacheKey 缺省字段不污染键（page_size 与 voice_type 缺一皆为空串）', () => {
    // 二者 discriminator 都为空串时应落到同一键——但真实调用不会同时缺省，这里只校验键构造稳健。
    assert.equal(
        voiceListCacheKey({ entry_id: 3 }),
        voiceListCacheKey({ entry_id: 3, page_size: undefined }),
    );
});
