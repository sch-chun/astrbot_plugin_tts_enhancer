// 组件级 i18n 自检 composable
//
// 每个前端子组件（BailianSpeechSynthesizer / VoicePreviewModal / DeleteConfirmModal 等）
// 在 setup() 中调用 useComponentI18n(bridge, defs)，返回 reactive 的 t 映射：
//     t[key] = bridge.t('views.tts_studio.components.' + key, defs[key])
//
// 与 app.js 的 applyI18n 同一套路：首次调用即填充，并注册 bridge.onContext 在
// WebUI 切换语言时实时刷新；组件卸载时反注册，避免泄漏（bridge.onContext 会返回
// 反注册函数）。
//
// defs 中的值是 zh-CN 兜底文案，既作为 fallback，也作为生成器里 zh-CN 段的来源。

const { reactive, onUnmounted } = Vue;

export function useComponentI18n(bridge, defs, prefix = 'views.tts_studio.components') {
    // 先以 zh-CN 兜底填充，避免首帧出现空白
    const t = reactive(Object.assign({}, defs));

    function apply() {
        if (!bridge || typeof bridge.t !== 'function') return;
        for (const key of Object.keys(defs)) {
            t[key] = bridge.t(prefix + '.' + key, defs[key]);
        }
    }

    apply();

    let off = null;
    if (bridge && typeof bridge.onContext === 'function') {
        off = bridge.onContext(apply);
    }

    onUnmounted(() => {
        if (typeof off === 'function') off();
    });

    return t;
}
