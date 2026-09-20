// 全局单例音频播放管理器
// 所有供应商组件共享同一个 volume / currentPlayingId / 播放实例

const { ref, watch } = Vue;

// ---------- 模块级单例状态（所有调用方共享） ----------
const volume = ref(0.8);              // 全局音量 0~1
const currentAudio = ref(null);       // 当前 Audio 实例
const currentPlayingId = ref(null);   // 当前播放的标识（用于按钮状态 / toggle）

let endCleanup = null;                // 播放停止/结束时执行的清理（如 revokeObjectURL）

function runCleanup() {
    if (endCleanup) {
        try { endCleanup(); } catch (e) { console.warn('音频清理失败:', e); }
        endCleanup = null;
    }
}

/** 停止当前播放（若有） */
function stopAudio() {
    const audio = currentAudio.value;
    if (audio) {
        audio.onended = null;
        try { audio.pause(); } catch (_) {}
        audio.src = '';
        currentAudio.value = null;
    }
    currentPlayingId.value = null;
    runCleanup();
}

/**
 * 播放音频
 * @param {string} url  音频 URL（blob: 或 http(s):）
 * @param {string} id   播放标识；同一 id 再次调用会切换为「停止」
 * @param {Object} [opts]
 * @param {Function} [opts.onEnd]   自然结束回调
 * @param {Function} [opts.onError] 播放失败回调 (error) => void
 * @param {Function} [opts.cleanup] 停止/结束时清理函数（如 URL.revokeObjectURL）
 * @returns {boolean} 是否开始播放（false 表示被 toggle 停止）
 */
function playAudio(url, id, opts = {}) {
    const { onEnd, onError, cleanup } = opts;

    // 点击同一个标识 → 停止（toggle）
    if (currentPlayingId.value === id) {
        stopAudio();
        return false;
    }

    stopAudio();

    const audio = new Audio(url);
    audio.volume = volume.value;
    currentAudio.value = audio;
    currentPlayingId.value = id;
    endCleanup = cleanup || null;

    audio.onended = () => {
        currentAudio.value = null;
        currentPlayingId.value = null;
        runCleanup();
        if (onEnd) onEnd();
    };

    const p = audio.play();
    if (p && typeof p.catch === 'function') {
        p.catch((e) => {
            stopAudio();
            if (onError) onError(e);
            else console.error('播放失败:', e);
        });
    }
    return true;
}

/** 指定 id 是否正在播放 */
function isPlaying(id) {
    return currentPlayingId.value === id;
}

// 音量变化实时应用到正在播放的音频
watch(volume, (v) => {
    if (currentAudio.value) currentAudio.value.volume = v;
});

export function useAudioManager() {
    return {
        volume,
        currentAudio,
        currentPlayingId,
        playAudio,
        stopAudio,
        isPlaying,
    };
}
