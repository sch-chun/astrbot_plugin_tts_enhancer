const { ref, reactive, computed, watch, onMounted } = Vue;

import { useToast } from '../composables/useToast.js';
import { useClipboard } from '../composables/useClipboard.js';
import { useAudioManager } from '../composables/useAudioManager.js';
import { validateText } from '../composables/useTextValidator.js';
import VoicePreviewModal from './common/voice_preview_modal.js';
import DeleteConfirmModal from './common/delete_confirm_modal.js';

export default {
    name: 'BailianMinimaxSpeech2_8',
    components: { VoicePreviewModal, DeleteConfirmModal },
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true }
    },
    setup(props) {

        // ---------- Toast ----------
        const {
            toastMessage, toastVisible, toastType,
            showToast, showSuccess, showError,
            onToastMouseEnter, onToastMouseLeave,
        } = useToast();

        // ---------- 认证配置 ----------
        const selectedEntryId = ref(null);
        watch(() => props.entries, (newVal) => {
            if (newVal && newVal.length > 0) {
                selectedEntryId.value = newVal[0].id;
            }
        }, { immediate: true });

        const currentEntry = computed(() => {
            return props.entries.find(e => e.id === selectedEntryId.value) || props.entries[0];
        });

        // ---------- 全局音频控制 ----------
        const {
            volume,
            currentPlayingId,
            playAudio: playAudioGlobal,
            stopAudio,
            isPlaying,
        } = useAudioManager();

        function playAudio(url, buttonId, cleanup) {
            return playAudioGlobal(url, buttonId, {
                cleanup,
                onError: (e) => showError('播放失败: ' + e.message),
            });
        }

        // ---------- 选项卡 ----------
        const currentTab = ref('upload'); // 'upload' | 'url' | 'list'

        // ---------- 声音克隆（支持本地文件和 URL）----------
        const cloneParams = reactive({
            voice_id: '',
            audio_url: '',
            text: '你好，这是试听文本。',
            model: 'HD',
            language_boost: 'auto',
            need_noise_reduction: false,
            need_volume_normalization: false,
            aigc_watermark: false,
        });
        const cloning = ref(false);

        // 本地文件选择
        const fileInputRef = ref(null);
        const selectedAudioFile = ref(null);
        const audioFileBase64 = ref(''); // 存储转换后的 Data URL

        // 示例音频（可选，用于增强相似度）
        const promptFileInputRef = ref(null);
        const selectedPromptFile = ref(null);
        const promptFileBase64 = ref('');
        const promptText = ref(''); // 示例音频对应的文本

        // 文件读取为 Base64 Data URL
        function handleAudioFileSelect(event) {
            const file = event.target.files[0];
            if (!file) {
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
                return;
            }

            // 校验文件类型
            const validTypes = ['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a'];
            if (!validTypes.includes(file.type) && !file.name.match(/\.(wav|mp3|m4a)$/i)) {
                showError('不支持的音频格式，请选择 WAV/MP3/M4A 文件');
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
                return;
            }

            // 校验文件大小（建议 < 10MB）
            if (file.size > 10 * 1024 * 1024) {
                showError('音频文件过大，请选择 10MB 以内的文件');
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
                return;
            }

            selectedAudioFile.value = file;

            // 读取为 Base64 Data URL
            const reader = new FileReader();
            reader.onload = (e) => {
                audioFileBase64.value = e.target.result; // 完整的 Data URL
            };
            reader.onerror = () => {
                showError('读取文件失败');
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
            };
            reader.readAsDataURL(file);
        }

        // 清除文件选择
        function clearAudioFile() {
            selectedAudioFile.value = null;
            audioFileBase64.value = '';
            if (fileInputRef.value) {
                fileInputRef.value.value = '';
            }
        }

        // 示例音频文件选择
        function handlePromptFileSelect(event) {
            const file = event.target.files[0];
            if (!file) {
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
                return;
            }

            // 校验文件类型
            const validTypes = ['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a'];
            if (!validTypes.includes(file.type) && !file.name.match(/\.(wav|mp3|m4a)$/i)) {
                showError('不支持的音频格式，请选择 WAV/MP3/M4A 文件');
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
                return;
            }

            // 校验文件大小（< 20MB）
            if (file.size > 20 * 1024 * 1024) {
                showError('示例音频文件过大，请选择 20MB 以内的文件');
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
                return;
            }

            selectedPromptFile.value = file;

            // 读取为 Base64 Data URL
            const reader = new FileReader();
            reader.onload = (e) => {
                promptFileBase64.value = e.target.result;
            };
            reader.onerror = () => {
                showError('读取示例音频失败');
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
            };
            reader.readAsDataURL(file);
        }

        // 清除示例音频
        function clearPromptFile() {
            selectedPromptFile.value = null;
            promptFileBase64.value = '';
            promptText.value = '';
            if (promptFileInputRef.value) {
                promptFileInputRef.value.value = '';
            }
        }

        // ---------- 音色列表 ----------
        const voiceList = ref([]);
        const voiceLoading = ref(false);

        async function fetchVoiceList() {
            if (!selectedEntryId.value) return;
            voiceLoading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/list', {
                    entry_id: selectedEntryId.value,
                    voice_type: 'all'
                });
                voiceList.value = result.items || [];

                // 检查未激活音色是否已出现在自定义列表中
                const activeVoiceIds = new Set(voiceList.value.map(v => v.voice_id));
                const activated = unactivatedVoices.value.filter(
                    v => activeVoiceIds.has(v.voice_id)
                );
                if (activated.length > 0) {
                    // 从未激活列表中移除已激活的
                    const remaining = unactivatedVoices.value.filter(
                        v => !activeVoiceIds.has(v.voice_id)
                    );
                    await saveUnactivatedVoices(remaining);
                }
            } catch (e) {
                showError('获取音色列表失败: ' + e.message);
            } finally {
                voiceLoading.value = false;
            }
        }

        // 删除音色
        async function deleteVoice(voiceId) {
            showDeleteConfirm(
                '确认删除',
                `确定删除音色 ${voiceId} 吗？此操作不可撤销。`,
                async () => {
                    try {
                        await props.bridge.apiPost('voice/delete', {
                            entry_id: selectedEntryId.value,
                            voice_id: voiceId
                        });
                        showSuccess('删除成功');
                        await fetchVoiceList();
                    } catch (e) {
                        showError('删除失败: ' + e.message);
                    }
                }
            );
        }

        // 预览音色
        const previewModalVisible = ref(false);
        const previewVoiceId = ref('');

        function openPreview(voiceId) {
            previewVoiceId.value = voiceId;
            previewModalVisible.value = true;
        }

        // 预览成功后：若该音色属于未激活列表，则刷新以让它「消失」（被激活）
        async function onVoicePreviewed({ voiceId }) {
            if (unactivatedVoices.value.some(v => v.voice_id === voiceId)) {
                await fetchVoiceList();
                await loadUnactivatedVoices();
            }
        }

        // 复刻结果模态框
        const cloneResultModalVisible = ref(false);
        const cloneResult = ref(null);

        function closeCloneResult() {
            cloneResultModalVisible.value = false;
            cloneResult.value = null;
            fetchVoiceList();  // 刷新音色列表
        }

        function playDemoAudio() {
            if (cloneResult.value && cloneResult.value.demo_audio) {
                playAudio(cloneResult.value.demo_audio, 'demo_audio');
            } else {
                showError('没有试听音频');
            }
        }

        // ---------- 未激活音色管理 ----------
        const unactivatedVoices = ref([]);

        async function loadUnactivatedVoices() {
            try {
                const result = await props.bridge.apiPost('kv/get', {
                    key: 'bailian_minimax_unactivated_list'
                });
                const list = result.value ? JSON.parse(result.value) : [];
                unactivatedVoices.value = list;
            } catch (e) {
                console.warn('加载未激活音色列表失败:', e);
                unactivatedVoices.value = [];
            }
        }

        async function saveUnactivatedVoices(list) {
            await props.bridge.apiPost('kv/set', {
                key: 'bailian_minimax_unactivated_list',
                value: JSON.stringify(list)
            });
            unactivatedVoices.value = list;
        }

        async function addUnactivatedVoice(voiceInfo) {
            const list = [...unactivatedVoices.value];

            // 避免重复添加
            if (!list.some(v => v.voice_id === voiceInfo.voice_id)) {
                list.push({
                    voice_id: voiceInfo.voice_id,
                    type: voiceInfo.type || 'voice_cloning',
                    created_time: Date.now(),
                });
                await saveUnactivatedVoices(list);
            }
        }

        async function removeUnactivatedVoice(voiceId) {
            const list = unactivatedVoices.value.filter(v => v.voice_id !== voiceId);
            await saveUnactivatedVoices(list);
        }

        function showDeleteUnactivatedConfirm(voiceId) {
            showDeleteConfirm(
                '确认删除',
                `确定删除未激活音色 ${voiceId} 吗？此操作将同时从百炼服务端删除该音色，不可恢复。`,
                async () => {
                    try {
                        // 调用 API 删除服务端音色
                        await props.bridge.apiPost('voice/delete', {
                            entry_id: selectedEntryId.value,
                            voice_id: voiceId
                        });
                        // 删除本地
                        await removeUnactivatedVoice(voiceId);
                        showSuccess('已删除未激活音色');
                    } catch (e) {
                        showError('删除失败: ' + e.message);
                    }
                }
            );
        }

        async function keepUnactivatedVoice(result) {
            const voiceInfo = {
                voice_id: result.voice_id,
                type: 'voice_cloning',
                created_time: Date.now(),
            };
            await addUnactivatedVoice(voiceInfo);
            showSuccess('音色已保留到未激活列表，请通过预览激活');
            closeCloneResult();
        }

        // ---------- 克隆操作 ----------
        async function performClone() {
            if (!selectedEntryId.value) {
                showError('请先选择认证配置');
                return;
            }

            // 确定 audio_url：优先使用本地文件转换的 Data URL，否则使用手动输入的 URL
            let finalAudioUrl = '';
            if (audioFileBase64.value) {
                finalAudioUrl = audioFileBase64.value;
            } else if (cloneParams.audio_url.trim()) {
                finalAudioUrl = cloneParams.audio_url.trim();
            } else {
                showError('请选择音频文件或输入音频 URL');
                return;
            }

            if (!cloneParams.text.trim()) {
                showError('请输入试听文本');
                return;
            }
            if (textError.value) {
                showError(textError.value);
                return;
            }

            cloning.value = true;
            try {
                const payload = {
                    entry_id: selectedEntryId.value,
                    voice_id: cloneParams.voice_id.trim() || undefined,
                    audio_url: finalAudioUrl,
                    text: cloneParams.text.trim(),
                    model: cloneParams.model,
                    language_boost: cloneParams.language_boost || undefined,
                    need_noise_reduction: cloneParams.need_noise_reduction || undefined,
                    need_volume_normalization: cloneParams.need_volume_normalization || undefined,
                    aigc_watermark: cloneParams.aigc_watermark || undefined,
                };

                // 可选：示例音频
                if (promptFileBase64.value) {
                    if (!promptText.value.trim()) {
                        showError('请填写示例音频对应的文本内容');
                        cloning.value = false;
                        return;
                    }
                    payload.prompt_audio_url = promptFileBase64.value;
                    payload.prompt_text = promptText.value.trim();
                }

                const result = await props.bridge.apiPost('voice/create', payload);
                if (result.voice_id) {
                    showSuccess(`音色克隆成功！Voice ID: ${result.voice_id}`);
                    
                    // 如果有试听音频，显示试听模态框
                    if (result.demo_audio) {
                        cloneResult.value = result;
                        cloneResultModalVisible.value = true;
                    } else {
                        // 没有试听音频，直接刷新列表
                        await fetchVoiceList();
                    }
                    
                    // 清空表单（保留试听文本）
                    cloneParams.voice_id = '';
                    cloneParams.audio_url = '';
                    clearAudioFile();
                    clearPromptFile();
                } else {
                    showError('克隆失败: ' + (result.message || result.error || '未知错误'));
                }
            } catch (e) {
                showError('克隆失败: ' + e.message);
            } finally {
                cloning.value = false;
            }
        }

        // ---------- 复制功能 ----------
        const { copyText, copyLink } = useClipboard(showSuccess, showError);

        // ---------- 生命周期 ----------
        watch(selectedEntryId, (newId) => {
            if (newId && currentTab.value === 'list') {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        watch(currentTab, (newTab) => {
            if (newTab === 'list' && selectedEntryId.value) {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        onMounted(() => {
            if (selectedEntryId.value && currentTab.value === 'list') {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        // ---------- 计算属性 ----------
        const systemVoices = computed(() => {
            return voiceList.value.filter(v => v.type === 'system');
        });
        const customVoices = computed(() => {
            return voiceList.value.filter(v => v.type === 'voice_cloning');
        });

        // ---------- 删除确认模态框 ----------
        const deleteModal = reactive({
            visible: false,
            title: '确认删除',
            message: '',
            onConfirm: null,
        });

        function showDeleteConfirm(title, message, onConfirm) {
            deleteModal.title = title;
            deleteModal.message = message;
            deleteModal.onConfirm = onConfirm;
            deleteModal.visible = true;
        }

        function cancelDelete() {
            deleteModal.visible = false;
            deleteModal.onConfirm = null;
        }

        async function confirmDelete() {
            if (typeof deleteModal.onConfirm === 'function') {
                await deleteModal.onConfirm();
            }
            deleteModal.visible = false;
            deleteModal.onConfirm = null;
        }

        // ---------- 校验 ----------
        const voiceIdError = computed(() => {
            const id = cloneParams.voice_id.trim();
            if (!id) return '';
            if (id.length < 8 || id.length > 256) return '长度必须为 8~256 字符';
            if (!/^[A-Za-z]/.test(id)) return '首字符必须为英文字母';
            if (!/^[A-Za-z0-9\-_]+$/.test(id)) return '仅允许字母、数字、-、_';
            if (/[-_]$/.test(id)) return '末位字符不可为 - 或 _';
            return '';
        });

        const isVoiceIdValid = computed(() => {
            if (!cloneParams.voice_id.trim()) return true;
            return !voiceIdError.value;
        });

        const textError = computed(() => validateText(cloneParams.text, {
            label: '试听文本',
            max: 1000,
            required: true,
        }).error);

        const isTextValid = computed(() => !textError.value);

        // 克隆按钮启用条件
        const isUploadEnabled = computed(() => {
            return !!audioFileBase64.value &&
                cloneParams.text.trim() &&
                isVoiceIdValid.value &&
                isTextValid.value;
        });

        const isUrlEnabled = computed(() => {
            return !!cloneParams.audio_url.trim() &&
                cloneParams.text.trim() &&
                isVoiceIdValid.value &&
                isTextValid.value;
        });

        return {

            // Toast
            toastMessage, toastVisible, toastType,
            showToast, showSuccess, showError,
            onToastMouseEnter, onToastMouseLeave,

            // 认证
            selectedEntryId, currentEntry,

            // 音频
            volume, currentPlayingId,
            isPlaying, playAudio, stopAudio,

            // 选项卡
            currentTab,

            // 克隆
            cloneParams, cloning, fileInputRef, selectedAudioFile,
            promptFileInputRef, selectedPromptFile, promptText,
            performClone, handleAudioFileSelect, clearAudioFile,
            handlePromptFileSelect, clearPromptFile,

            // 音色列表
            voiceList, voiceLoading,
            systemVoices, customVoices,
            fetchVoiceList, deleteVoice, openPreview,

            // 预览
            previewModalVisible, previewVoiceId,

            // 复刻结果
            cloneResultModalVisible, cloneResult,
            closeCloneResult, playDemoAudio,

            // 未激活音色
            unactivatedVoices,
            loadUnactivatedVoices, addUnactivatedVoice, onVoicePreviewed,
            removeUnactivatedVoice, showDeleteUnactivatedConfirm, keepUnactivatedVoice,
            
            // 复制
            copyText, copyLink,

            // 删除确认
            deleteModal,
            cancelDelete, confirmDelete,

            // 校验
            voiceIdError, isVoiceIdValid,
            textError, isTextValid,
            isUploadEnabled, isUrlEnabled,
        };
    },
    template: /*html*/ `
<div class="bailian-tts">

    <!-- Toast -->
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
                {{ entry.display_name || ('配置 #' + entry.id) }}
            </option>
        </select>
    </div>

    <!-- 音色创建区域 -->
    <fieldset
        style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
    >
        <legend>创建新音色（声音克隆）</legend>

        <div
            style="
                background:rgba(241,151,27,0.15);
                border-left:4px solid #f0971b;
                padding:8px 12px;
                margin-bottom:16px;
                border-radius:4px;
                color:var(--text);
            "
        >
            <strong>💡 提示：</strong>首次使用复刻音色进行语音合成时将激活并扣除 9.9 元解锁费。
            <ul style="margin: 4px 0 0 0; padding-left: 20px; color: var(--text);">
                <li>
                    详见：<span class="link-copy"
                        @click="copyLink(
                            'https://docs.bailian.console.aliyun.com/zh/model-studio/model-pricing#minimax-2'
                        )"
                        style="color:var(--primary);cursor:pointer;text-decoration:underline;"
                    >模型调用价格</span>（点击复制链接）
                </li>
            </ul>
        </div>

        <!-- 选项卡切换 -->
        <div
            style="display:flex;gap:8px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;"
        >
            <button 
                class="tab" 
                :class="{ active: currentTab === 'upload' }"
                @click="currentTab = 'upload'"
                style="
                    padding:8px 16px;
                    border:none;
                    background:transparent;
                    cursor:pointer;
                    border-bottom:2px solid transparent;
                "
            >📁 上传音频文件</button>
            <button 
                class="tab" 
                :class="{ active: currentTab === 'url' }"
                @click="currentTab = 'url'"
                style="
                    padding:8px 16px;
                    border:none;
                    background:transparent;
                    cursor:pointer;
                    border-bottom:2px solid transparent;
                "
            >🔗 使用音频 URL</button>
            <button 
                class="tab" 
                :class="{ active: currentTab === 'list' }"
                @click="currentTab = 'list'"
                style="
                    padding:8px 16px;
                    border:none;
                    background:transparent;
                    cursor:pointer;
                    border-bottom:2px solid transparent;
                "
            >📋 音色列表</button>
        </div>

        <!-- 上传音频文件表单 -->
        <div v-if="currentTab === 'upload'">
            <div class="form-group">
                <label>选择本地音频文件（wav, mp3, m4a）</label>
                <input type="file" 
                    ref="fileInputRef"
                    @change="handleAudioFileSelect"
                    accept=".wav,.mp3,.m4a" />
                <div v-if="selectedAudioFile" class="hint" style="color:var(--primary);">
                    ✅ 已选择: {{ selectedAudioFile.name }} ({{ (selectedAudioFile.size / 1024).toFixed(1) }} KB)
                    <span style="color:var(--primary);cursor:pointer;text-decoration:underline;margin-left:8px;"
                        @click="clearAudioFile">清除</span>
                </div>
                <div class="hint">
                    时长最少应不低于 10s，最长应不超过 5 分钟；格式需为：mp3、m4a、wav；大小需不超过 20MB
                </div>
            </div>

            <div class="form-group">
                <label>自定义音色 ID（可选）</label>
                <input type="text" v-model="cloneParams.voice_id" 
                    placeholder="留空则自动生成" 
                    :class="{ 'input-error': !isVoiceIdValid }" />
                <div v-if="voiceIdError" class="error-hint">⚠️ {{ voiceIdError }}</div>
                <div class="hint">
                    长度 8-256，首字母必须为英文字母，允许数字、字母、- 和 _，末位字符不可为 - 或 _，不可与已有 ID 重复
                </div>
            </div>

            <div class="form-group">
                <label>试听文本</label>
                <textarea 
                    v-model="cloneParams.text" 
                    rows="3" 
                    placeholder="请输入试听文本，最多 1000 字符..." 
                    :class="{ 'input-error': !isTextValid }"
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
                <div v-if="textError" class="error-hint">⚠️ {{ textError }}</div>
                <div class="hint">试听将根据字符数正常收取语音合成费用，限制 1000 字符</div>
            </div>

            <div class="form-group">
                <label>模型版本</label>
                <select v-model="cloneParams.model">
                    <option value="HD">HD</option>
                    <option value="Turbo">Turbo</option>
                </select>
            </div>

            <div class="form-group">
                <label>语言增强</label>
                <select v-model="cloneParams.language_boost">
                    <option value="auto">auto（自动）</option>
                        <option value="Chinese">汉语</option>
                        <option value="Chinese,Yue">粤语</option>
                        <option value="English">英语</option>
                        <option value="Arabic">阿拉伯语</option>
                        <option value="Russian">俄语</option>
                        <option value="Spanish">西班牙语</option>
                        <option value="French">法语</option>
                        <option value="Portuguese">葡萄牙语</option>
                        <option value="German">德语</option>
                        <option value="Turkish">土耳其语</option>
                        <option value="Dutch">荷兰语</option>
                        <option value="Ukrainian">乌克兰语</option>
                        <option value="Vietnamese">越南语</option>
                        <option value="Indonesian">印尼语</option>
                        <option value="Japanese">日语</option>
                        <option value="Italian">意大利语</option>
                        <option value="Korean">韩语</option>
                        <option value="Thai">泰语</option>
                        <option value="Polish">波兰语</option>
                        <option value="Romanian">罗马尼亚语</option>
                        <option value="Greek">希腊语</option>
                        <option value="Czech">捷克语</option>
                        <option value="Finnish">芬兰语</option>
                        <option value="Hindi">印地语</option>
                        <option value="Bulgarian">保加利亚语</option>
                        <option value="Danish">丹麦语</option>
                        <option value="Hebrew">希伯来语</option>
                        <option value="Malay">马来语</option>
                        <option value="Persian">波斯语</option>
                        <option value="Slovak">斯洛伐克语</option>
                        <option value="Swedish">瑞典语</option>
                        <option value="Croatian">克罗地亚语</option>
                        <option value="Filipino">菲律宾语</option>
                        <option value="Hungarian">匈牙利语</option>
                        <option value="Norwegian">挪威语</option>
                        <option value="Slovenian">斯洛文尼亚语</option>
                        <option value="Catalan">加泰罗尼亚语</option>
                        <option value="Nynorsk">挪威尼诺斯克语</option>
                        <option value="Tamil">泰米尔语</option>
                        <option value="Afrikaans">南非荷兰语</option>
                </select>
                <div class="hint">增强对指定语种的识别能力，一般设置为 auto</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_noise_reduction" id="upload_noise" />
                <label for="upload_noise">开启降噪</label>
                <div class="hint">有背景噪音时建议开启</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_volume_normalization" id="upload_vol_norm" />
                <label for="upload_vol_norm">开启音量归一化</label>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.aigc_watermark" id="upload_aigc" />
                <label for="upload_aigc">添加 AIGC 水印</label>
                <div class="hint">在合成音频末尾添加音频节奏标识</div>
            </div>

            <div class="form-group">
                <label>示例音频（可选，增强相似度）</label>
                <input type="file" 
                    ref="promptFileInputRef"
                    @change="handlePromptFileSelect"
                    accept=".wav,.mp3,.m4a" />
                <div v-if="selectedPromptFile" class="hint" style="color:var(--primary);">
                    ✅ 已选择: {{ selectedPromptFile.name }} ({{ (selectedPromptFile.size / 1024).toFixed(1) }} KB)
                    <span style="color:var(--primary);cursor:pointer;text-decoration:underline;margin-left:8px;"
                        @click="clearPromptFile">清除</span>
                </div>
                <div class="hint">可选，时长 < 8s，文件 ≤ 20MB。提供示例音频可增强音色相似度</div>
            </div>

            <div v-if="selectedPromptFile" class="form-group">
                <label>示例音频文本</label>
                <input type="text" v-model="promptText" 
                    placeholder="请输入示例音频对应的文本内容" />
                <div class="hint">示例音频对应的文本内容，需与音频内容一致</div>
            </div>

            <button
                class="btn"
                @click="performClone"
                :disabled="!isUploadEnabled || cloning"
            >
                {{ cloning ? '克隆中...' : '📁 上传并克隆' }}
            </button>
        </div>

        <!-- 使用音频 URL 表单 -->
        <div v-if="currentTab === 'url'">
            <div class="form-group">
                <label>公网音频 URL</label>
                <input type="url" v-model="cloneParams.audio_url" 
                    placeholder="例如：https://example.com/voice.wav" />
                <div class="hint">音频文件的可访问 URL，支持 WAV/MP3/M4A 格式</div>
            </div>

            <div class="form-group">
                <label>自定义音色 ID（可选）</label>
                <input type="text" v-model="cloneParams.voice_id" 
                    placeholder="留空则自动生成" 
                    :class="{ 'input-error': !isVoiceIdValid }" />
                <div v-if="voiceIdError" class="error-hint">⚠️ {{ voiceIdError }}</div>
            </div>

            <div class="form-group">
                <label>试听文本</label>
                <textarea 
                    v-model="cloneParams.text" 
                    rows="3" 
                    placeholder="请输入试听文本，最多 1000 字符..." 
                    :class="{ 'input-error': !isTextValid }"
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
                <div v-if="textError" class="error-hint">⚠️ {{ textError }}</div>
                <div class="hint">克隆成功后将使用此文本生成试听音频，限制 1000 字符</div>
            </div>

            <div class="form-group">
                <label>模型版本</label>
                <select v-model="cloneParams.model">
                    <option value="HD">HD</option>
                    <option value="Turbo">Turbo</option>
                </select>
            </div>

            <div class="form-group">
                <label>语言增强</label>
                <select v-model="cloneParams.language_boost">
                    <option value="auto">auto（自动）</option>
                    <option value="Chinese">汉语</option>
                    <option value="Chinese,Yue">粤语</option>
                    <option value="English">英语</option>
                    <option value="Japanese">日语</option>
                    <option value="Korean">韩语</option>
                    <option value="Russian">俄语</option>
                    <option value="Spanish">西班牙语</option>
                    <option value="French">法语</option>
                    <option value="German">德语</option>
                </select>
                <div class="hint">增强对指定语种的识别能力，一般设置为 auto</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_noise_reduction" id="url_noise" />
                <label for="url_noise">开启降噪</label>
                <div class="hint">有背景噪音时建议开启</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_volume_normalization" id="url_vol_norm" />
                <label for="url_vol_norm">开启音量归一化</label>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.aigc_watermark" id="url_aigc" />
                <label for="url_aigc">添加 AIGC 水印</label>
                <div class="hint">在合成音频末尾添加音频节奏标识</div>
            </div>

            <div class="form-group">
                <label>示例音频（可选，增强相似度）</label>
                <input type="file" 
                    ref="promptFileInputRef"
                    @change="handlePromptFileSelect"
                    accept=".wav,.mp3,.m4a" />
                <div v-if="selectedPromptFile" class="hint" style="color:var(--primary);">
                    ✅ 已选择: {{ selectedPromptFile.name }} ({{ (selectedPromptFile.size / 1024).toFixed(1) }} KB)
                    <span style="color:var(--primary);cursor:pointer;text-decoration:underline;margin-left:8px;"
                        @click="clearPromptFile">清除</span>
                </div>
                <div class="hint">可选，时长 &lt; 8 秒，文件 ≤ 20MB。提供示例音频可增强音色相似度</div>
            </div>

            <div v-if="selectedPromptFile" class="form-group">
                <label>示例音频文本</label>
                <input type="text" v-model="promptText" 
                    placeholder="请输入示例音频对应的文本内容" />
                <div class="hint">示例音频对应的文本内容，需与音频内容一致</div>
            </div>

            <button
                class="btn"
                @click="performClone"
                :disabled="!isUrlEnabled || cloning"
            >
                {{ cloning ? '克隆中...' : '🔗 使用 URL 克隆' }}
            </button>
        </div>

        <!-- 音色列表 -->
        <div v-if="currentTab === 'list'">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h3 style="margin:0;">音色列表</h3>
                <button class="btn btn-sm" @click="fetchVoiceList" :disabled="voiceLoading">刷新</button>
            </div>
            <div v-if="voiceLoading">加载中...</div>
            <template v-else>
                <!-- 未激活音色 -->
                <template v-if="unactivatedVoices.length">
                    <!-- 提示横幅 -->
                    <div style="margin: 8px 0 12px 0;
                        padding: 8px 14px;
                        background: rgba(59, 130, 246, 0.12);
                        border-left: 4px solid #3b82f6;
                        border-radius: var(--radius);
                        color: var(--text);
                        font-size: 0.85rem;
                        line-height: 1.5;"
                    >
                        <span>💡</span>
                        <span>
                            这些音色尚未激活，点击 <strong>“预览（激活）”</strong> 可调用一次语音合成激活音色，<!--
                            -->激活后音色将出现在复刻音色列表中，并扣取相应费用。
                        </span>
                    </div>
                    <h4 style="margin:16px 0 8px 0;">⏳ 未激活音色</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>Voice ID</th>
                                <th>类型</th>
                                <th>创建时间</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="v in unactivatedVoices" :key="v.voice_id">
                                <td>{{ v.voice_id }}</td>
                                <td>{{ v.type || 'voice_cloning' }}</td>
                                <td>{{ v.created_time ? new Date(v.created_time).toLocaleString() : '-' }}</td>
                                <td>
                                    <button class="btn btn-sm" @click="copyText(v.voice_id)">复制</button>
                                    <button class="btn btn-sm" @click="openPreview(v.voice_id)">预览（激活）</button>
                                    <button class="btn btn-danger btn-sm" @click="showDeleteUnactivatedConfirm(v.voice_id)">
                                        删除
                                    </button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </template>

                <!-- 复刻音色 -->
                <template v-if="customVoices.length">
                    <h4 style="margin:16px 0 8px 0;">🎤 复刻音色</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>Voice ID</th>
                                <th>名称</th>
                                <th>创建时间</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="v in customVoices" :key="v.voice_id">
                                <td>{{ v.voice_id }}</td>
                                <td>{{ v.voice_name || '-' }}</td>
                                <td>{{ v.created_at || '-' }}</td>
                                <td>
                                    <button
                                        class="btn btn-sm"
                                        @click="copyText(v.voice_id)"
                                        title="复制 ID"
                                        style="margin-right: 4px;"
                                    >复制</button>
                                    <button
                                        class="btn btn-sm"
                                        @click="openPreview(v.voice_id)"
                                        title="预览音色"
                                        style="margin-right: 4px;"
                                    >预览</button>
                                    <button
                                        class="btn btn-danger btn-sm"
                                        @click="deleteVoice(v.voice_id)"
                                    >删除</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </template>

                <!-- 系统音色 -->
                <template v-if="systemVoices.length">
                    <h4 style="margin:16px 0 8px 0;">🎙️ 系统音色</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>Voice ID</th>
                                <th>名称</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="v in systemVoices" :key="v.voice_id">
                                <td>{{ v.voice_id }}</td>
                                <td>{{ v.voice_name || '-' }}</td>
                                <td>
                                    <button
                                        class="btn btn-sm"
                                        @click="copyText(v.voice_id)"
                                        title="复制 ID"
                                        style="margin-right: 4px;"
                                    >复制</button>
                                    <button
                                        class="btn btn-sm"
                                        @click="openPreview(v.voice_id)"
                                        title="预览音色"
                                    >预览</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </template>

                <!-- 空状态 -->
                <div v-if="!voiceList.length && !unactivatedVoices.length"
                    style="text-align:center;color:var(--gray);padding:20px 0;">
                    暂无音色
                </div>
            </template>
        </div>
    </fieldset>

    <!-- 复刻结果试听模态框 -->
    <div v-if="cloneResultModalVisible" class="modal-overlay" @mousedown.self="closeCloneResult">
        <div class="modal-content" style="max-width:500px;">
            <h3>✅ 克隆成功</h3>
            <p><strong>Voice ID:</strong> {{ cloneResult.voice_id }}</p>
            <p style="color:var(--gray);font-size:0.85rem;">
                音色当前处于未激活状态，需要在语音合成接口中正式调用一次方可激活。
            </p>
            <div v-if="cloneResult.demo_audio">
                <button class="btn" @click="playDemoAudio"
                    :class="{'btn-danger': currentPlayingId === 'demo_audio'}">
                    {{ currentPlayingId === 'demo_audio' ? '⏹ 停止' : '▶ 播放试听音频' }}
                </button>
            </div>
            <div style="margin-top:16px;display:flex;gap:12px;justify-content:flex-end;">
                <button class="btn btn-danger" @click="showDeleteUnactivatedConfirm(cloneResult.voice_id)">
                    删除
                </button>
                <button class="btn btn-success" @click="keepUnactivatedVoice(cloneResult)">
                    保留
                </button>
            </div>
        </div>
    </div>

    <!-- 预览模态框 -->
    <VoicePreviewModal
        v-model:visible="previewModalVisible"
        :bridge="bridge"
        :entry-id="selectedEntryId"
        :voice-id="previewVoiceId"
        id-prefix="bailian_minimax_preview"
        @previewed="onVoicePreviewed"
    />

    <!-- 删除确认模态框 -->
    <DeleteConfirmModal
        :visible="deleteModal.visible"
        :title="deleteModal.title"
        :message="deleteModal.message"
        @confirm="confirmDelete"
        @cancel="cancelDelete"
    />
</div>
`
};
