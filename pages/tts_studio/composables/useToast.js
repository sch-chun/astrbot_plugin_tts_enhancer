const { ref, onUnmounted } = Vue;

/**
 * Toast 通知 composable
 * @param {Object}  options
 * @param {number}  options.duration      显示时长（ms），默认 3000
 * @param {boolean} options.pauseOnHover  悬停时暂停倒计时，默认 true
 * @param {boolean} options.resetOnLeave  离开时重置为完整时长（true）还是续接剩余时间（false），默认 true
 */
export function useToast(options = {}) {
    const {
        duration = 3000,
        pauseOnHover = true,
        resetOnLeave = true,
    } = options;

    const toastMessage = ref('');
    const toastVisible = ref(false);
    const toastType = ref('success');

    let timer = null;       // setTimeout 句柄
    let startedAt = 0;      // 本轮计时起点
    let remaining = duration; // 剩余毫秒
    let paused = false;     // 是否处于暂停态
    let hovering = false;   // 鼠标是否停在 toast 上

    function clearTimer() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
    }

    /** 以 ms 为时长重新开始计时 */
    function startTimer(ms) {
        clearTimer();
        remaining = ms;
        startedAt = Date.now();
        paused = false;
        timer = setTimeout(hide, ms);
    }

    function hide() {
        clearTimer();
        paused = false;
        toastVisible.value = false;
        toastMessage.value = '';
    }

    function showToast(msg, type = 'success') {
        toastMessage.value = msg;
        toastType.value = type;
        toastVisible.value = true;

        if (pauseOnHover && hovering) {

            // 鼠标仍停留在 toast 上：先不启动倒计时，等移开再开始
            clearTimer();
            remaining = duration;
            startedAt = Date.now();
            paused = true;
        } else {

            // 每次调用都重置为完整时长
            startTimer(duration);
        }
    }

    const showSuccess = (msg) => showToast(msg, 'success');
    const showError   = (msg) => showToast(msg, 'error');

    // -------- 鼠标交互 --------
    function onToastMouseEnter() {
        hovering = true;
        if (!pauseOnHover || !toastVisible.value || paused) return;
        clearTimer();

        // 扣掉已经走过的时间
        remaining = Math.max(0, remaining - (Date.now() - startedAt));
        paused = true;
    }

    function onToastMouseLeave() {
        hovering = false;
        if (!pauseOnHover || !paused) return;

        // 按需求：离开后重置为完整时长；若想续接剩余时间则传 resetOnLeave: false
        startTimer(resetOnLeave ? duration : Math.max(remaining, 0));
    }

    onUnmounted(() => {
        clearTimer();
    });

    return {

        // 状态
        toastMessage,
        toastVisible,
        toastType,

        // 方法
        showToast,
        showSuccess,
        showError,
        hideToast: hide,

        // 悬停事件（绑定到 toast 元素上）
        onToastMouseEnter,
        onToastMouseLeave,
    };
}
