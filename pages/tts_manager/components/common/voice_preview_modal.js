// 公共「音色预览」模态框
// - 输入预览文本 → 调用 bridge.apiPost('voice/preview') → 播放 / 停止
// - 内部使用 useToast / useAudioManager，与其它组件共享全局音频单例
// - 通过 previewed 事件把预览结果通知给父组件（如激活后刷新列表）

const { ref, computed, watch } = Vue;


import { useToast } from '../../composables/useToast.js';
import { useAudioManager, base64ToBlobUrl } from '../../composables/useAudioManager.js';


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

        // 默认预览文本
        initialText: { type: String, default: '欢迎使用语音合成预览功能。' },

        // 播放标识前缀，避免不同调用方之间冲突
        idPrefix: { type: String, default: 'voice_preview' },

        // 后端未返回 format 时的缺省音频格式
        defaultFormat: { type: String, default: 'mp3' },

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

        const {
            currentPlayingId,
            playAudio: playAudioGlobal,
            stopAudio,
        } = useAudioManager();

        const text = ref(props.initialText);
        const loading = ref(false);

        // 播放标识：随 voiceId / idPrefix 变化
        const playId = computed(() => `${props.idPrefix}_${props.voiceId}`);

        function close() {
            emit('update:visible', false);
        }

        // 打开时若文本为空则回填默认值
        watch(() => props.visible, (v) => {
            if (v && !text.value.trim()) {
                text.value = props.initialText;
            }
        });

        async function doPreview() {
            // 同一音色正在播放 → 切换为停止，不重复请求后端
            if (currentPlayingId.value === playId.value) {
                stopAudio();
                return;
            }
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
                });
                if (!result.audio_base64) {
                    showError('预览失败: 未返回音频数据');
                    return;
                }
                const mimeType = `audio/${result.format || props.defaultFormat}`;
                const audioUrl = base64ToBlobUrl(result.audio_base64, mimeType);
                playAudioGlobal(audioUrl, playId.value, {
                    cleanup: () => URL.revokeObjectURL(audioUrl),
                    onError: (e) => showError('预览失败: ' + e.message),
                });
                emit('previewed', { voiceId: props.voiceId, result });
            } catch (e) {
                console.error('预览失败:', e);
                showError('预览失败: ' + e.message);
            } finally {
                loading.value = false;
            }
        }

        return {
            // 通知框
            toastMessage, toastVisible, toastType,
            onToastMouseEnter, onToastMouseLeave,

            // 状态
            text, loading, playId, currentPlayingId,

            // 方法
            close, doPreview,
        };
    },
    template: /* html */ `
        <div v-if="visible" class="modal-overlay" @mousedown.self="close">
            <div class="modal-content">
                <h3>{{ title }}</h3>
                <p><strong>Voice ID:</strong> {{ voiceId }}</p>
                <div class="form-group">
                    <label>预览文本</label>
                    <textarea v-model="text" rows="3" placeholder="输入要试听的文本"></textarea>
                </div>
                <div style="display:flex; gap:12px; justify-content:flex-end;">
                    <button
                        class="btn"
                        @click="doPreview"
                        :disabled="loading"
                        :class="{'btn-danger': currentPlayingId === playId}"
                    >
                        {{ loading ? '合成中...' : (
                            currentPlayingId === playId ? '⏹ 停止' : '试听'
                        ) }}
                    </button>
                    <button class="btn btn-sm btn-secondary" @click="close">关闭</button>
                </div>
            </div>
        </div>

        <!-- 组件内部 toast（与父组件相互独立） -->
        <div
            v-if="toastVisible"
            class="toast"
            :class="{'toast-error': toastType === 'error'}"
            @mouseenter="onToastMouseEnter"
            @mouseleave="onToastMouseLeave"
        >
            {{ toastMessage }}
        </div>
    `
};
