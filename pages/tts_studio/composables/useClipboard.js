// composables/useClipboard.js

/**
 * 剪贴板复制 composable
 * 提供两种语义化方法：copyText（复制文本）/ copyLink（复制链接，提示手动粘贴）
 *
 * @param {Function} showSuccess  成功提示函数（一般传 useToast 的 showSuccess）
 * @param {Function} showError    失败提示函数（一般传 useToast 的 showError）
 * @param {Object}   options
 * @param {string}   options.errorMessage   失败提示文案，默认 '复制失败，请手动复制'
 * @param {string}   options.linkMessage    复制链接成功时的提示，默认 '链接已复制，请手动粘贴到浏览器地址栏访问'
 * @param {string}   options.textPrefix     copyText 成功提示前缀，默认 '已复制: '
 */
export function useClipboard(showSuccess, showError, options = {}) {
    const {
        errorMessage = '复制失败，请手动复制',
        linkMessage = '链接已复制，请手动粘贴到浏览器地址栏访问',
        textPrefix = '已复制: ',
    } = options;

    /**
     * 底层写入剪贴板，不负责提示
     * @param {string} text
     * @returns {boolean} 是否成功
     */
    function writeToClipboard(text) {
        let success = false;
        let input = null;
        try {
            input = document.createElement('input');
            input.value = text;

            // 确保元素在视口内但不可见，避免页面滚动
            input.style.position = 'fixed';
            input.style.top = '-9999px';
            input.style.left = '-9999px';
            document.body.appendChild(input);
            input.select();

            // 针对移动端 iOS 的兼容
            input.setSelectionRange(0, 99999);
            success = document.execCommand('copy');
        } catch (e) {
            console.error('复制失败:', e);
        } finally {
            // 保证即使 execCommand 抛异常也能清理临时节点
            if (input && input.parentNode) {
                input.parentNode.removeChild(input);
            }
        }
        return success;
    }

    /**
     * 复制普通文本
     * 成功 → 弹 "已复制: {text}"
     * 失败 → 弹 errorMessage
     *
     * @param {string} text
     * @param {Object} [opts]
     * @param {string} [opts.successMsg]  覆盖默认成功文案
     * @param {string} [opts.errorMsg]    覆盖默认失败文案
     * @returns {boolean}
     */
    function copyText(text, opts = {}) {
        const ok = writeToClipboard(text);
        if (ok) {
            showSuccess(opts.successMsg ?? (textPrefix + text));
        } else {
            showError(opts.errorMsg ?? errorMessage);
        }
        return ok;
    }

    /**
     * 复制链接（适合需要用户手动粘贴到浏览器地址栏的场景）
     * 成功 → 弹 linkMessage
     * 失败 → 弹 errorMessage
     *
     * @param {string} url
     * @param {Object} [opts]
     * @param {string} [opts.successMsg]  覆盖默认成功文案
     * @param {string} [opts.errorMsg]    覆盖默认失败文案
     * @returns {boolean}
     */
    function copyLink(url, opts = {}) {
        const ok = writeToClipboard(url);
        if (ok) {
            showSuccess(opts.successMsg ?? linkMessage);
        } else {
            showError(opts.errorMsg ?? errorMessage);
        }
        return ok;
    }

    return { copyText, copyLink };
}
