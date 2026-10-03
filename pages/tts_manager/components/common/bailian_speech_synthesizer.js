const { ref, reactive, watch, computed } = Vue;


import { useClipboard } from '../../composables/useClipboard.js';
import { useToast } from '../../composables/useToast.js';
import { useAudioManager } from '../../composables/useAudioManager.js';
import { validateText } from '../../composables/useTextValidator.js';
import { base64ToBlobUrl } from '../../composables/useAudioManager.js';
import VoicePreviewModal from './voice_preview_modal.js';
import DeleteConfirmModal from './delete_confirm_modal.js';


const MAX_CLONE_AUDIO_BYTES = 10 * 1024 * 1024;
const CLONE_AUDIO_MIME_BY_EXTENSION = Object.freeze({
    wav: 'audio/wav',
    mp3: 'audio/mpeg',
    m4a: 'audio/mp4',
});


export default {
    name: 'BailianSpeechSynthesizer',
    components: { VoicePreviewModal, DeleteConfirmModal },
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true },

        // 供应商特定配置
        providerConfig: {
            type: Object,
            default: () => ({
                displayName: '百炼 TTS',
                supportedLanguages: [
                    'zh','en','fr','de','ja','ko','ru','pt','th','id','vi'
                ],
                supportsSystemVoices: true,
                systemVoiceHelpLink: '',
                designHelpLink: 'https://help.aliyun.com/zh/model-studio/voice-design-user-guide',
                availableModels: ['flash', 'plus']
            })
        }
    },
    setup(props) {

        // ----- Toast 提示 -----
        const {
            toastMessage, toastVisible, toastType,
            showSuccess, showError,
            onToastMouseEnter, onToastMouseLeave,
        } = useToast();

        // ----- 全局音频控制（单例，跨组件共享音量与播放状态） -----
        const {
            currentPlayingId,
            playAudio: playAudioGlobal,
            stopAudio,
            isPlaying,
        } = useAudioManager();

        // ----- 公共状态 -----
        const selectedEntryId = ref(null);
        const voiceList = ref([]);
        const loading = ref(false);
        const mode = ref('clone'); // 'clone' | 'design'

        // ----- Data URL 复刻表单 -----
        const cloneForm = reactive({
            file: null,
            prefix: 'clone',
            language_hint: 'zh',
            enable_volume_normalization: false,
            enable_preprocess: false,
            max_prompt_audio_length: 10.0,
            model: 'flash',
        });
        const cloning = ref(false);

        // 用于重置文件输入框的 ref
        const fileInputRef = ref(null);

        // ----- 设计模式表单 -----
        const designForm = reactive({
            voice_prompt: '',
            preview_text: '欢迎使用声音设计功能，让我们听听这个音色的效果。',
            prefix: 'design',
            language_hint: 'zh',
            model: 'flash',
            sample_rate: 24000,
            response_format: 'wav',
        });
        const designing = ref(false);

        // ----- 删除确认模态框 -----
        const deleteModalVisible = ref(false);
        const deleteTargetId = ref('');

        // ----- 语言列表（从 providerConfig 中读取）-----
        const allLanguages = computed(() => {
            const codes = props.providerConfig.supportedLanguages || [];

            // 标签映射（可复用原映射）
            const labelMap = {
                'zh': '中文', 'en': '英语', 'fr': '法语', 'de': '德语',
                'ja': '日语', 'ko': '韩语', 'ru': '俄语', 'pt': '葡萄牙语',
                'th': '泰语', 'id': '印尼语', 'vi': '越南语', 'es': '西班牙语',
                'it': '意大利语', 'ms': '马来西亚语', 'fil': '菲律宾语', 'ar': '阿拉伯语'
            };
            return codes.map(code => ({ code, label: labelMap[code] || code }));
        });

        // 根据模式过滤语言列表：设计模式仅支持中英文
        const languages = computed(() => {
            if (mode.value === 'design') {
                return allLanguages.value.filter(l => l.code === 'zh' || l.code === 'en');
            }
            return allLanguages.value;
        });

        // ----- 模型列表（从 providerConfig 中读取）-----
        const MODEL_LABELS = { flash: 'Flash', plus: 'Plus' };

        const availableModels = computed(() => {
            const models = props.providerConfig.availableModels || ['flash', 'plus'];
            return models.map(m => ({ code: m, label: MODEL_LABELS[m] || m }));
        });

        // ----- 当前表单（根据模式）-----
        const currentForm = computed(() => {
            if (mode.value === 'design') return designForm;
            return cloneForm;
        });

        // ----- 设计模式字符数校验 -----
        const voicePromptValidation = computed(() => validateText(designForm.voice_prompt, {
            label: '声音描述',
            max: 500,
            required: true,
        }));

        const previewTextValidation = computed(() => validateText(designForm.preview_text, {
            label: '预览文本',
            min: 15,
            max: 200,
            required: true,
        }));

        const voicePromptChars = computed(() => voicePromptValidation.value.count);
        const previewTextChars = computed(() => previewTextValidation.value.count);
        const voicePromptError = computed(() => voicePromptValidation.value.error);
        const previewTextError = computed(() => previewTextValidation.value.error);

        const isVoicePromptValid = computed(() => voicePromptValidation.value.valid);
        const isPreviewTextValid = computed(() => previewTextValidation.value.valid);

        const isPrefixValidForDesign = computed(() => {
            return /^[a-zA-Z0-9]{1,10}$/.test(designForm.prefix);
        });

        const isDesignFormValid = computed(() => {
            return isPrefixValidForDesign.value &&
                isVoicePromptValid.value &&
                isPreviewTextValid.value;
        });

        // ----- 监听 entry 变化 -----
        watch(() => props.entries, (newVal) => {
            if (newVal && newVal.length > 0) {
                selectedEntryId.value = newVal[0].id;
                fetchVoices();
            }
        }, { immediate: true, deep: true });

        const currentEntry = computed(() => {
            return props.entries.find(e => e.id === selectedEntryId.value) || props.entries[0];
        });

        watch(currentEntry, (newEntry) => {
        if (newEntry) {
            const models = props.providerConfig.availableModels || ['flash', 'plus'];
            let entryModel = newEntry.model || 'flash';
            if (!models.includes(entryModel)) {
                entryModel = models[0];
            }
            cloneForm.model = entryModel;
            designForm.model = entryModel;
        }
    }, { immediate: true });

        // ----- 获取音色列表 -----
        async function fetchVoices() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) return;
            loading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/list', {
                    entry_id: selectedEntryId.value,
                    page_size: 50,
                });
                voiceList.value = result.items || [];
            } catch (e) {
                console.error('获取音色列表失败:', e);
                showError('获取音色列表失败: ' + e.message);
            } finally {
                loading.value = false;
            }
        }

        // ----- 通用创建音色（调用 /voice/create）-----
        async function callCreateVoice(payload) {
            Object.keys(payload).forEach(key => {
                if (payload[key] === undefined) delete payload[key];
            });
            try {
                const result = await props.bridge.apiPost('voice/create', payload);
                console.log('Create voice response:', result);
                if (result.voice_id || result.voice) {
                    return result;
                }
                const errMsg = result.message || result.error || '创建失败，未返回音色 ID';
                showError('创建音色失败: ' + errMsg);
                return null;
            } catch (e) {
                console.error('创建音色异常:', e);
                let errMsg = e.message || '未知错误';
                if (e.response) {
                    try {
                        const data = await e.response.json();
                        errMsg = data.message || data.error || errMsg;
                    } catch {}
                }
                showError('创建音色失败: ' + errMsg);
                return null;
            }
        }

        // ----- Data URL 复刻 -----
        function getCloneAudioMimeType(file) {
            const extension = file.name.split('.').pop()?.toLowerCase() || '';
            return CLONE_AUDIO_MIME_BY_EXTENSION[extension] || '';
        }

        function validateCloneAudioFile(file) {
            const mimeType = getCloneAudioMimeType(file);
            if (!mimeType) {
                throw new Error('仅支持 wav、mp3、m4a 音频文件');
            }
            if (!file.size) {
                throw new Error('音频文件不能为空');
            }
            if (file.size > MAX_CLONE_AUDIO_BYTES) {
                throw new Error('音频文件不得超过 10MB');
            }
            return mimeType;
        }

        function encodeAudioAsDataUrl(file, mimeType) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onerror = () => reject(new Error('读取音频文件失败'));
                reader.onload = () => {
                    const rawDataUrl = String(reader.result || '');
                    const separatorIndex = rawDataUrl.indexOf(',');
                    if (separatorIndex < 0 || separatorIndex === rawDataUrl.length - 1) {
                        reject(new Error('音频文件编码失败'));
                        return;
                    }
                    resolve(`data:${mimeType};base64,${rawDataUrl.slice(separatorIndex + 1)}`);
                };
                reader.readAsDataURL(file);
            });
        }

        function handleFileChange(event) {
            const file = event.target.files[0];
            if (!file) {
                cloneForm.file = null;
                return;
            }
            try {
                validateCloneAudioFile(file);
                cloneForm.file = file;
            } catch (error) {
                cloneForm.file = null;
                event.target.value = '';
                showError(error.message);
            }
        }

        async function cloneFromFile() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            if (!cloneForm.file) {
                showError('请选择音频文件');
                return;
            }

            cloning.value = true;
            try {
                const mimeType = validateCloneAudioFile(cloneForm.file);
                const audioDataUrl = await encodeAudioAsDataUrl(cloneForm.file, mimeType);
                const payload = {
                    entry_id: selectedEntryId.value,
                    mode: 'clone',
                    audio_data_url: audioDataUrl,
                    prefix: cloneForm.prefix,
                    language_hints: cloneForm.language_hint ? [cloneForm.language_hint] : [],
                    enable_volume_normalization: cloneForm.enable_volume_normalization,
                    enable_preprocess: cloneForm.enable_preprocess,
                    max_prompt_audio_length:
                        cloneForm.enable_preprocess ?
                        cloneForm.max_prompt_audio_length : undefined,
                    model: cloneForm.model,
                };
                const result = await callCreateVoice(payload);
                if (result) {
                    const voiceId = result.voice_id || result.voice;
                    showSuccess('音色创建成功！Voice ID: ' + voiceId);
                    await fetchVoices();
                    cloneForm.file = null;
                    if (fileInputRef.value) {
                        fileInputRef.value.value = '';
                    }
                }
            } catch (error) {
                console.error('Data URL 复刻失败:', error);
                showError('复刻失败: ' + error.message);
            } finally {
                cloning.value = false;
            }
        }

        // ----- 设计模式：创建音色并打开预览模态框 -----
        const previewModalVisible = ref(false);
        const previewVoiceId = ref('');
        const previewAudioBase64 = ref('');
        const previewAudioFormat = ref('wav');
        const previewText = ref('欢迎使用声音设计功能，让我们听听这个音色的效果。');
        const previewDeleteConfirm = ref(false);

        async function createFromDesign() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            if (!isVoicePromptValid.value) {
                showError(voicePromptError.value);
                return;
            }
            if (!isPreviewTextValid.value) {
                showError(previewTextError.value);
                return;
            }
            if (!isPrefixValidForDesign.value) {
                showError('prefix 必须为字母数字，长度 1-10');
                return;
            }

            designing.value = true;
            try {
                const payload = {
                    entry_id: selectedEntryId.value,
                    mode: 'design',
                    voice_prompt: designForm.voice_prompt,
                    preview_text: designForm.preview_text,
                    prefix: designForm.prefix,
                    language_hints: designForm.language_hint ? [designForm.language_hint] : [],
                    model: designForm.model,
                    sample_rate: designForm.sample_rate,
                    response_format: designForm.response_format,
                };
                const result = await callCreateVoice(payload);
                if (result) {
                    previewVoiceId.value = result.voice_id;
                    previewAudioBase64.value = result.preview_audio?.data || '';
                    previewAudioFormat.value = result.preview_audio?.response_format || 'wav';
                    previewText.value = designForm.preview_text;
                    previewModalVisible.value = true;
                }
            } catch (e) {
                console.error('设计模式创建失败:', e);
                showError('创建失败: ' + e.message);
            } finally {
                designing.value = false;
            }
        }

        // ----- 预览模态框 -----
        const designPreviewId = computed(() => `design_preview_${previewVoiceId.value}`);

        function closePreviewModal() {
            previewModalVisible.value = false;
            previewDeleteConfirm.value = false;

            // 若仍在该音色的预览播放中，则停止（停止时会自动 revoke blob URL）
            if (isPlaying(designPreviewId.value)) {
                stopAudio();
            }
        }

        function playPreviewAudio() {
            if (!previewAudioBase64.value) {
                showError('没有可播放的音频数据');
                return;
            }
            try {
                const mimeType = `audio/${previewAudioFormat.value}`;
                const audioUrl = base64ToBlobUrl(previewAudioBase64.value, mimeType);
                playAudioGlobal(audioUrl, designPreviewId.value, {
                    cleanup: () => URL.revokeObjectURL(audioUrl),
                    onError: (e) => showError('播放失败: ' + e.message),
                });
            } catch (e) {
                console.error('播放失败:', e);
                showError('播放失败: ' + e.message);
            }
        }

        async function keepVoice() {
            showSuccess('音色已保留: ' + previewVoiceId.value);
            closePreviewModal();
            await fetchVoices();
        }

        async function confirmDeletePreview() {
            try {
                await props.bridge.apiPost('voice/delete', {
                    entry_id: selectedEntryId.value,
                    voice_id: previewVoiceId.value,
                });
                showSuccess('音色已删除');
                closePreviewModal();
                await fetchVoices();
            } catch (e) {
                console.error('删除音色失败:', e);
                showError('删除失败: ' + e.message);
                previewDeleteConfirm.value = false;
            }
        }

        // ----- 列表预览（音色列表中的预览按钮）-----
        const listPreviewModalVisible = ref(false);
        const listPreviewVoiceId = ref('');

        function openListPreviewModal(voiceId) {
            listPreviewVoiceId.value = voiceId;
            listPreviewModalVisible.value = true;
        }

        // ----- 删除音色（使用自定义模态框）-----
        async function deleteVoice(voiceId) {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            deleteTargetId.value = voiceId;
            deleteModalVisible.value = true;
        }

        async function confirmDelete() {
            try {
                await props.bridge.apiPost('voice/delete', {
                    entry_id: selectedEntryId.value,
                    voice_id: deleteTargetId.value,
                });
                showSuccess('删除成功');
                deleteModalVisible.value = false;
                deleteTargetId.value = '';
                await fetchVoices();
            } catch (e) {
                console.error('删除音色失败:', e);
                showError('删除失败: ' + e.message);
            }
        }

        function cancelDelete() {
            deleteModalVisible.value = false;
            deleteTargetId.value = '';
        }

        // ----- 复制到剪贴板 -----
        const { copyText, copyLink } = useClipboard(showSuccess, showError);

        function getStatusDescription(status) {
            const map = {
                'DEPLOYING': '审核中/处理中',
                'OK': '审核通过，可正常使用',
                'UNDEPLOYED': '审核未通过，不可使用'
            };
            return map[status] || status;
        }

        // ---- 表单校验（克隆模式） ----
        const isPrefixValid = computed(() => {
            const prefix = currentForm.value.prefix;
            return /^[a-zA-Z0-9]{1,10}$/.test(prefix);
        });

        const isMaxLengthValid = computed(() => {
            if (!currentForm.value.enable_preprocess) return true;
            const val = currentForm.value.max_prompt_audio_length;
            return typeof val === 'number' && val >= 3.0 && val <= 30.0;
        });

        const isFormValid = computed(() => {
            const prefixOK = isPrefixValid.value;
            const lengthOK = isMaxLengthValid.value;
            const fileOK = mode.value !== 'clone' || Boolean(cloneForm.file);
            return prefixOK && lengthOK && fileOK;
        });

        return {

            // 通知框
            toastMessage, toastVisible, toastType,
            onToastMouseEnter, onToastMouseLeave,

            // 数据
            selectedEntryId, currentEntry, voiceList, loading, designing, mode,
            currentForm, cloneForm, cloning, designForm, availableModels,
            deleteModalVisible, deleteTargetId, languages,

            // 预览
            previewModalVisible, previewVoiceId, previewText, previewDeleteConfirm,
            playPreviewAudio, keepVoice, closePreviewModal, confirmDeletePreview,

            // 列表预览
            listPreviewModalVisible, listPreviewVoiceId,
            openListPreviewModal,

            // 删除
            deleteVoice, confirmDelete, cancelDelete,
            
            // 公共方法
            fetchVoices, getStatusDescription,

            // 音频播放（单例）
            currentPlayingId, isPlaying,

            // 校验
            voicePromptChars, previewTextChars, voicePromptError, previewTextError, isPrefixValid,
            isVoicePromptValid, isPreviewTextValid, isPrefixValidForDesign, isDesignFormValid,
            isFormValid,

            // 上传文件 ref
            fileInputRef,
            handleFileChange, cloneFromFile, createFromDesign,
            
            // 供应商配置（用于模板）
            providerConfig: props.providerConfig,

            // 复制
            copyText, copyLink,
        };
    },
    template: /*html*/ `
        <div class="bailian-tts">
            <div v-if="toastVisible"
                class="toast"
                :class="{'toast-error': toastType === 'error'}"
                @mouseenter="onToastMouseEnter"
                @mouseleave="onToastMouseLeave"
            >
                {{ toastMessage }}
            </div>

            <!-- 认证配置选择 -->
            <div class="form-group">
                <label>认证配置</label>
                <select v-model="selectedEntryId">
                    <option v-for="entry in entries" :key="entry.id" :value="entry.id">
                        {{ entry.display_name || entry.api_key }} 
                        ({{ entry.workspace_id }})
                    </option>
                </select>
                <span v-if="currentEntry" style="margin-left:12px;color:var(--gray);font-size:0.9rem;">
                    API Key: {{ currentEntry.api_key }}
                </span>
            </div>

            <!-- 音色创建区域 -->
            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>创建新音色</legend>

                <!-- 系统音色提示（仅当供应商支持系统音色且非设计模式） -->
                <div v-if="providerConfig.supportsSystemVoices && mode !== 'design'" 
                    style="
                        background:rgba(37,99,235,0.1);
                        border-left:4px solid var(--primary);
                        padding:8px 12px;
                        margin-bottom:16px;
                        border-radius:4px;
                        color:var(--text);
                    "
                >
                    💡 系统音色列表请参考<!--
                    --><template v-if="providerConfig.systemVoiceLinks && providerConfig.systemVoiceLinks.length">
                        <span v-for="(link, idx) in providerConfig.systemVoiceLinks" :key="idx">
                            <span class="link-copy" @click="copyLink(link.url)" 
                                style="color:var(--primary);cursor:pointer;text-decoration:underline;margin:0 4px;">
                                {{ link.label }}
                            </span>
                            <span v-if="idx < providerConfig.systemVoiceLinks.length - 1">、</span>
                        </span>
                    </template>
                    <template v-else>
                        <span class="link-copy" @click="copyLink(providerConfig.systemVoiceHelpLink)" 
                            style="color:var(--primary);cursor:pointer;text-decoration:underline;">
                            帮助文档
                        </span>
                    </template><!--
                    -->（点击复制链接）
                </div>

                <!-- 选项卡切换 -->
                <div
                    style="display:flex;gap:8px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;"
                >
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'clone' }"
                        @click="mode = 'clone'"
                        style="
                            padding:8px 16px;
                            border:none;
                            background:transparent;
                            cursor:pointer;
                            border-bottom:2px solid transparent;
                        "
                    >📁 声音复刻</button>
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'design' }"
                        @click="mode = 'design'"
                        style="
                            padding:8px 16px;
                            border:none;
                            background:transparent;
                            cursor:pointer;
                            border-bottom:2px solid transparent;
                        "
                    >🎨 声音设计</button>
                </div>

                <div v-if="mode === 'clone'">
                    <div class="form-group">
                        <label>选择音频文件（wav (16bit), mp3, m4a）</label>
                        <input type="file" ref="fileInputRef" accept=".wav,.mp3,.m4a" @change="handleFileChange" />
                        <div class="hint">
                            推荐 10~20s，最长 60s，文件 ≤ 10MB，采样率 ≥ 16kHz。
                        </div>
                    </div>
                </div>

                <!-- 声音设计模式 -->
                <div v-if="mode === 'design'">
                    <div class="form-group">
                        <label>声音描述（自然语言）</label>
                        <textarea 
                            v-model="designForm.voice_prompt" 
                            rows="3" 
                            placeholder="例如：沉稳的中年男性播音员，音色低沉浑厚，富有磁性，语速平稳..." 
                            :class="{ 'input-error': !isVoicePromptValid }"
                            style="
                                width:100%;
                                padding:8px;
                                border:1px solid var(--border);
                                border-radius:var(--radius);
                                background:var(--bg);
                                color:var(--text);
                                resize:vertical;
                            "
                        ></textarea>
                        <div v-if="voicePromptError" class="error-hint">
                            ⚠️ {{ voicePromptError }}
                        </div>
                        <div class="hint">
                            用自然语言描述期望的声音特质，支持中文和英文，不超过 500 字符（汉字按 2 字符计算）。详见 
                            <span
                                style="color:var(--primary);cursor:pointer;text-decoration:underline;"
                                @click="copyLink(providerConfig.designHelpLink)"
                            >声音设计编写指南</span>
                            （点击复制链接，请手动粘贴到浏览器地址栏打开）
                        </div>
                    </div>

                    <div class="form-group">
                        <label>预览文本</label>
                        <textarea 
                            v-model="designForm.preview_text" 
                            rows="2" 
                            placeholder="输入用于试听的文本..." 
                            :class="{ 'input-error': !isPreviewTextValid }"
                            style="
                                width:100%;
                                padding:8px;
                                border:1px solid var(--border);
                                border-radius:var(--radius);
                                background:var(--bg);
                                color:var(--text);
                                resize:vertical;
                            "
                        ></textarea>
                        <div v-if="previewTextError" class="error-hint">
                            ⚠️ {{ previewTextError }}
                        </div>
                        <div class="hint">最小 15 字符，最大 200 字符（汉字按 2 字符计算）</div>
                    </div>
                </div>

                <!-- 公共配置 -->
                <div class="form-group">
                    <label>音色前缀</label>
                    <input
                        v-model="currentForm.prefix"
                        placeholder="例如：design"
                        :class="{ 'input-error': !isPrefixValid }"
                    />
                    <div v-if="!isPrefixValid" class="error-hint">
                        ⚠️ 仅字母数字，长度 1~10 字符
                    </div>
                    <div class="hint">
                        <span v-if="mode === 'design'">生成的音色名格式：{target_model}-vd-{prefix}-{唯一标识}</span>
                        <span v-else>生成的音色名格式：{target_model}-{prefix}-{唯一标识}</span>
                    </div>
                </div>

                <div class="form-group">
                    <label>语言提示</label>
                    <div class="language-radios">
                        <label v-for="lang in languages" :key="lang.code" class="lang-radio">
                            <input type="radio" :value="lang.code" v-model="currentForm.language_hint" />
                            {{ lang.label }}
                        </label>
                    </div>
                    <div class="hint">辅助模型识别语种，提升合成效果。设计模式仅支持中文和英文。</div>
                </div>

                <!-- 克隆专用参数 -->
                <template v-if="mode !== 'design'">
                    <div class="form-group checkbox-group">
                        <input
                            type="checkbox"
                            v-model="currentForm.enable_volume_normalization"
                            :id="mode + '_vol_norm'"
                        />
                        <label :for="mode + '_vol_norm'">启用音量归一化</label>
                    </div>

                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="currentForm.enable_preprocess" :id="mode + '_preproc'" />
                        <label :for="mode + '_preproc'">启用音频预处理</label>
                        <div class="hint">有背景噪音时建议开启</div>
                    </div>

                    <div class="form-group" v-if="currentForm.enable_preprocess">
                        <label>最大提示音频时长（s）</label>
                        <input
                            type="number"
                            v-model.number="currentForm.max_prompt_audio_length"
                            step="0.1"
                            min="3.0"
                            max="30.0"
                            :class="{ 'input-error': !isMaxLengthValid }"
                        />
                        <div v-if="!isMaxLengthValid" class="error-hint">
                            ⚠️ 请输入 3.0 ~ 30.0 之间的数值
                        </div>
                    </div>
                </template>

                <!-- 设计专用参数 -->
                <template v-if="mode === 'design'">
                    <div class="form-group">
                        <label>采样率</label>
                        <select v-model="designForm.sample_rate">
                            <option value="8000">8000</option>
                            <option value="16000">16000</option>
                            <option value="24000" selected>24000</option>
                            <option value="48000">48000</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>输出格式</label>
                        <select v-model="designForm.response_format">
                            <option value="pcm">PCM</option>
                            <option value="wav" selected>WAV</option>
                            <option value="mp3">MP3</option>
                            <option value="opus">Opus</option>
                        </select>
                    </div>
                </template>

                <div class="form-group">
                    <label>模型版本</label>
                    <select v-model="currentForm.model">
                        <option v-for="m in availableModels" :key="m.code" :value="m.code">
                            {{ m.label }}
                        </option>
                    </select>
                </div>

                <!-- 提交按钮 -->
                <button
                    v-if="mode === 'clone'"
                    class="btn"
                    @click="cloneFromFile"
                    :disabled="!isFormValid || cloning"
                >
                    {{ cloning ? '复刻中...' : '📁 复刻音色' }}
                </button>
                <button
                    v-else-if="mode === 'design'"
                    class="btn"
                    @click="createFromDesign"
                    :disabled="!isDesignFormValid || designing"
                >
                    {{ designing ? '创建中...' : '🎨 设计音色' }}
                </button>
            </fieldset>

            <!-- 音色列表 -->
            <div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <h3 style="margin:0;">音色列表</h3>
                    <button class="btn btn-sm" @click="fetchVoices" :disabled="loading">刷新</button>
                </div>
                <div v-if="loading">加载中...</div>
                <table v-else>
                    <thead>
                        <tr>
                            <th>Voice ID</th>
                            <th>创建时间</th>
                            <th>状态</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in voiceList" :key="v.voice_id">
                            <td>
                                {{ v.voice_id }}
                                <span v-if="v.voice_id && v.voice_id.includes('-vd-')"
                                    style="
                                        background:#dbeafe;
                                        color:#1e40af;
                                        padding:0 6px;
                                        border-radius:4px;
                                        font-size:0.7rem;
                                        margin-left:4px;
                                    "
                                >设计</span>
                            </td>
                            <td>{{ v.created_at }}</td>
                            <td>
                                <span
                                    :class="'status-' + v.status.toLowerCase()"
                                    :title="getStatusDescription(v.status)"
                                >{{ v.status }}</span>
                            </td>
                            <td>
                                <button
                                    class="btn btn-sm"
                                    @click="copyText(v.voice_id)"
                                    title="复制 ID"
                                    style="margin-right: 4px;"
                                >复制</button>
                                <button
                                    class="btn btn-sm"
                                    @click="openListPreviewModal(v.voice_id)"
                                    :disabled="v.status !== 'OK'"
                                    title="预览音色"
                                    style="margin-right: 4px;"
                                >预览</button>
                                <button class="btn btn-danger btn-sm" @click="deleteVoice(v.voice_id)">删除</button>
                            </td>
                        </tr>
                        <tr v-if="!voiceList.length">
                            <td colspan="4" style="text-align:center;color:var(--gray);">暂无音色</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- 预览模态框（设计模式专用 - 内嵌删除确认） -->
            <div v-if="previewModalVisible" class="modal-overlay">
                <div class="modal-content" style="max-width:500px;width:90%;">
                    <h3>🎧 音色预览</h3>
                    <p><strong>Voice ID:</strong> {{ previewVoiceId }}</p>
                    <p><strong>预览文本:</strong> {{ previewText }}</p>
                    <div style="display:flex;gap:12px;margin:16px 0;flex-wrap:wrap;">
                        <button class="btn" @click="playPreviewAudio"
                            :class="{'btn-danger': currentPlayingId === 'design_preview_' + previewVoiceId}">
                            {{ currentPlayingId === 'design_preview_' + previewVoiceId ? '⏹ 停止' : '▶ 试听' }}
                        </button>
                    </div>
                    <div style="border-top:1px solid var(--border);padding-top:16px;">
                        <div v-if="!previewDeleteConfirm" style="display:flex;gap:12px;justify-content:flex-end;">
                            <button class="btn btn-success" @click="keepVoice">保留</button>
                            <button class="btn btn-danger" @click="previewDeleteConfirm = true">删除</button>
                            <button class="btn btn-sm btn-secondary" @click="closePreviewModal">关闭</button>
                        </div>
                        <div v-else style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
                            <div style="color:var(--danger);font-weight:bold;">
                                ⚠️ 确定要删除此音色吗？此操作不可恢复。
                            </div>
                            <div style="display:flex;gap:12px;">
                                <button class="btn btn-sm btn-secondary" @click="previewDeleteConfirm = false">
                                    取消
                                </button>
                                <button class="btn btn-danger" @click="confirmDeletePreview">确认删除</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 删除确认模态框（公共组件） -->
            <DeleteConfirmModal
                v-model:visible="deleteModalVisible"
                title="⚠️ 确认删除"
                @cancel="cancelDelete"
                @confirm="confirmDelete"
            >
                <p>确定要删除音色 <strong>{{ deleteTargetId }}</strong> 吗？此操作不可恢复。</p>
            </DeleteConfirmModal>

            <!-- 列表预览模态框 -->
            <VoicePreviewModal
                v-model:visible="listPreviewModalVisible"
                :bridge="bridge"
                :entry-id="selectedEntryId"
                :voice-id="listPreviewVoiceId"
                id-prefix="list_preview"
                default-format="mpeg"
            />
        </div>
    `
};
