// 音色管理视图的 tab 选择逻辑（纯函数，与 Vue 解耦，便于单测）。
//
// 后端 /providers 返回的供应商分组统一在此筛选 / 排序，前端不再把这套判断
// 散落在 app.js 的 computed 与事件回调里；app.js 仅负责消费结果。

/**
 * 从后端 /providers 返回的供应商分组中，筛选出「支持音色管理」的组。
 *
 * 可见性由后端 capabilities.voice_management 决定（单一数据源），不依赖前端硬编码。
 *
 * @param {Array<{template_key:string, capabilities?:{voice_management?:boolean}}>} groups
 * @returns {Array} 支持音色管理的供应商分组（原顺序）
 */
export function selectVoiceTabs(groups) {
    return (Array.isArray(groups) ? groups : []).filter(
        (g) => g && g.capabilities?.voice_management,
    );
}

/**
 * 在可见供应商分组中，挑第一个「在前端注册了 UI 组件」的组作为默认选中 tab。
 *
 * 避免默认选中一个后端标记为支持音色管理、但前端尚未注册组件的供应商，
 * 否则整页音色管理视图会落到空白组件（P3 回归点）。
 *
 * @param {Array<{template_key:string}>} visibleGroups 可见分组（通常来自 selectVoiceTabs）
 * @param {(templateKey:string) => boolean} hasComponent 判断某 template_key 是否已注册组件
 * @returns {object|null} 第一个可用分组；无可用分组时返回 null
 */
export function firstUsableTab(visibleGroups, hasComponent) {
    const list = visibleGroups || [];
    for (const g of list) {
        if (hasComponent(g.template_key)) {
            return g;
        }
    }
    return null;
}
