// 音色列表前端缓存（模块级单例，跨组件实例共享）。
//
// 背景：切换顶层视图（音色管理 / 合成记录）或供应商标签页时，对应组件会重新挂载，
// 进而重新请求 /voice/list。本缓存以「请求参数签名」为键保留上一次结果，命中即直接
// 回填、跳过网络请求，避免频繁重复加载。
//
// 失效策略：
//  1. 变更操作（创建 / 删除 / 预览激活 / 手动刷新）通过 force 标志绕过缓存并回源，
//     回源成功后若结果为终态则覆盖缓存。
//  2. 非终态（含 DEPLOYING 的审核中条目）不写缓存 —— 音色状态以 /voice/list 为唯一来源，
//     DEPLOYING → OK / UNDEPLOYED 靠它推进，一旦定格缓存用户会一直看到旧状态。
//  3. TTL（默认 60s）兜底：即便终态也会被定期回源，防供应商侧状态在 OK 之后又变。
//  4. clearVoiceListCache()：providers 列表重新加载 / entry 删除时清理残留。
//
// 健壮性：
//  - getVoiceList 返回数组浅拷贝，避免组件 unshift / 下标赋值直接污染全局缓存。
//  - 键由「影响结果的全部字段按 key 排序后序列化」生成，字段顺序变化不影响命中，
//    将来新增 cursor / page 等字段也会被纳入键（不再被静默忽略）。

const CACHE_TTL_MS = 60 * 1000; // 60s 兜底 TTL

// 非终态状态：音色仍在审核 / 处理中，状态会随 /voice/list 推进。
const NON_TERMINAL_STATUS = new Set(['DEPLOYING']);

const cache = new Map(); // key -> { items, expireAt }

export function voiceListCacheKey(params) {
    const sorted = {};
    for (const k of Object.keys(params || {}).sort()) {
        if (params[k] !== undefined) sorted[k] = params[k];
    }
    return 'vl|' + JSON.stringify(sorted);
}

function hasNonTerminal(items) {
    return Array.isArray(items) && items.some(
        (it) => it && NON_TERMINAL_STATUS.has(it.status),
    );
}

export function getVoiceList(params) {
    const key = voiceListCacheKey(params);
    const hit = cache.get(key);
    if (!hit) return null;
    // TTL 过期视为未命中，触发回源
    if (Date.now() >= hit.expireAt) {
        cache.delete(key);
        return null;
    }
    // 返回浅拷贝，避免组件 unshift / 下标赋值污染全局缓存
    return [...hit.items];
}

export function setVoiceList(params, items) {
    // 非终态不写缓存：DEPLOYING 等过渡状态会随 /voice/list 推进，
    // 一旦缓存定格，用户将一直看到旧状态。
    if (hasNonTerminal(items)) return;
    const key = voiceListCacheKey(params);
    // 存副本而非原引用：组件拿到 items 后可能就地 mutate（如创建音色后
    // upsertVoiceItem 对 voiceList.value 做 unshift / 下标赋值），若缓存持有
    // 同一数组引用，脏改动会写入缓存并残留到 TTL（60s）才自愈。
    cache.set(key, { items: [...items], expireAt: Date.now() + CACHE_TTL_MS });
}

// 清空缓存。不传 entryId 清空全部；传 entryId 仅清该 entry（entry 删除后残留）。
export function clearVoiceListCache(entryId) {
    if (entryId === undefined) {
        cache.clear();
        return;
    }
    const target = String(entryId);
    for (const key of [...cache.keys()]) {
        try {
            const obj = JSON.parse(key.slice(3)); // 去掉前缀 'vl|'
            if (obj && String(obj.entry_id) === target) cache.delete(key);
        } catch (_) {
            // 忽略因格式异常无法解析的键
        }
    }
}
