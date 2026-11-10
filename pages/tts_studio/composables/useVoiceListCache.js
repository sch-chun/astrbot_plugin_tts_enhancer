// 音色列表前端缓存（模块级单例，跨组件实例共享）。
//
// 背景：切换顶层视图（音色管理 / 合成记录）或供应商标签页时，对应组件会重新挂载，
// 进而重新请求 /voice/list。本缓存以「请求参数签名」为键保留上一次结果，命中即直接
// 回填、跳过网络请求，避免频繁重复加载。
//
// 失效策略：删除 / 创建 / 预览激活 / 手动刷新等「相关操作」通过 force 标志绕过缓存并
// 回源，回源成功后自动用最新数据覆盖缓存；缓存默认不随时间过期（仅按需刷新），
// 符合「切标签不重复加载，但操作后要刷新」的预期。

const cache = new Map(); // key -> items[]

// 仅取影响返回结果的字段，避免无关字段污染键导致缓存永不命中。
export function voiceListCacheKey(params) {
    const entryId = params && params.entry_id;
    const discriminator = params && (params.voice_type ?? params.page_size ?? '');
    return `vl:${entryId}:${discriminator}`;
}

export function getVoiceList(params) {
    const key = voiceListCacheKey(params);
    return cache.has(key) ? cache.get(key) : null;
}

export function setVoiceList(params, items) {
    cache.set(voiceListCacheKey(params), items);
}
