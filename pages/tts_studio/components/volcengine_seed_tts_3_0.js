const { ref, computed, watch, onMounted } = Vue;

import { useToast } from '../composables/useToast.js';
import { useClipboard } from '../composables/useClipboard.js';
import { useComponentI18n } from '../composables/useComponentI18n.js';
import VoicePreviewModal from './common/voice_preview_modal.js';

const AUDIO_FORMATS = ['wav', 'mp3', 'ogg', 'm4a', 'aac', 'pcm'];
const MAX_AUDIO_BYTES = 10 * 1024 * 1024;
const CLONE_LANGUAGES = [
    { id: 0, code: 'zh', name: '中文（含粤语及方言）', promptTextRequired: false, prosodySupported: true },
    { id: 1, code: 'en', name: '英语（美国）', promptTextRequired: false, prosodySupported: true },
    { id: 2, code: 'ja', name: '日语（日本）', promptTextRequired: false, prosodySupported: true },
    { id: 3, code: 'es', name: '西班牙语（西班牙）', promptTextRequired: false, prosodySupported: true },
    { id: 4, code: 'id', name: '印度尼西亚语（印度尼西亚）', promptTextRequired: false, prosodySupported: true },
    { id: 5, code: 'pt', name: '葡萄牙语（葡萄牙）', promptTextRequired: false, prosodySupported: true },
    { id: 6, code: 'de', name: '德语（德国）', promptTextRequired: false, prosodySupported: true },
    { id: 7, code: 'fr', name: '法语（法国）', promptTextRequired: false, prosodySupported: true },
    { id: 8, code: 'ko', name: '韩语（韩国）', promptTextRequired: false, prosodySupported: true },
    { id: 9, code: 'it', name: '意大利语（意大利）', promptTextRequired: false, prosodySupported: true },
    { id: 10, code: 'th', name: '泰语（泰国）', promptTextRequired: false, prosodySupported: true },
    { id: 11, code: 'vi', name: '越南语（越南）', promptTextRequired: false, prosodySupported: true },
    { id: 12, code: 'ru', name: '俄语（俄罗斯）', promptTextRequired: false, prosodySupported: true },
    { id: 13, code: 'fil', name: '菲律宾语（菲律宾）', promptTextRequired: false, prosodySupported: true },
    { id: 14, code: 'ms', name: '马来语（马来西亚）', promptTextRequired: false, prosodySupported: true },
    { id: 15, code: 'ar', name: '阿拉伯语（沙特阿拉伯）', promptTextRequired: false, prosodySupported: true },
    { id: 16, code: 'es-MX', name: '西班牙语（墨西哥）', promptTextRequired: false, prosodySupported: true },
    { id: 17, code: 'pt-BR', name: '葡萄牙语（巴西）', promptTextRequired: false, prosodySupported: true },
    { id: 18, code: 'nl', name: '荷兰语（荷兰）', promptTextRequired: false, prosodySupported: true },
    { id: 19, code: 'pl', name: '波兰语（波兰）', promptTextRequired: false, prosodySupported: true },
    { id: 20, code: 'tr', name: '土耳其语（土耳其）', promptTextRequired: false, prosodySupported: true },
    { id: 21, code: 'sv', name: '瑞典语（瑞典）', promptTextRequired: true, prosodySupported: false },
    { id: 22, code: 'af', name: '南非荷兰语（南非）', promptTextRequired: true, prosodySupported: false },
    { id: 23, code: 'az', name: '阿塞拜疆语（阿塞拜疆）', promptTextRequired: true, prosodySupported: false },
    { id: 24, code: 'bg', name: '保加利亚语（保加利亚）', promptTextRequired: true, prosodySupported: false },
    { id: 25, code: 'bn', name: '孟加拉语（孟加拉国）', promptTextRequired: false, prosodySupported: true },
    { id: 26, code: 'ca', name: '加泰罗尼亚语（西班牙）', promptTextRequired: true, prosodySupported: false },
    { id: 27, code: 'cs', name: '捷克语（捷克）', promptTextRequired: true, prosodySupported: false },
    { id: 28, code: 'da', name: '丹麦语（丹麦）', promptTextRequired: true, prosodySupported: false },
    { id: 29, code: 'el', name: '希腊语（希腊）', promptTextRequired: false, prosodySupported: true },
    { id: 30, code: 'et', name: '爱沙尼亚语（爱沙尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 31, code: 'fa', name: '波斯语（伊朗）', promptTextRequired: true, prosodySupported: false },
    { id: 32, code: 'fi', name: '芬兰语（芬兰）', promptTextRequired: true, prosodySupported: false },
    { id: 33, code: 'he', name: '希伯来语（以色列）', promptTextRequired: true, prosodySupported: false },
    { id: 34, code: 'hi', name: '印地语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 35, code: 'hr', name: '克罗地亚语（克罗地亚）', promptTextRequired: true, prosodySupported: false },
    { id: 36, code: 'hu', name: '匈牙利语（匈牙利）', promptTextRequired: true, prosodySupported: false },
    { id: 37, code: 'is', name: '冰岛语（冰岛）', promptTextRequired: true, prosodySupported: false },
    { id: 38, code: 'kk', name: '哈萨克语（哈萨克斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 39, code: 'km', name: '高棉语（柬埔寨）', promptTextRequired: true, prosodySupported: false },
    { id: 40, code: 'lt', name: '立陶宛语（立陶宛）', promptTextRequired: true, prosodySupported: false },
    { id: 41, code: 'lv', name: '拉脱维亚语（拉脱维亚）', promptTextRequired: true, prosodySupported: false },
    { id: 42, code: 'my', name: '缅甸语（缅甸）', promptTextRequired: true, prosodySupported: false },
    { id: 43, code: 'no', name: '挪威语（挪威）', promptTextRequired: true, prosodySupported: false },
    { id: 44, code: 'pa', name: '旁遮普语（巴基斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 45, code: 'ro', name: '罗马尼亚语（罗马尼亚）', promptTextRequired: false, prosodySupported: true },
    { id: 46, code: 'sk', name: '斯洛伐克语（斯洛伐克）', promptTextRequired: true, prosodySupported: false },
    { id: 47, code: 'sl', name: '斯洛文尼亚语（斯洛文尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 48, code: 'sq', name: '阿尔巴尼亚语（阿尔巴尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 49, code: 'sr', name: '塞尔维亚语（塞尔维亚）', promptTextRequired: true, prosodySupported: false },
    { id: 50, code: 'sw', name: '斯瓦希里语（肯尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 51, code: 'uk', name: '乌克兰语（乌克兰）', promptTextRequired: false, prosodySupported: true },
    { id: 52, code: 'ur', name: '乌尔都语（巴基斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 53, code: 'uz', name: '乌兹别克语（乌兹别克斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 54, code: 'am', name: '阿姆哈拉语（埃塞俄比亚）', promptTextRequired: true, prosodySupported: false },
    { id: 55, code: 'as', name: '阿萨姆语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 56, code: 'ast', name: '阿斯图里亚斯语（西班牙）', promptTextRequired: true, prosodySupported: false },
    { id: 57, code: 'be', name: '白俄罗斯语（白俄罗斯）', promptTextRequired: true, prosodySupported: false },
    { id: 58, code: 'bs', name: '波斯尼亚语（波斯尼亚和黑塞哥维那）', promptTextRequired: true, prosodySupported: false },
    { id: 59, code: 'ceb', name: '宿务语（菲律宾）', promptTextRequired: true, prosodySupported: false },
    { id: 60, code: 'ckb', name: '索拉尼库尔德语（伊拉克）', promptTextRequired: true, prosodySupported: false },
    { id: 61, code: 'cy', name: '威尔士语（英国）', promptTextRequired: true, prosodySupported: false },
    { id: 62, code: 'en-GB', name: '英语（英国）', promptTextRequired: false, prosodySupported: false },
    { id: 63, code: 'fuv', name: '尼日利亚富拉语（尼日利亚）', promptTextRequired: true, prosodySupported: false },
    { id: 64, code: 'gl', name: '加利西亚语（西班牙）', promptTextRequired: true, prosodySupported: false },
    { id: 65, code: 'gu', name: '古吉拉特语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 66, code: 'ha', name: '豪萨语（尼日利亚）', promptTextRequired: true, prosodySupported: false },
    { id: 67, code: 'hy', name: '亚美尼亚语（亚美尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 68, code: 'ig', name: '伊博语（尼日利亚）', promptTextRequired: true, prosodySupported: false },
    { id: 69, code: 'jv', name: '爪哇语（印度尼西亚）', promptTextRequired: true, prosodySupported: false },
    { id: 70, code: 'ka', name: '格鲁吉亚语（格鲁吉亚）', promptTextRequired: true, prosodySupported: false },
    { id: 71, code: 'kam', name: '坎巴语（肯尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 72, code: 'kea', name: '佛得角克里奥尔语（佛得角）', promptTextRequired: true, prosodySupported: false },
    { id: 73, code: 'kn', name: '卡纳达语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 74, code: 'ky', name: '吉尔吉斯语（吉尔吉斯斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 75, code: 'lb', name: '卢森堡语（卢森堡）', promptTextRequired: true, prosodySupported: false },
    { id: 76, code: 'lg', name: '卢干达语（乌干达）', promptTextRequired: true, prosodySupported: false },
    { id: 77, code: 'ln', name: '林加拉语（刚果民主共和国）', promptTextRequired: true, prosodySupported: false },
    { id: 78, code: 'lo', name: '老挝语（老挝）', promptTextRequired: true, prosodySupported: false },
    { id: 79, code: 'luo', name: '卢奥语（肯尼亚）', promptTextRequired: true, prosodySupported: false },
    { id: 80, code: 'mi', name: '毛利语（新西兰）', promptTextRequired: true, prosodySupported: false },
    { id: 81, code: 'mk', name: '马其顿语（马其顿）', promptTextRequired: true, prosodySupported: false },
    { id: 82, code: 'ml', name: '马拉雅拉姆语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 83, code: 'mn', name: '蒙古语（蒙古）', promptTextRequired: true, prosodySupported: false },
    { id: 84, code: 'mr', name: '马拉地语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 85, code: 'mt', name: '马耳他语（马耳他）', promptTextRequired: true, prosodySupported: false },
    { id: 86, code: 'ne', name: '尼泊尔语（尼泊尔）', promptTextRequired: false, prosodySupported: true },
    { id: 87, code: 'nso', name: '北索托语（南非）', promptTextRequired: true, prosodySupported: false },
    { id: 88, code: 'ny', name: '齐切瓦语（马拉维）', promptTextRequired: true, prosodySupported: false },
    { id: 89, code: 'oc', name: '奥克语（法国）', promptTextRequired: true, prosodySupported: false },
    { id: 90, code: 'ory', name: '奥里亚语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 91, code: 'ps', name: '普什图语（巴基斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 92, code: 'sd', name: '信德语（巴基斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 93, code: 'sn', name: '修纳语（津巴布韦）', promptTextRequired: true, prosodySupported: false },
    { id: 94, code: 'ta', name: '泰米尔语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 95, code: 'te', name: '泰卢固语（印度）', promptTextRequired: true, prosodySupported: false },
    { id: 96, code: 'tg', name: '塔吉克语（塔吉克斯坦）', promptTextRequired: true, prosodySupported: false },
    { id: 97, code: 'umb', name: '乌姆本杜语（安哥拉）', promptTextRequired: true, prosodySupported: false },
    { id: 98, code: 'wo', name: '沃洛夫语（塞内加尔）', promptTextRequired: true, prosodySupported: false },
    { id: 99, code: 'xh', name: '科萨语（南非）', promptTextRequired: true, prosodySupported: false },
    { id: 100, code: 'yo', name: '约鲁巴语（尼日利亚）', promptTextRequired: true, prosodySupported: false },
    { id: 118, code: 'zu', name: '祖鲁语（南非）', promptTextRequired: true, prosodySupported: false },
];
const CUSTOM_SPEAKER_ID_RE = /^[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]$/;
const CUSTOM_SPEAKER_RESERVED_RE = /^(?:BV|(?:s|icl|mix|dit|wvae|moon|mercury|venus|earth|mars|jupiter|saturn|uranus|neptune|pluto|umm)_)/i;
const CUSTOM_SPEAKER_SUFFIX_RE = /_(?:bigtts|bigtts_cc|tob|cs_tob|streaming)$/i;
const I18N_DEFS = {
    authConfig: '认证配置',
    authConfigHint: '选择用于复刻和状态查询的认证配置。',
    officialVoiceList: '官方 Seed 3.0 音色列表',
    voiceDesign: '前往官方音色设计',
    cloneTitle: 'Seed 3.0 音色复刻',
    feeTip: '已有音色 ID 会复用账号下已购买或获赠的槽位，不收取槽位费；自定义 ID 仅限后付费，首次正式合成时收取槽位费。试听音色 7 天内未正式合成会被删除；试听文本与正式合成都产生合成费用。',
    existingIdHint: '复用已有槽位，不收取槽位费；ID 需属于当前账号。',
    customIdHint: '仅限后付费；首次正式合成收取槽位费，请先确认试听效果。',
    feeConfirm: '我已了解自定义 ID 首次正式合成会收取槽位费',
    idMode: '音色 ID 方式',
    idModeHint: '已有音色 ID 复用槽位；自定义 ID 仅限后付费。',
    existingId: '已有音色 ID',
    customId: '自定义 ID（仅后付费）',
    speakerId: '已有音色 ID',
    customSpeakerId: '自定义音色 ID',
    audioFile: '复刻音频',
    seedAudioHint: '10–60 秒，不超过 10 MB；支持 wav/mp3/ogg/m4a/aac/pcm。PCM 必须为 24 kHz 单声道。',
    language: '复刻语种',
    languageHint: '中文、粤语及中文方言共用编号 0，已合并；韵律美化仅适用于标准中文。',
    promptText: '音源转写文本',
    promptTextRequired: '该语种必须填写与录音一致的音源转写文本。',
    promptTextOptional: '该语种可选填音源转写文本；留空使用自动转写。',
    prosodyBoost: '韵律美化',
    prosodyHint: '开启后由模型优化语调、节奏与停顿；仅支持的语种显示。',
    demoText: '试听文本',
    demoTextHint: '可选，用于生成试听音频；填写时长度为 4–300 个字符。',
    audioDenoise: '音频降噪',
    audioDenoiseHint: '降低录音中的环境噪声，适合非安静环境录制的音频。',
    volumeNormalization: '音量归一化',
    volumeNormalizationHint: '自动平衡音频音量，减少不同录音之间的音量差异。',
    submit: '提交复刻',
    submitting: '提交中...',
    resultTitle: '复刻结果',
    voiceId: 'Voice ID',
    queryId: '查询音色 ID',
    queryIdHint: '输入已有音色 ID 或自定义 ID 查询复刻状态。',
    query: '查询状态',
    querying: '查询中...',
    status: '状态',
    ready: '可合成',
    pending: '处理中',
    notFound: '未找到',
    unknownStatus: '未知状态',
    demoAudio: '试听音频',
    copyBtn: '复制',
    copyLink: '复制链接',
    seedPreviewBtn: '合成预览',
    errNoEntry: '请先选择认证配置',
    errNoFile: '请选择音频文件',
    errNoSpeakerId: '请填写音色 ID',
    errFeeConfirm: '请先确认自定义音色的槽位费',
    errDemoText: '试听文本长度必须在 4–300 个字符之间',
    errAudioFormat: '不支持的音频格式',
    errAudioSize: '音频文件不能超过 10 MB',
    errAudioDuration: '音频时长必须在 10–60 秒之间',
    errAudioRead: '读取音频失败',
    errPcmData: 'PCM 数据不完整，必须为 16 bit 单声道数据',
    errCustomId: '自定义音色 ID 不符合命名规则',
    errLanguage: '请选择有效的复刻语种',
    errPromptText: '该语种必须填写音源转写文本',
    errCreate: '复刻失败：',
    errQuery: '查询失败：',
};

function formatBytes(bytes) {
    return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}

function getDuration(buffer, format) {
    if (format === 'pcm') return buffer.byteLength / (24000 * 2);
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(new Blob([buffer]));
        const audio = document.createElement('audio');
        const cleanup = () => {
            URL.revokeObjectURL(url);
            audio.removeAttribute('src');
            audio.load();
        };
        audio.preload = 'metadata';
        audio.onloadedmetadata = () => {
            const duration = audio.duration;
            cleanup();
            resolve(duration);
        };
        audio.onerror = () => {
            cleanup();
            reject(new Error('invalid audio'));
        };
        audio.src = url;
    });
}

export default {
    name: 'VolcengineSeedTts30',
    components: { VoicePreviewModal },
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true },
    },
    setup(props) {
        const t = useComponentI18n(props.bridge, I18N_DEFS);
        const { toastMessage, toastVisible, toastType, showSuccess, showError, onToastMouseEnter, onToastMouseLeave } = useToast();
        const { copyText } = useClipboard(showSuccess, showError);
        const selectedEntryId = ref(null);
        watch(() => props.entries, (entries) => {
            if (entries && entries.length) selectedEntryId.value = entries[0].id;
        }, { immediate: true });

        const idMode = ref('existing');
        const speakerId = ref('');
        const customSpeakerId = ref('');
        const languageCode = ref('zh');
        const promptText = ref('');
        const prosodyBoost = ref(false);
        const demoText = ref('');
        const feeConfirmed = ref(false);
        const audioDenoise = ref(false);
        const volumeNormalization = ref(true);
        const audioData = ref('');
        const audioFormat = ref('wav');
        const audioName = ref('');
        const audioInfo = ref('');
        const audioError = ref('');
        const submitting = ref(false);
        const querying = ref(false);
        const queryId = ref('');
        const queryCustomId = ref('');
        const result = ref(null);
        const previewModalVisible = ref(false);
        const previewVoiceId = ref('');
        const selectedLanguage = computed(() => CLONE_LANGUAGES.find(item => item.code === languageCode.value));
        const promptTextRequired = computed(() => selectedLanguage.value?.promptTextRequired === true);
        const prosodySupported = computed(() => selectedLanguage.value?.prosodySupported === true);
        watch(prosodySupported, supported => {
            if (!supported) prosodyBoost.value = false;
        });

        const hasEntry = () => selectedEntryId.value !== null && selectedEntryId.value !== undefined;
        const currentSpeakerId = () => (idMode.value === 'custom' ? customSpeakerId.value : speakerId.value).trim();
        const validCustomSpeakerId = (value) => CUSTOM_SPEAKER_ID_RE.test(value)
            && !/^[a-z]{2}_/.test(value)
            && !CUSTOM_SPEAKER_RESERVED_RE.test(value)
            && !CUSTOM_SPEAKER_SUFFIX_RE.test(value);
        const demoTextValid = () => !demoText.value.trim() || (demoText.value.trim().length >= 4 && demoText.value.trim().length <= 300);
        const canSubmit = () => hasEntry() && !!audioData.value && !submitting.value && !audioError.value
            && !!selectedLanguage.value && !!currentSpeakerId() && demoTextValid()
            && (!promptTextRequired.value || !!promptText.value.trim())
            && (idMode.value !== 'custom' || (validCustomSpeakerId(currentSpeakerId()) && feeConfirmed.value));
        const statusText = (status) => {
            if (status === 2 || status === 4) return t.ready;
            if (status === 0) return t.notFound;
            if (Number.isInteger(status)) return t.pending;
            return t.unknownStatus;
        };
        const voiceReady = () => result.value && (result.value.status === 2 || result.value.status === 4);
        const displayVoiceId = () => result.value && result.value.speaker_id && result.value.speaker_id !== 'custom_speaker_id'
            ? result.value.speaker_id
            : queryId.value;
        const demoAudio = () => {
            const items = result.value && result.value.speaker_status;
            return Array.isArray(items) ? items.find(item => item && item.model_type === 5 && item.demo_audio) : null;
        };
        const formatCreated = (value) => {
            const timestamp = Number(value);
            return Number.isFinite(timestamp) && timestamp > 0 ? new Date(timestamp).toLocaleString() : '—';
        };

        async function onFileSelected(event) {
            const file = event.target.files && event.target.files[0];
            audioData.value = '';
            audioInfo.value = '';
            audioError.value = '';
            if (!file) return;
            audioName.value = file.name;
            audioFormat.value = (file.name.split('.').pop() || '').toLowerCase();
            if (!AUDIO_FORMATS.includes(audioFormat.value)) {
                audioError.value = t.errAudioFormat;
                return;
            }
            if (file.size > MAX_AUDIO_BYTES) {
                audioError.value = t.errAudioSize;
                return;
            }
            try {
                const buffer = await file.arrayBuffer();
                if (audioFormat.value === 'pcm' && buffer.byteLength % 2 !== 0) {
                    audioError.value = t.errPcmData;
                    return;
                }
                const duration = await getDuration(buffer, audioFormat.value);
                if (!Number.isFinite(duration) || duration < 10 || duration > 60) {
                    audioError.value = t.errAudioDuration;
                    return;
                }
                const bytes = new Uint8Array(buffer);
                let binary = '';
                for (let offset = 0; offset < bytes.length; offset += 0x8000) {
                    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
                }
                audioData.value = btoa(binary);
                audioInfo.value = `${formatBytes(file.size)} · ${duration.toFixed(1)}s`;
            } catch (e) {
                audioError.value = t.errAudioRead + ': ' + e.message;
            } finally {
                event.target.value = '';
            }
        }

        async function submitClone() {
            if (!hasEntry()) return showError(t.errNoEntry);
            if (!audioData.value) return showError(t.errNoFile);
            if (audioError.value) return showError(audioError.value);
            if (!currentSpeakerId()) return showError(t.errNoSpeakerId);
            if (!selectedLanguage.value) return showError(t.errLanguage);
            if (promptTextRequired.value && !promptText.value.trim()) return showError(t.errPromptText);
            if (!demoTextValid()) return showError(t.errDemoText);
            const params = {
                entry_id: selectedEntryId.value,
                speaker_id: idMode.value === 'custom' ? '' : currentSpeakerId(),
                language: selectedLanguage.value.id,
                audio: { data: audioData.value, format: audioFormat.value },
            };
            if (idMode.value === 'custom') {
                if (!validCustomSpeakerId(currentSpeakerId())) return showError(t.errCustomId);
                if (!feeConfirmed.value) return showError(t.errFeeConfirm);
                params.speaker_id = 'custom_speaker_id';
                params.custom_speaker_id = currentSpeakerId();
                params.fee_confirmed = true;
            }
            const extra = {};
            if (promptText.value.trim()) extra.prompt_text = promptText.value.trim();
            if (demoText.value.trim()) extra.demo_text = demoText.value.trim();
            for (const [key, value] of [
                ['prosody_boost', prosodyBoost.value],
                ['enable_audio_denoise', audioDenoise.value],
                ['disable_volume_normalization', !volumeNormalization.value],
            ]) if (value) extra[key] = value;
            if (Object.keys(extra).length) params.extra_params = extra;
            submitting.value = true;
            result.value = null;
            try {
                const response = await props.bridge.apiPost('voice/create', params);
                result.value = response;
                queryId.value = result.value.speaker_id && result.value.speaker_id !== 'custom_speaker_id'
                    ? result.value.speaker_id
                    : (params.custom_speaker_id || params.speaker_id);
                queryCustomId.value = params.custom_speaker_id && queryId.value === params.custom_speaker_id
                    ? params.custom_speaker_id
                    : '';
                showSuccess(t.cloneTitle);
            } catch (e) {
                showError(t.errCreate + e.message);
            } finally {
                submitting.value = false;
            }
        }

        async function queryStatus() {
            if (!hasEntry()) return showError(t.errNoEntry);
            if (!queryId.value.trim()) return;
            querying.value = true;
            try {
                const response = await props.bridge.apiPost('voice/query', {
                    entry_id: selectedEntryId.value,
                    voice_id: queryCustomId.value && queryId.value.trim() === queryCustomId.value
                        ? 'custom_speaker_id'
                        : queryId.value.trim(),
                    ...(queryCustomId.value && queryId.value.trim() === queryCustomId.value
                        ? { custom_speaker_id: queryCustomId.value }
                        : {}),
                });
                result.value = { ...(result.value || {}), ...response.status };
                if (response.status && response.status.speaker_id && response.status.speaker_id !== 'custom_speaker_id') {
                    queryId.value = response.status.speaker_id;
                    queryCustomId.value = '';
                }
            } catch (e) {
                showError(t.errQuery + e.message);
            } finally {
                querying.value = false;
            }
        }

        function openPreview() {
            if (!voiceReady()) return;
            previewVoiceId.value = displayVoiceId();
            previewModalVisible.value = true;
        }

        onMounted(() => {
            if (!hasEntry() && props.entries.length) selectedEntryId.value = props.entries[0].id;
        });

        return {
            t, CLONE_LANGUAGES, selectedEntryId, idMode, speakerId, customSpeakerId,
            languageCode, selectedLanguage, promptTextRequired, prosodySupported,
            promptText, prosodyBoost, demoText, feeConfirmed, audioDenoise,
            volumeNormalization, audioName, audioInfo, audioError,
            submitting, querying, queryId, result, previewModalVisible, previewVoiceId,
            toastMessage, toastVisible, toastType, onToastMouseEnter, onToastMouseLeave,
            copyText, onFileSelected, canSubmit, submitClone, queryStatus,
            statusText, voiceReady, displayVoiceId, demoAudio, formatCreated, openPreview,
            currentSpeakerId, validCustomSpeakerId, demoTextValid,
        };
    },
    template: /* html */ `
    <div class="volcengine-seed-tts">
        <Teleport to="body">
            <Transition name="toast">
                <div v-if="toastVisible" class="toast" :class="{'toast-error': toastType === 'error'}"
                     @mouseenter="onToastMouseEnter" @mouseleave="onToastMouseLeave">{{ toastMessage }}</div>
            </Transition>
        </Teleport>

        <div class="form-group">
            <label>{{ t.authConfig }}</label>
            <select v-model="selectedEntryId">
                <option v-for="entry in entries" :key="entry.id" :value="entry.id">{{ entry.display_name || entry.api_key }}</option>
            </select>
            <small>
                {{ t.authConfigHint }}
                <a href="https://docs.volcengine.com/docs/doubao-voice/voice-list-3-0-1" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#2563eb);">{{ t.officialVoiceList }}</a>
            </small>
        </div>
        <div style="margin:0 0 14px;padding:10px 14px;background:rgba(245,158,11,.12);border-left:4px solid #f59e0b;border-radius:var(--radius);font-size:.85rem;line-height:1.6;">
            {{ t.feeTip }}
        </div>

        <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
            <h3>{{ t.cloneTitle }}</h3>
            <a href="https://console.volcengine.com/speech/new/experience/timbre" target="_blank" rel="noopener noreferrer" style="color:var(--primary,#2563eb);font-size:.85rem;">{{ t.voiceDesign }}</a>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
            <div class="form-group">
                <label>{{ t.idMode }}</label>
                <select v-model="idMode">
                    <option value="existing">{{ t.existingId }}</option>
                    <option value="custom">{{ t.customId }}</option>
                </select>
                <small>{{ t.idModeHint }}</small>
            </div>
            <div class="form-group" v-if="idMode === 'existing'">
                <label>{{ t.speakerId }}</label>
                <input v-model="speakerId" type="text" placeholder="S_********">
                <small>{{ t.existingIdHint }}</small>
            </div>
            <div class="form-group" v-else>
                <label>{{ t.customSpeakerId }}</label>
                <input v-model="customSpeakerId" type="text" placeholder="custom_zh_voice01">
                <small>{{ t.customIdHint }}</small>
            </div>
        </div>
        <label v-if="idMode === 'custom'" class="seed-checkbox-label">
            <input v-model="feeConfirmed" type="checkbox"> {{ t.feeConfirm }}
        </label>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;">
            <div class="form-group">
                <label>{{ t.audioFile }}</label>
                <input type="file" accept=".wav,.mp3,.ogg,.m4a,.aac,.pcm" @change="onFileSelected">
                <small>{{ t.seedAudioHint }}</small>
                <div v-if="audioName" style="margin-top:6px;">{{ audioName }} <span v-if="audioInfo">· {{ audioInfo }}</span></div>
                <div v-if="audioError" style="color:var(--error,#dc2626);margin-top:6px;">{{ audioError }}</div>
            </div>
            <div class="form-group">
                <label>{{ t.language }}</label>
                <select v-model="languageCode">
                    <option v-for="item in CLONE_LANGUAGES" :key="item.code" :value="item.code">
                        {{ item.name }}（{{ item.id }} · {{ item.code }}）
                    </option>
                </select>
                <small>{{ t.languageHint }}</small>
            </div>
        </div>
        <div class="form-group">
            <label>{{ t.promptText }}</label>
            <textarea v-model="promptText" rows="2"></textarea>
            <small>{{ promptTextRequired ? t.promptTextRequired : t.promptTextOptional }}</small>
        </div>
        <div v-if="prosodySupported" class="form-group">
            <label class="seed-checkbox-label">
                <input v-model="prosodyBoost" type="checkbox"> {{ t.prosodyBoost }}
            </label>
            <small>{{ t.prosodyHint }}</small>
        </div>
        <div class="form-group" style="margin-top:12px;">
            <label>{{ t.demoText }}</label>
            <textarea v-model="demoText" rows="2" minlength="4" maxlength="300"></textarea>
            <small>{{ t.demoTextHint }}</small>
            <small v-if="!demoTextValid()" style="color:var(--error,#dc2626);">{{ t.errDemoText }}</small>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:12px;">
            <div class="form-group">
                <label class="seed-checkbox-label"><input v-model="audioDenoise" type="checkbox"> {{ t.audioDenoise }}</label>
                <small>{{ t.audioDenoiseHint }}</small>
            </div>
            <div class="form-group">
                <label class="seed-checkbox-label"><input v-model="volumeNormalization" type="checkbox"> {{ t.volumeNormalization }}</label>
                <small>{{ t.volumeNormalizationHint }}</small>
            </div>
        </div>
        <button class="btn btn-primary" style="margin-top:12px;" :disabled="!canSubmit()" @click="submitClone">
            {{ submitting ? t.submitting : t.submit }}
        </button>

        <template v-if="result">
            <hr style="margin:22px 0;border:0;border-top:1px solid var(--border);">
            <h3>{{ t.resultTitle }}</h3>
            <div class="form-group">
                <label>{{ t.voiceId }}</label>
                <div style="display:flex;gap:8px;">
                    <input :value="displayVoiceId()" readonly type="text">
                    <button class="btn btn-sm" @click="copyText(displayVoiceId())">{{ t.copyBtn }}</button>
                </div>
            </div>
            <div class="form-group">
                <label>{{ t.status }}</label>
                <div>{{ statusText(result.status) }} ({{ result.status }})</div>
                <small v-if="result.create_time">{{ formatCreated(result.create_time) }}</small>
            </div>
            <div v-if="demoAudio()">
                <label>{{ t.demoAudio }}</label>
                <audio controls :src="demoAudio().demo_audio" style="width:100%;margin-top:6px;"></audio>
            </div>
            <button v-if="voiceReady()" class="btn btn-sm" style="margin-top:12px;" @click="openPreview">{{ t.seedPreviewBtn }}</button>
        </template>

        <hr style="margin:22px 0;border:0;border-top:1px solid var(--border);">
        <div class="form-group">
            <label>{{ t.queryId }}</label>
            <div style="display:flex;gap:8px;">
                <input v-model="queryId" type="text" placeholder="S_********">
                <button class="btn btn-sm" :disabled="querying || !queryId.trim()" @click="queryStatus">{{ querying ? t.querying : t.query }}</button>
            </div>
            <small>{{ t.queryIdHint }}</small>
        </div>
        <VoicePreviewModal v-model:visible="previewModalVisible" :bridge="bridge" :entry-id="selectedEntryId"
                           :voice-id="previewVoiceId" id-prefix="seed_preview" />
    </div>
    `,
};
