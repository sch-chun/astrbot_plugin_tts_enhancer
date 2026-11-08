// 公共「音色预览」模态框
// - 输入预览文本 → 调用 bridge.apiPost('voice/preview') 合成 → 底部行内出现可重播播放器 + 时长提示
// - 播放复用全局音频单例 useAudioManager（playAudio/stopAudio），与全站其它播放器一致，
//   天然保证同一时刻只有一段音频在响；blob URL 由本组件在关闭 / 重合成时自行释放。
// - 通过 previewed 事件把预览结果通知给父组件（如激活后刷新列表）

const { ref, watch, computed } = Vue;


import { useToast } from '../../composables/useToast.js';
import { useAudioManager, base64ToBlobUrl } from '../../composables/useAudioManager.js';


// 适合朗读的示例文本池：打开模态框时随机抽一条，便于快速试听不同语调 / 情绪。
// 覆盖陈述、疑问、感叹、播报、温柔等多种句式，长短与标点不一，方便对比音色表现。
const DEFAULT_SAMPLES = [
    '你好呀，今天天气真不错，我们一起去公园散步吧！',
    '尊敬的旅客，您乘坐的航班已经开始登机，请前往三号登机口办理乘机手续。',
    '生活就像一盒巧克力，你永远不知道下一颗是什么味道。',
    '请问这附近有推荐的咖啡馆吗？我想找个安静的地方看会儿书。',
    '根据最新数据，本周气温将下降五到八摄氏度，请大家注意添衣保暖。',
    '谢谢你一直以来的陪伴，没有你，我可能早就坚持不下去了。',
    '会议将在下午三点准时开始，请大家提前五分钟入场就座。',
    '哇，这座城市的夜景也太美了吧，灯火璀璨，宛如星河落在人间。',
    '小朋友，慢一点走，前面的台阶有点滑，要小心哦。',
    '恭喜你顺利完成本次任务，系统将在二十四小时内为你发放奖励。',
];

// 随机抽取一条示例；避免与当前文本相同（池子大于 1 时），连续打开不至于重复。
function pickRandomSample(current) {
    if (DEFAULT_SAMPLES.length <= 1) {
        return DEFAULT_SAMPLES[0] || '';
    }
    let next = current;
    while (next === current) {
        next = DEFAULT_SAMPLES[Math.floor(Math.random() * DEFAULT_SAMPLES.length)];
    }
    return next;
}


