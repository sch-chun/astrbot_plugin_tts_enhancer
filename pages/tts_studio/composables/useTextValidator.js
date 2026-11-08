// 统一的文本字数校验工具
//
// 计数规则：汉字（U+4E00 ~ U+9FFF）按 2 字符计算，其余字符按 1 字符计算
//
// 统一报错文案：
//   必填未填 → `{label}不能为空`
//   低于下限 → `{label}不能少于 {min} 字符（当前 {count} 字符）`
//   超出上限 → `{label}不能超过 {max} 字符（当前 {count} 字符）`

/** 统计文本字符数（汉字按 2 字符，其他按 1 字符） */
export function countChars(text) {
    if (!text) return 0;
    let count = 0;
    for (const char of text) {
        const code = char.charCodeAt(0);
        if (code >= 0x4E00 && code <= 0x9FFF) {
            count += 2;
        } else {
            count += 1;
        }
    }
    return count;
}

/**
 * 校验文本长度
 * @param {string} text
 * @param {Object}  [options]
 * @param {string}  [options.label='文本']   字段名，用于错误提示
 * @param {number}  [options.min]            最小字符数（含）
 * @param {number}  [options.max]            最大字符数（含）
 * @param {boolean} [options.required=false] 是否必填（为空时报错）
 * @returns {{ valid: boolean, error: string, count: number }}
 */
export function validateText(text, options = {}) {
    const {
        label = '文本',
        min,
        max,
        required = false,
    } = options;

    const raw = typeof text === 'string' ? text : (text == null ? '' : String(text));
    const value = raw.trim();
    const count = countChars(raw);

    // 空值处理
    if (!value) {
        if (required) {
            return { valid: false, error: `${label}不能为空`, count };
        }
        // 非必填且为空 → 不参与长度校验，视为合法
        return { valid: true, error: '', count };
    }

    if (typeof min === 'number' && count < min) {
        return {
            valid: false,
            error: `${label}不能少于 ${min} 字符（当前 ${count} 字符）`,
            count,
        };
    }

    if (typeof max === 'number' && count > max) {
        return {
            valid: false,
            error: `${label}不能超过 ${max} 字符（当前 ${count} 字符）`,
            count,
        };
    }

    return { valid: true, error: '', count };
}
