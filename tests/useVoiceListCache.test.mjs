// 音色列表前端缓存的单测（node --test，无需浏览器 / Vue）。
// 运行：node --test tests/useVoiceListCache.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
    getVoiceList,
    setVoiceList,
    voiceListCacheKey,
    clearVoiceListCache,
} from '../pages/tts_studio/composables/useVoiceListCache.js';

const A_ITEMS = [{ voice_id: 'a1' }, { voice_id: 'a2' }];
const B_ITEMS = [{ voice_id: 'b1' }];

test('未写入时 getVoiceList 返回 null（触发回源）', () => {
    assert.equal(getVoiceList({ entry_id: 999, page_size: 50 }), null);
});

test('写入后可命中，且返回的是副本而非同一引用', () => {
    const params = { entry_id: 1, page_size: 50 };
    setVoiceList(params, A_ITEMS);
    const got = getVoiceList(params);
    assert.ok(Array.isArray(got));
    assert.deepEqual(got, A_ITEMS);
    // 必须是副本：避免组件 unshift / 下标赋值污染全局缓存（P1 缓存污染）。
    assert.notEqual(got, A_ITEMS);
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

test('voiceListCacheKey 缺省字段不污染键', () => {
    assert.equal(
        voiceListCacheKey({ entry_id: 3 }),
        voiceListCacheKey({ entry_id: 3, page_size: undefined }),
    );
});

test('缓存返回的是副本，组件对数组结构的 mutate 不会污染后续命中（P1）', () => {
    const params = { entry_id: 4, page_size: 50 };
    setVoiceList(params, A_ITEMS);
    const first = getVoiceList(params);
    assert.notEqual(first, A_ITEMS); // 必须是数组级副本
    // 模拟组件对「数组本身」的直接操作（unshift / 下标赋值），不应污染缓存。
    // 注意：元素对象仍按引用共享，P1 只保证数组结构不被组件改动污染。
    first.unshift({ voice_id: 'x' });
    first[0] = { voice_id: 'mutated' };
    first.push({ voice_id: 'y' });
    // 原始缓存数组结构不受影响（仍为最初写入的 2 项）
    const again = getVoiceList(params);
    assert.deepEqual(again, [{ voice_id: 'a1' }, { voice_id: 'a2' }]);
    assert.notEqual(again, first);
});

test('键不因字段顺序变化而不同（P3 键设计脆弱）', () => {
    const a = voiceListCacheKey({ entry_id: 5, page_size: 50, voice_type: 'all' });
    const b = voiceListCacheKey({ voice_type: 'all', entry_id: 5, page_size: 50 });
    assert.equal(a, b);
    // 且二者命中同一份缓存
    setVoiceList({ page_size: 50, voice_type: 'all', entry_id: 5 }, A_ITEMS);
    assert.deepEqual(getVoiceList({ entry_id: 5, voice_type: 'all', page_size: 50 }), A_ITEMS);
});

test('clearVoiceListCache 后返回 null；按 entryId 清理只清该 entry（P2 无清理入口）', () => {
    setVoiceList({ entry_id: 1, page_size: 50 }, A_ITEMS);
    setVoiceList({ entry_id: 2, page_size: 50 }, B_ITEMS);
    assert.deepEqual(getVoiceList({ entry_id: 1, page_size: 50 }), A_ITEMS);
    // 只清 entry=1
    clearVoiceListCache(1);
    assert.equal(getVoiceList({ entry_id: 1, page_size: 50 }), null);
    assert.deepEqual(getVoiceList({ entry_id: 2, page_size: 50 }), B_ITEMS);
    // 清空全部
    clearVoiceListCache();
    assert.equal(getVoiceList({ entry_id: 2, page_size: 50 }), null);
});

test('非终态（含 DEPLOYING）不写缓存，强制回源推进状态（P2 status 定格）', () => {
    const params = { entry_id: 6, page_size: 50 };
    // 审核中条目不应被定格进缓存
    setVoiceList(params, [{ voice_id: 'd1', status: 'DEPLOYING' }]);
    assert.equal(getVoiceList(params), null);
    // 终态（OK）才写缓存
    setVoiceList(params, [{ voice_id: 'd1', status: 'OK' }]);
    assert.deepEqual(getVoiceList(params), [{ voice_id: 'd1', status: 'OK' }]);
});

test('setVoiceList 存副本：调用方就地 unshift / 下标赋值不污染缓存（P2 脏数组残留）', () => {
    const params = { entry_id: 8, page_size: 50 };
    const source = [{ voice_id: 'a1' }, { voice_id: 'a2' }];
    setVoiceList(params, source);
    // 模拟创建音色后组件侧 mutate（upsertVoiceItem 对 voiceList.value 的操作）：
    // 新条目 unshift + 既有条目整条替换（list[idx] = {...}）。
    source.unshift({ voice_id: 'new', status: 'DEPLOYING' });
    source[1] = { voice_id: 'a1', status: 'OK' };
    // 缓存应是写入时的快照，不被调用方后续就地改动污染
    assert.deepEqual(getVoiceList(params), [{ voice_id: 'a1' }, { voice_id: 'a2' }]);
});