export default {
    name: 'VoicePreviewModal',
    props: {
        // 是否可见（v-model）
        visible: { type: Boolean, default: false },

        // 桥接对象（提供 apiPost）
        bridge: { type: Object, required: true },

        // 认证配置 id
        entryId: { type: [Number, String], default: null },

        // 当前预览的音色 id
        voiceId: { type: String, default: '' },

        // 默认预览文本（未被父组件覆盖时，打开模态框会从示例池随机抽一条替换）
        initialText: { type: String, default: DEFAULT_SAMPLES[0] },

        // 播放标识前缀，与本音色 voiceId 拼成全局唯一播放 id，复用全局音频单例
        idPrefix: { type: String, default: 'voice_preview' },

        // 后端未返回 format 时的缺省音频格式
        defaultFormat: { type: String, default: 'mp3' },

        // 合成来源：标记本次预览应记入「合成记录」的来源类别
        // （preview=音色预览 / design_preview=设计试听，缺省为 preview）
        source: { type: String, default: 'preview' },

        // 模态框标题
        title: { type: String, default: '预览音色' },
    },
    emits: ['update:visible', 'previewed'],
    setup(props, { emit }) {
        const {
            toastMessage, toastVisible, toastType,
            showError,
            onToastMouseEnter, onToastMouseLeave,
        } = useToast();

        // 复用全局音频单例：playAudio/stopAudio 保证全站同一时刻只响一段，
        // currentPlayingId 用于按钮在「播放 / 停止」间切换。
        const { currentPlayingId, playAudio, stopAudio } = useAudioManager();

        const text = ref(props.initialText);
        const loading = ref(false);
        // 可选：调用 SubAgent 增强（默认关闭，保持预览零 LLM 开销）
        const useEnhance = ref(false);

        // 合成后的音频（blob URL）；非空时行内出现播放器
        const audioUrl = ref('');
        // 音频时长（秒）；合成后由独立 probe 探测，不依赖是否自动播放成功
        const audioDuration = ref(0);

        // 全局唯一播放 id：前缀 + 音色 id，避免与其它组件的播放器（demo/file/trial）冲突
        const playId = computed(() => `${props.idPrefix}_${props.voiceId}`);

        // 释放音频：先停掉播放（cleanup 为 null，单例不会误回收我们的 URL），
        // 再 revoke 上一段 blob URL；关闭模态框 / 重新合成前调用，避免内存泄漏。
        function revokeAudio() {
            stopAudio();
            if (audioUrl.value) {
                try { URL.revokeObjectURL(audioUrl.value); } catch (_) {}
            }
            audioUrl.value = '';
            audioDuration.value = 0;
        }

        function close() {
            revokeAudio();
            emit('update:visible', false);
        }

        // 打开时：若文本为空，或仍是系统示例（未被用户改写），随机抽一条朗读示例；
        // 已含用户自定义文本则保留，避免关闭重开时误删输入。
        watch(() => props.visible, (v) => {
            if (!v) return;
            const cur = text.value.trim();
            if (!cur || DEFAULT_SAMPLES.includes(cur)) {
                text.value = pickRandomSample(cur);
            }
        });

        async function doPreview() {
            if (!text.value.trim()) {
                showError('请输入预览文本');
                return;
            }
            if (props.entryId === null || props.entryId === undefined) {
                showError('请先选择认证配置');
                return;
            }
            loading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/preview', {
                    entry_id: props.entryId,
                    voice_id: props.voiceId,
                    text: text.value.trim(),
                    source: props.source,
                    enhance: useEnhance.value,
                });
                if (!result.audio_base64) {
                    showError('预览失败: 未返回音频数据');
                    return;
                }
                // 释放上一段音频，替换为新合成结果
                revokeAudio();
                const mimeType = `audio/${result.format || props.defaultFormat}`;
                audioUrl.value = base64ToBlobUrl(result.audio_base64, mimeType);
                emit('previewed', { voiceId: props.voiceId, result });
                // 探测时长（仅加载 metadata，不播放），与是否自动播放成功无关
                probeDuration(audioUrl.value);
                // 尝试自动播放（受浏览器自动播放策略限制，失败则保持播放器可见供手动播放）
                playAudio(audioUrl.value, playId.value, { cleanup: null });
            } catch (e) {
                console.error('预览失败:', e);
                showError('预览失败: ' + e.message);
            } finally {
                loading.value = false;
            }
        }

        // 用独立 Audio 探测时长，避免依赖播放；探测期间若已重合成则丢弃旧结果
        function probeDuration(url) {
            audioDuration.value = 0;
            const probe = new Audio(url);
            probe.preload = 'metadata';
            probe.onloadedmetadata = () => {
                if (audioUrl.value === url) {
                    audioDuration.value = probe.duration || 0;
                }
                probe.onloadedmetadata = null;
            };
            probe.onerror = () => { probe.onloadedmetadata = null; };
            probe.load();
        }

        function togglePreviewPlay() {
            if (!audioUrl.value) return;
            // playAudio 对相同 id 自动 toggle 为停止，故单个按钮即「播放 / 停止」
            playAudio(audioUrl.value, playId.value, { cleanup: null });
        }

        function formatDuration(s) {
            if (!s || isNaN(s) || s <= 0) return '计算中…';
            return `${s.toFixed(1)} 秒`;
        }

        return {
            // 通知框
            toastMessage, toastVisible, toastType,
            onToastMouseEnter, onToastMouseLeave,

            // 状态
            text, loading, useEnhance,
            audioUrl, playId, currentPlayingId, audioDuration,

            // 方法
            close, doPreview, togglePreviewPlay, formatDuration,
        };
    },
    template: /* html */ `
        <Teleport to="body">
            <Transition name="modal">
                <div v-if="visible" class="modal-overlay" @mousedown.self="close">
                    <div class="modal-content">
                        <h3>{{ title }}</h3>
                        <p><strong>Voice ID:</strong> {{ voiceId }}</p>
                        <div class="form-group">
                            <label>预览文本</label>
                            <textarea v-model="text" rows="3" placeholder="输入要试听的文本"></textarea>
                        </div>
                        <label class="enhance-toggle">
                            <input type="checkbox" v-model="useEnhance" />
                            <span>调用 SubAgent 增强（可选，将消耗一次 LLM 调用）</span>
                        </label>
                        <div class="preview-actions">
                            <!-- 左侧：合成成功后的可重播播放 + 时长提示 -->
                            <div class="preview-play" v-if="audioUrl">
                                <button class="btn btn-sm" @click="togglePreviewPlay">
                                    {{ currentPlayingId === playId ? '⏹ 停止' : '▶ 播放' }}
                                </button>
                                <span class="preview-hint">合成成功！音频时长：{{ formatDuration(audioDuration) }}</span>
                            </div>
                            <!-- 右侧：合成 / 关闭 -->
                            <div class="preview-buttons">
                                <button
                                    class="btn"
                                    @click="doPreview"
                                    :disabled="loading"
                                >
                                    {{ loading ? '合成中...' : '合成' }}
                                </button>
                                <button class="btn btn-sm btn-secondary" @click="close">关闭</button>
                            </div>
                        </div>
                    </div>
                </div>
            </Transition>

            <!-- 组件内部 toast（与父组件相互独立） -->
            <Transition name="toast">
                <div
                    v-if="toastVisible"
                    class="toast"
                    :class="{'toast-error': toastType === 'error'}"
                    @mouseenter="onToastMouseEnter"
                    @mouseleave="onToastMouseLeave"
                >
                    {{ toastMessage }}
                </div>
            </Transition>
        </Teleport>
    `
};
