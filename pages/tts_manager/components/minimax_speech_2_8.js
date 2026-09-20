const { ref, reactive, computed, watch, onMounted, nextTick } = Vue;


import { useToast } from '../composables/useToast.js';
import { useClipboard } from '../composables/useClipboard.js';
import { useAudioManager } from '../composables/useAudioManager.js';
import { validateText, countChars } from '../composables/useTextValidator.js'
import VoicePreviewModal from './common/voice_preview_modal.js';
import DeleteConfirmModal from './common/delete_confirm_modal.js';


export default {
    name: 'MinimaxSpeech2_8',
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

        // ---------- 全局音频控制（单例，跨组件共享音量与播放状态） ----------
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
        const currentTab = ref('clone'); // 'clone' | 'design' | 'list'

        // ---------- 复刻音频管理 ----------
        const cloneFiles = ref([]);
        const cloneLoading = ref(false);
        const cloneUploading = ref(false);
        const selectedCloneFileId = ref(null); // 选中的主音频 file_id

        // 上传复刻音频
        const cloneFileInput = ref(null);
        const cloneCustomFileName = ref('');

        async function handleCloneUpload() {
            const input = cloneFileInput.value;
            if (!input || !input.files || !input.files[0]) {
                showError('请选择一个文件');
                return;
            }
            const file = input.files[0];
            if (!selectedEntryId.value) {
                showError('请先选择认证配置');
                return;
            }
            cloneUploading.value = true;
            try {

                // 1. 上传到本地
                const uploadResult = await props.bridge.upload('upload', file);
                if (!uploadResult.file_id) {
                    showError(
                        '上传失败: ' + (uploadResult.message || uploadResult.error || '未知错误')
                    );
                    return;
                }
                const localFileId = uploadResult.file_id;

                // 2. 调用 /file/upload 传递给供应商
                const payload = {
                    entry_id: selectedEntryId.value,
                    file_id: localFileId,
                    purpose: 'voice_clone'
                };
                const customName = cloneCustomFileName.value.trim();
                if (customName) {
                    payload.filename = customName;
                }

                const result = await props.bridge.apiPost('file/upload', payload);
                if (result.file_id) {
                    showSuccess('复刻音频上传成功');
                    cloneCustomFileName.value = '';

                    // 清空文件选择
                    input.value = '';
                    await fetchCloneFiles();
                } else {
                    showError('上传失败: ' + (result.message || result.error || '未知错误'));
                }
            } catch (e) {
                showError('上传失败: ' + e.message);
            } finally {
                cloneUploading.value = false;
            }
        }

        async function fetchCloneFiles() {
            if (!selectedEntryId.value) return;
            cloneLoading.value = true;
            try {
                const result = await props.bridge.apiPost('file/list', {
                    entry_id: selectedEntryId.value,
                    purpose: 'voice_clone'
                });
                cloneFiles.value = result.files || [];
            } catch (e) {
                showError('获取复刻音频列表失败: ' + e.message);
            } finally {
                cloneLoading.value = false;
            }
        }

        async function deleteCloneFile(fileId) {
            showDeleteConfirm(
                '确认删除',
                `确定删除复刻音频 ${fileId} 吗？`,
                async () => {
                    await props.bridge.apiPost('file/delete', {
                        entry_id: selectedEntryId.value,
                        file_id: fileId,
                        purpose: 'voice_clone'
                    });
                    showSuccess('删除成功');
                    if (selectedCloneFileId.value === fileId) {
                        selectedCloneFileId.value = null;
                    }
                    await fetchCloneFiles();
                }
            );
        }

        // ---------- 示例音频管理 ----------
        const promptFiles = ref([]);
        const promptLoading = ref(false);
        const promptUploading = ref(false);

        // 存储每个示例音频的源文本（从KV加载）
        const promptTexts = reactive({}); // { file_id: text }

        // 编辑状态
        const editingPrompt = ref(null); // file_id

        const promptFileInput = ref(null);
        const promptTextInput = ref('');
        const promptCustomFileName = ref('');

        // ---------- 示例音频上传 ----------
        async function handlePromptUpload() {
            const input = promptFileInput.value;
            if (!input || !input.files || !input.files[0]) {
                showError('请选择一个文件');
                return;
            }
            const file = input.files[0];
            if (!selectedEntryId.value) {
                showError('请先选择认证配置');
                return;
            }
            const text = promptTextInput.value.trim();
            if (!text) {
                showError('请输入源文本（音频对应的文字内容）');
                return;
            }
            promptUploading.value = true;
            try {

                // 1. 上传到本地
                const uploadResult = await props.bridge.upload('upload', file);
                if (!uploadResult.file_id) {
                    showError(
                        '上传失败: ' + (uploadResult.message || uploadResult.error || '未知错误')
                    );
                    return;
                }
                const localFileId = uploadResult.file_id;

                // 2. 调用 /file/upload 传递给供应商
                const payload = {
                    entry_id: selectedEntryId.value,
                    file_id: localFileId,
                    purpose: 'prompt_audio'
                };
                const customName = promptCustomFileName.value.trim();
                if (customName) {
                    payload.filename = customName;
                }

                const result = await props.bridge.apiPost('file/upload', payload);
                if (result.file_id) {

                    // 3. 保存源文本到 KV
                    await props.bridge.apiPost('kv/set', {
                        key: `minimax_prompt_${result.file_id}`,
                        value: text
                    });
                    showSuccess('示例音频上传成功');
                    promptTextInput.value = '';
                    promptCustomFileName.value = '';
                    input.value = '';
                    await fetchPromptFiles();
                } else {
                    showError('上传失败: ' + (result.message || result.error || '未知错误'));
                }
            } catch (e) {
                showError('上传失败: ' + e.message);
            } finally {
                promptUploading.value = false;
            }
        }

        async function fetchPromptFiles() {
            if (!selectedEntryId.value) return;
            promptLoading.value = true;
            try {
                const result = await props.bridge.apiPost('file/list', {
                    entry_id: selectedEntryId.value,
                    purpose: 'prompt_audio'
                });
                promptFiles.value = result.files || [];

                // 加载每个文件的源文本
                for (const f of promptFiles.value) {
                    const fileId = f.file_id;
                    if (!(fileId in promptTexts)) {
                        const kv = await props.bridge.apiPost('kv/get', {
                            key: `minimax_prompt_${fileId}`
                        });
                        promptTexts[fileId] = kv.value || '';
                    }
                }
            } catch (e) {
                showError('获取示例音频列表失败: ' + e.message);
            } finally {
                promptLoading.value = false;
            }
        }

        async function savePromptText(fileId) {
            const text = promptTexts[fileId] || '';
            if (!text.trim()) {
                showError('源文本不能为空');
                return;
            }
            try {
                await props.bridge.apiPost('kv/set', {
                    key: `minimax_prompt_${fileId}`,
                    value: text
                });
                showSuccess('源文本已保存');
                editingPrompt.value = null;
            } catch (e) {
                showError('保存失败: ' + e.message);
            }
        }

        async function deletePromptFile(fileId) {
            showDeleteConfirm(
                '确认删除',
                `确定删除示例音频 ${fileId} 吗？`,
                async () => {
                    await props.bridge.apiPost('file/delete', {
                        entry_id: selectedEntryId.value,
                        file_id: fileId,
                        purpose: 'prompt_audio'
                    });
                    await props.bridge.apiPost('kv/delete', {
                        key: `minimax_prompt_${fileId}`
                    });
                    delete promptTexts[fileId];
                    showSuccess('删除成功');
                    await fetchPromptFiles();
                }
            );
        }

        // 判断示例音频是否可绑定（源文本非空）
        function isPromptBindable(fileId) {
            return !!(promptTexts[fileId] && promptTexts[fileId].trim());
        }

        // ---------- 音频播放（通用） ----------

        // 从 file_id 获取音频内容并播放
        async function playFile(fileId) {
            try {
                const result = await props.bridge.apiPost('file/get', {
                    entry_id: selectedEntryId.value,
                    file_id: fileId
                });
                if (result.audio_base64) {
                    const buttonId = 'file_' + fileId;

                    // 先构造 Blob URL 再播放
                    const audioBytes = Uint8Array.from(
                        atob(result.audio_base64), c => c.charCodeAt(0)
                    );
                    const blob = new Blob([audioBytes], { type: 'audio/mp3' });
                    const url = URL.createObjectURL(blob);
                    playAudio(url, buttonId, () => URL.revokeObjectURL(url));
                } else {
                    showError('未获取到音频数据');
                }
            } catch (e) {
                showError('获取音频失败: ' + e.message);
            }
        }

        // ---------- 复刻操作 ----------
        const cloneParams = reactive({
            voice_id: '',
            text: '',
            model: 'HD',
            language_boost: 'auto',
            text_validation: '',
            accuracy: 0.7,
            need_noise_reduction: false,
            need_volume_normalization: false,
            aigc_watermark: false,
        });

        const selectedPromptFileId = ref(null); // 示例音频选择
        const cloning = ref(false);

        // 可选的示例音频列表（仅源文本已绑定的）
        const bindablePrompts = computed(() => {
            return promptFiles.value.filter(f => isPromptBindable(f.file_id));
        });

        async function performClone() {
            if (!selectedEntryId.value) {
                showError('请先选择认证配置');
                return;
            }
            if (!selectedCloneFileId.value) {
                showError('请选择一个主音频（复刻音频）');
                return;
            }
            const payload = {
                entry_id: selectedEntryId.value,
                mode: 'clone',
                file_id: selectedCloneFileId.value,
                voice_id: cloneParams.voice_id || undefined,
                text: cloneParams.text || undefined,
                model: `speech-2.8-${cloneParams.model.toLowerCase()}`,
                language_boost: cloneParams.language_boost || undefined,
                text_validation: cloneParams.text_validation || undefined,
                accuracy: cloneParams.accuracy,
                need_noise_reduction: cloneParams.need_noise_reduction,
                need_volume_normalization: cloneParams.need_volume_normalization,
                aigc_watermark: cloneParams.aigc_watermark,
            };
            if (selectedPromptFileId.value) {

                // 验证源文本存在
                const promptText = promptTexts[selectedPromptFileId.value] || '';
                if (!promptText.trim()) {
                    showError('所选示例音频缺少源文本，请先绑定');
                    return;
                }
                payload.prompt_file_id = selectedPromptFileId.value;
                payload.prompt_text = promptText;
            }
            cloning.value = true;
            try {
                const result = await props.bridge.apiPost('voice/create', payload);
                if (result.voice_id) {
                    showSuccess(`音色克隆成功！Voice ID: ${result.voice_id}`);

                    // 如果有试听音频，打开模态框
                    if (result.demo_audio) {
                        cloneResult.value = result;
                        cloneResultModalVisible.value = true;
                    } else {

                        // 无试听，直接刷新音色列表
                        await fetchVoiceList();
                    }
                } else {
                    showError('克隆失败: ' + (result.message || result.error || '未知错误'));
                }
            } catch (e) {
                showError('克隆失败: ' + e.message);
            } finally {
                cloning.value = false;
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

        // ---------- 声音设计 ----------
        const designForm = reactive({
            prompt: '',
            preview_text: '欢迎使用 MiniMax 声音设计功能。',
            voice_id: '',
            aigc_watermark: false,
        });
        const designing = ref(false);
        const designResultModalVisible = ref(false);
        const designResult = ref(null);

        async function performDesign() {
            if (!selectedEntryId.value) {
                showError('请先选择认证配置');
                return;
            }
            if (designPromptError.value) {
                showError(designPromptError.value);
                return;
            }
            if (designTextError.value) {
                showError(designTextError.value);
                return;
            }
            designing.value = true;
            try {
                const payload = {
                    entry_id: selectedEntryId.value,
                    mode: 'design',
                    prompt: designForm.prompt,
                    preview_text: designForm.preview_text,
                    voice_id: designForm.voice_id || undefined,
                    aigc_watermark: designForm.aigc_watermark,
                };
                const result = await props.bridge.apiPost('voice/create', payload);
                if (result.voice_id) {
                    showSuccess(`音色设计成功！Voice ID: ${result.voice_id}`);
                    if (result.trial_audio) {
                        designResult.value = result;
                        designResultModalVisible.value = true;
                    } else {
                        await fetchVoiceList();
                    }
                } else {
                    showError('设计失败: ' + (result.message || result.error || '未知错误'));
                }
            } catch (e) {
                showError('设计失败: ' + e.message);
            } finally {
                designing.value = false;
            }
        }

        function closeDesignResult() {
            designResultModalVisible.value = false;
            designResult.value = null;
            fetchVoiceList();
        }

        function hexToUint8Array(hex) {
            if (!hex) return null;
            const bytes = new Uint8Array(hex.length / 2);
            for (let i = 0; i < hex.length; i += 2) {
                bytes[i/2] = parseInt(hex.substr(i, 2), 16);
            }
            return bytes;
        }

        function playTrialAudio() {
            if (designResult.value && designResult.value.trial_audio) {
                const hex = designResult.value.trial_audio;
                const bytes = hexToUint8Array(hex);
                if (!bytes) {
                    showError('试听音频数据无效');
                    return;
                }
                const blob = new Blob([bytes], { type: 'audio/mp3' });
                const url = URL.createObjectURL(blob);
                playAudio(url, 'trial_audio', () => URL.revokeObjectURL(url));
            } else {
                showError('没有试听音频');
            }
        }

        // ---------- 音色列表 ----------
        const voiceList = ref([]);
        const voiceLoading = ref(false);
        const voiceListRefresh = ref(0);

        async function fetchVoiceList() {
            if (!selectedEntryId.value) return;
            voiceLoading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/list', {
                    entry_id: selectedEntryId.value,
                    voice_type: 'all' // 获取所有类型
                });

                // 后端 list_voice 返回 items 和 total，但 MiniMax 适配器 list_voice 返回包含 items
                voiceList.value = result.items || [];

                // 检查未激活音色是否已出现在自定义列表中
                const activeVoiceIds = new Set(voiceList.value.map(v => v.voice_id));
                const unactivated = unactivatedVoices.value.filter(
                    v => activeVoiceIds.has(v.voice_id)
                );
                if (unactivated.length > 0) {

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
        async function deleteVoice(voiceId, voiceType) {
            showDeleteConfirm(
                '确认删除',
                `确定删除音色 ${voiceId} 吗？`,
                async () => {
                    await props.bridge.apiPost('voice/delete', {
                        entry_id: selectedEntryId.value,
                        voice_id: voiceId,
                        voice_type: voiceType
                    });
                    showSuccess('删除成功');
                    await fetchVoiceList();
                }
            );
        }

        // 预览音色（调用 /voice/preview）
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

        // ---------- 复制功能 ----------
        const { copyText, copyLink } = useClipboard(showSuccess, showError);

        // ---------- 生命周期 ----------
        watch(selectedEntryId, (newId) => {
            if (newId) {
                fetchCloneFiles();
                fetchPromptFiles();
                if (currentTab.value === 'list') {
                    loadUnactivatedVoices();
                    fetchVoiceList()
                }
            }
        });

        watch(currentTab, (newTab) => {
            if (newTab === 'list' && selectedEntryId.value) {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        onMounted(() => {

            // 初始加载
            if (selectedEntryId.value) {
                fetchCloneFiles();
                fetchPromptFiles();
                if (currentTab.value === 'list') {
                    fetchVoiceList();
                    loadUnactivatedVoices();
                }
            }
        });

        const systemVoices = computed(() => {
            return voiceList.value.filter(v => v.type === 'system');
        });
        const customVoices = computed(() => {
            return voiceList.value.filter(v => v.type !== 'system');
        });

        // ---------- 通用删除模态框 ----------
        const deleteModal = reactive({
            visible: false,
            title: '确认删除',
            message: '',
            onConfirm: null, // 要执行的回调函数
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

        // ---------- 校验计算属性 ----------
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
        }).error);

        const textValidationError = computed(() => validateText(cloneParams.text_validation, {
            label: 'ASR 验证文本',
            max: 200,
        }).error);

        const isTextValid = computed(() => !textError.value);
        const isTextValidationValid = computed(() => !textValidationError.value);

        const isCloneEnabled = computed(() => {
            return selectedCloneFileId.value !== null &&
                isVoiceIdValid.value &&
                isTextValid.value &&
                isTextValidationValid.value;
        });

        // 上传启用条件
        const isCloneUploadEnabled = computed(() => {
            return cloneFileInput.value &&
                cloneFileInput.value.files &&
                cloneFileInput.value.files[0];
        });

        const isPromptUploadEnabled = computed(() => {
            return promptFileInput.value &&
                promptFileInput.value.files &&
                promptFileInput.value.files[0] &&
                promptTextInput.value.trim().length > 0;
        });

        // ---------- 声音设计校验 ----------
        const designPromptError = computed(() => validateText(designForm.prompt, {
            label: '音色描述',
            required: true,
        }).error);

        const designTextError = computed(() => validateText(designForm.preview_text, {
            label: '预览文本',
            max: 500,
            required: true,
        }).error);

        const designVoiceIdError = computed(() => {
            const id = designForm.voice_id.trim();
            if (!id) return '';
            if (id.length < 8 || id.length > 256) return '长度必须为 8~256 字符';
            if (!/^[A-Za-z]/.test(id)) return '首字符必须为英文字母';
            if (!/^[A-Za-z0-9\-_]+$/.test(id)) return '仅允许字母、数字、-、_';
            if (/[-_]$/.test(id)) return '末位字符不可为 - 或 _';
            return '';
        });

        const isDesignVoiceIdValid = computed(() => {
            if (!designForm.voice_id.trim()) return true;
            return !designVoiceIdError.value;
        });

        const isDesignEnabled = computed(() => {
            return designForm.prompt.trim().length > 0 &&
                !designTextError.value &&
                isDesignVoiceIdValid.value;
        });

        // ---------- 未激活音色管理 ----------
        const unactivatedVoices = ref([]);

        async function loadUnactivatedVoices() {
            try {
                const result = await props.bridge.apiPost('kv/get', {
                    key: 'minimax_unactivated_list'
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
                key: 'minimax_unactivated_list',
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
                    description: voiceInfo.description || []
                });
                await saveUnactivatedVoices(list);
            }
        }

        async function removeUnactivatedVoice(voiceId) {
            const list = unactivatedVoices.value.filter(v => v.voice_id !== voiceId);
            await saveUnactivatedVoices(list);
        }

        function showDeleteUnactivatedConfirm(voiceId) {

        // 从 unactivatedVoices 中找到对应的条目
        const entry = unactivatedVoices.value.find(v => v.voice_id === voiceId);
        if (!entry) {
            showError('未找到该未激活音色');
            return;
        }
        const voiceType = entry.type || 'voice_cloning';
        showDeleteConfirm(
            '确认删除',
            `确定删除未激活音色 ${voiceId} 吗？此操作将同时从 MiniMax 服务端删除该音色，不可恢复。`,
            async () => {
                try {

                    // 调用 API 删除服务端音色
                    await props.bridge.apiPost('voice/delete', {
                        entry_id: selectedEntryId.value,
                        voice_id: voiceId,
                        voice_type: voiceType
                    });

                    // 删除本地
                    await removeUnactivatedVoice(voiceId);
                    showSuccess('已删除未激活音色');

                    // 如果是复刻或设计结果模态框，关闭它们
                    if (cloneResultModalVisible.value) {
                        closeCloneResult();
                    }
                    if (designResultModalVisible.value) {
                        closeDesignResult();
                    }
                } catch (e) {
                    showError('删除失败: ' + e.message);
                }
            }
        );
    }

        async function keepUnactivatedVoice(result, type) {
            const voiceInfo = {
                voice_id: result.voice_id,
                type: type,
                created_time: Date.now(),
                description: []  // 没有描述
            };
            await addUnactivatedVoice(voiceInfo);
            showSuccess('音色已保留到未激活列表，请通过预览激活');
            if (type === 'voice_cloning') {
                closeCloneResult();
            } else {
                closeDesignResult();
            }
        }

        // 返回所有响应式数据和方法
        return {

            // 通知框
            toastMessage, toastVisible, toastType,
            onToastMouseEnter, onToastMouseLeave,

            // 通用
            selectedEntryId, currentEntry, currentTab,

            // 音量控制
            volume, currentPlayingId,
            playAudio, stopAudio, isPlaying,

            // 复刻音频
            cloneFiles, cloneLoading, cloneUploading,
            selectedCloneFileId, cloneFileInput, cloneCustomFileName,
            handleCloneUpload, fetchCloneFiles, deleteCloneFile, playFile,

            // 示例音频
            promptFiles, promptLoading, promptUploading, promptCustomFileName,
            promptTexts, editingPrompt, promptFileInput, promptTextInput, bindablePrompts,
            handlePromptUpload, fetchPromptFiles, savePromptText,
            deletePromptFile, isPromptBindable,

            // 复刻参数
            cloneParams, selectedPromptFileId, cloning,
            performClone,

            // 复刻结果
            cloneResultModalVisible, cloneResult,
            closeCloneResult, playDemoAudio,

            // 声音设计
            designForm, designing, designResultModalVisible, designResult,
            performDesign, closeDesignResult, playTrialAudio,

            // 音色列表
            voiceList, voiceLoading, systemVoices, customVoices,
            previewModalVisible, previewVoiceId,
            openPreview, onVoicePreviewed, fetchVoiceList, deleteVoice,
            

            // 提示
            showSuccess, showError,

            // 复制
            copyText, copyLink,

            // 删除模态框
            deleteModal,
            showDeleteConfirm, cancelDelete, confirmDelete,

            // 校验
            voiceIdError, isVoiceIdValid, textError, isTextValid, textValidationError,
            isTextValidationValid, isCloneEnabled, isCloneUploadEnabled, isPromptUploadEnabled,
            designPromptError, designTextError, designVoiceIdError,
            isDesignVoiceIdValid, isDesignEnabled,
            countChars,

            // 未激活音色
            unactivatedVoices,
            loadUnactivatedVoices, saveUnactivatedVoices, addUnactivatedVoice,
            removeUnactivatedVoice, showDeleteUnactivatedConfirm, keepUnactivatedVoice,
        };
    },
    template: /* html */ `
    <div class="minimax-tts">

        <!-- Toast -->
        <div
            v-if="toastVisible"
            class="toast"
            :class="{'toast-error': toastType === 'error'}"
            @mouseenter="onToastMouseEnter"
            @mouseleave="onToastMouseLeave"
        >
            {{ toastMessage }}
        </div>

        <!-- 认证配置 -->
        <div class="form-group">
            <label>认证配置</label>
            <select v-model="selectedEntryId">
                <option v-for="entry in entries" :key="entry.id" :value="entry.id">
                    {{ entry.display_name || entry.api_key }}
                </option>
            </select>
            <span v-if="currentEntry" style="margin-left:12px;color:var(--gray);font-size:0.9rem;">
                API Key: {{ currentEntry.api_key }}
            </span>
        </div>

        <!-- 重要通知横幅 -->
        <div style="margin: 12px 0 16px 0;
            padding: 12px 16px;
            background: rgba(245, 158, 11, 0.15);
            border-left: 4px solid #f59e0b;
            border-radius: var(--radius);
            color: var(--text);
            font-size: 0.9rem;
            line-height: 1.6;"
        >
            <div style="display: flex; align-items: flex-start; gap: 8px;">
                <span style="font-size: 1.2rem;">⚠️</span>
                <div>
                    <strong>重要：音色复刻与音色设计产出的均为临时（未激活）音色</strong>
                    <ul style="margin: 4px 0 0 0; padding-left: 20px; color: var(--text);">
                        <li>费用在首次用于语音合成时才收取（<strong>不含</strong>接口内试听）</li>
                        <li>若 <strong>168h（7 天）</strong>内未在任意语音合成接口中使用，该音色将被删除</li>
                        <li>
                            <strong>本界面音色列表中的预览功能会调用一次语音合成</strong>，<!--
                            -->因此需要的音色可通过预览一次保留，不想要的音色请勿点击预览避免扣费
                        </li>
                        <li>
                            详见：<span class="link-copy"
                                @click="copyLink(
                                    'https://platform.minimaxi.com/docs/guides/pricing-paygo#%E8%AF%AD%E9%9F%B3'
                                )"
                                style="color:var(--primary);cursor:pointer;text-decoration:underline;"
                            >MiniMax 语音定价文档</span>（点击复制链接）
                        </li>
                    </ul>
                </div>
            </div>
        </div>

        <!-- 选项卡 -->
        <div class="tabs" style="border-bottom:2px solid var(--border);margin:12px 0;">
            <button class="tab" :class="{ active: currentTab === 'clone' }" @click="currentTab = 'clone'">
                📁 上传复刻
            </button>
            <button class="tab" :class="{ active: currentTab === 'design' }" @click="currentTab = 'design'">
                🎨 声音设计
            </button>
            <button class="tab" :class="{ active: currentTab === 'list' }" @click="currentTab = 'list'">
                🗂️ 音色列表
            </button>
        </div>

        <!-- ========== 复刻选项卡 ========== -->
        <div v-if="currentTab === 'clone'">
            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>📁 复刻音频管理</legend>
                <div class="form-group">
                    <label>上传复刻音频</label>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                        <input
                            type="file" ref="cloneFileInput" accept=".mp3,.m4a,.wav" style="flex:1;min-width:150px;"
                        />
                        <input
                            v-model="cloneCustomFileName" placeholder="自定义文件名（可选）"
                            style="flex:1;min-width:120px;"
                        />
                        <button
                            class="btn" @click="handleCloneUpload" :disabled="!isCloneUploadEnabled || cloneUploading"
                        >{{ cloneUploading ? '上传中...' : '上传' }}</button>
                    </div>
                    <div class="hint">格式 mp3/m4a/wav，时长 10s ~ 5min，大小 ≤ 20MB</div>
                </div>
                <div v-if="cloneLoading">加载中...</div>
                <table v-else>
                    <thead><tr><th>File ID</th><th>文件名</th><th>大小</th><th>创建时间</th><th>操作</th></tr></thead>
                    <tbody>
                        <tr v-for="f in cloneFiles" :key="f.file_id">
                            <td>{{ f.file_id }}</td>
                            <td>{{ f.filename }}</td>
                            <td>{{ (f.bytes / 1024).toFixed(1) }} KB</td>
                            <td>{{ new Date(f.created_at * 1000).toLocaleString() }}</td>
                            <td>
                                <button class="btn btn-sm" @click="playFile(f.file_id)"
                                    :class="{'btn-danger': currentPlayingId === 'file_' + f.file_id}">
                                    {{ currentPlayingId === 'file_' + f.file_id ? '⏹ 停止' : '▶ 播放' }}
                                </button>
                                <button class="btn btn-sm"
                                    @click="selectedCloneFileId = f.file_id"
                                    :style="{
                                        background: selectedCloneFileId === f.file_id ? 'var(--success)' : 'var(--gray)'
                                    }"
                                >
                                    {{ selectedCloneFileId === f.file_id ? '✓ 已选' : '选择' }}
                                </button>
                                <button class="btn btn-danger btn-sm" @click="deleteCloneFile(f.file_id)">删除</button>
                            </td>
                        </tr>
                        <tr v-if="!cloneFiles.length">
                            <td colspan="5" style="text-align:center;color:var(--gray);">暂无复刻音频</td>
                        </tr>
                    </tbody>
                </table>
            </fieldset>

            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>🎤 示例音频管理</legend>
                <div class="form-group">
                    <label>上传示例音频</label>

                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
                        <input
                            type="file" ref="promptFileInput" accept=".mp3,.m4a,.wav" style="flex:1;min-width:150px;"
                        />
                        <input 
                            v-model="promptCustomFileName"
                            placeholder="自定义文件名（可选）"
                            style="flex:1;min-width:120px;"
                        />
                    </div>

                    <div style="display:flex;gap:8px;align-items:flex-start;">
                        <textarea
                            v-model="promptTextInput"
                            placeholder="输入音频对应的文字内容（必填）"
                            rows="2" style="flex:1;min-width:150px;"
                        ></textarea>
                        <button
                            class="btn" @click="handlePromptUpload"
                            :disabled="!isPromptUploadEnabled || promptUploading"
                        >{{ promptUploading ? '上传中...' : '上传' }}</button>
                    </div>
                    <div class="hint">可选，增强相似度。示例音频时长 < 8s，格式同主音频，上传时需填写对应的源文本</div>
                </div>
                <div v-if="promptLoading">加载中...</div>
                <table v-else>
                    <thead><tr><th>File ID</th><th>文件名</th><th>源文本</th><th>操作</th></tr></thead>
                    <tbody>
                        <tr v-for="f in promptFiles" :key="f.file_id">
                            <td>{{ f.file_id }}</td>
                            <td>{{ f.filename }}</td>
                            <td>
                                <div v-if="editingPrompt === f.file_id">
                                    <textarea v-model="promptTexts[f.file_id]" rows="2" style="width:100%;"></textarea>
                                    <button class="btn btn-sm" @click="savePromptText(f.file_id)">保存</button>
                                    <button class="btn btn-sm btn-secondary" @click="editingPrompt = null">取消</button>
                                </div>
                                <div v-else>
                                    <span v-if="isPromptBindable(f.file_id)">{{ promptTexts[f.file_id] }}</span>
                                    <span v-else style="color:var(--danger);">未绑定</span>
                                    <button class="btn btn-sm" @click="editingPrompt = f.file_id">✏️ 编辑</button>
                                </div>
                            </td>
                            <td>
                                <button class="btn btn-sm" @click="playFile(f.file_id)"
                                    :class="{'btn-danger': currentPlayingId === 'file_' + f.file_id}">
                                    {{ currentPlayingId === 'file_' + f.file_id ? '⏹ 停止' : '▶ 播放' }}
                                </button>
                                <button class="btn btn-sm"
                                    :disabled="!isPromptBindable(f.file_id)"
                                    @click="selectedPromptFileId = f.file_id"
                                    :style="{
                                        background: selectedPromptFileId === f.file_id ? 'var(--success)' : 'var(--gray)'
                                    }"
                                >
                                    {{ selectedPromptFileId === f.file_id ? '✓ 已选' : '选择' }}
                                </button>
                                <button class="btn btn-danger btn-sm" @click="deletePromptFile(f.file_id)">删除</button>
                            </td>
                        </tr>
                        <tr v-if="!promptFiles.length">
                            <td colspan="4" style="text-align:center;color:var(--gray);">暂无示例音频</td>
                        </tr>
                    </tbody>
                </table>
            </fieldset>

            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>🔊 复刻参数</legend>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="form-group">
                        <label>主音频（必选）</label>
                        <select v-model="selectedCloneFileId">
                            <option value="">-- 请选择 --</option>
                            <option v-for="f in cloneFiles" :key="f.file_id" :value="f.file_id">
                                {{ f.file_id }} - {{ f.filename }}
                            </option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>示例音频（可选）</label>
                        <select v-model="selectedPromptFileId">
                            <option value="">-- 不使用 --</option>
                            <option v-for="f in bindablePrompts" :key="f.file_id" :value="f.file_id">
                                {{ f.file_id }} - {{ promptTexts[f.file_id] }}
                            </option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Voice ID</label>
                        <input v-model="cloneParams.voice_id" placeholder="建议自定义，留空自动生成"
                            :class="{'input-error': voiceIdError}" />
                        <div v-if="voiceIdError" class="error-hint">⚠️ {{ voiceIdError }}</div>
                        <div class="hint">
                            长度 8-256，首字母必须为英文字母，允许数字、字母、- 和 _，末位字符不可为 - 或 _，不可与已有 ID 重复
                        </div>
                    </div>
                    <div class="form-group">
                        <label>试听文本</label>
                        <input v-model="cloneParams.text" placeholder="可选。≤ 1000 字"
                            :class="{'input-error': textError}" />
                        <div v-if="textError" class="error-hint">⚠️ {{ textError }}</div>
                        <div class="hint">
                            提供后模型将使用复刻后的音色朗读本段文本内容。<!--
                            -->试听将根据字符数正常收取语音合成费用，定价与 T2A 各接口一致
                        </div>
                    </div>
                    <div
                        v-if="cloneParams.text && cloneParams.text.trim()"
                        style="grid-column: 1 / -1; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;"
                    >
                        <div class="form-group">
                            <label>试听模型版本</label>
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
                            <div class="hint">增强对指定的小语种和方言的识别能力。一般设置为 auto 让模型自主判断</div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>ASR 验证文本</label>
                        <input
                            v-model="cloneParams.text_validation"
                            placeholder="预期音频内容，≤ 200 字"
                            :class="{'input-error': textValidationError}"
                        />
                        <div v-if="textValidationError" class="error-hint">⚠️ {{ textValidationError }}</div>
                        <div class="hint">
                            可选。音频复刻样本（file_id 或 clone_prompt.prompt_audio 中的音频）的预期文本内容。<!--
                            -->提供后，服务会对该音频做 ASR 识别，并将识别文本与该文本做相似度比对；<!--
                            -->若相似度低于 accuracy，请求会被拒绝
                        </div>
                    </div>
                    <div class="form-group">
                        <label>ASR 相似度阈值</label>
                        <input type="number" v-model.number="cloneParams.accuracy" min="0" max="1" step="0.1" />
                        <div class="hint">可选。配合 ASR 验证文本使用的 ASR 相似度阈值，取值范围 [0, 1]，默认 0.7</div>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="cloneParams.need_noise_reduction" />
                        <label>降噪</label>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="cloneParams.need_volume_normalization" />
                        <label>音量归一化</label>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="cloneParams.aigc_watermark" />
                        <label>AIGC 水印</label>
                        <div class="hint">是否在合成试听音频的末尾添加音频节奏标识</div>
                    </div>
                </div>
                <button class="btn" @click="performClone" :disabled="!isCloneEnabled || cloning">
                    {{ cloning ? '复刻中...' : '复刻音色' }}
                </button>
            </fieldset>

            <!-- 复刻结果模态框 -->
            <div v-if="cloneResultModalVisible" class="modal-overlay" @mousedown.self="closeCloneResult">
                <div class="modal-content" style="max-width:500px;">
                    <h3>✅ 复刻成功</h3>
                    <p><strong>Voice ID:</strong> {{ cloneResult.voice_id }}</p>
                    <p style="color:var(--gray);font-size:0.85rem;">
                        音色当前处于未激活状态，需要在语音合成接口中正式调用一次方可激活。
                    </p>
                    <button class="btn" @click="playDemoAudio"
                        :class="{'btn-danger': currentPlayingId === 'demo_audio'}">
                        {{ currentPlayingId === 'demo_audio' ? '⏹ 停止' : '▶ 播放试听音频' }}
                    </button>
                    <div style="margin-top:16px;display:flex;gap:12px;justify-content:flex-end;">
                        <button class="btn btn-danger" @click="showDeleteUnactivatedConfirm(cloneResult.voice_id)">
                            删除
                        </button>
                        <button class="btn btn-success" @click="keepUnactivatedVoice(cloneResult, 'voice_cloning')">
                            保留
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- ========== 声音设计选项卡 ========== -->
        <div v-if="currentTab === 'design'">
            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>🎨 声音设计</legend>
                <div class="form-group">
                    <label>音色描述 <span style="color:var(--danger);">*</span></label>
                    <textarea
                        v-model="designForm.prompt"
                        rows="3"
                        placeholder="例如：温柔的女声，略带磁性，适合朗读抒情散文..."
                        style="width:100%;
                        :class="{'input-error': designPromptError}"
                    ></textarea>
                    <div v-if="designPromptError" class="error-hint">⚠️ {{ designPromptError }}</div>
                </div>
                <div class="form-group">
                    <label>预览文本 <span style="color:var(--danger);">*</span></label>
                    <textarea
                        v-model="designForm.preview_text"
                        rows="2"
                        placeholder="输入用于试听的文本。≤ 500 字符" style="width:100%;"
                        :class="{'input-error': designTextError}"
                    ></textarea>
                    <div v-if="designTextError" class="error-hint">⚠️ {{ designTextError }}</div>
                    <div class="hint">最大 500 字符 (汉字按 2 字符计算)；试听音频的合成将收取 2 元/万字符的费用</div>
                </div>
                <div class="form-group">
                    <label>Voice ID</label>
                    <input v-model="designForm.voice_id" placeholder="建议自定义，留空自动生成"
                        :class="{'input-error': designVoiceIdError}" />
                    <div v-if="designVoiceIdError" class="error-hint">⚠️ {{ designVoiceIdError }}</div>
                    <div class="hint">
                        长度 8-256，首字母必须为英文字母，允许数字、字母、- 和 _，末位字符不可为 - 或 _，不可与已有 ID 重复
                    </div>
                </div>
                <div class="form-group checkbox-group">
                    <input type="checkbox" v-model="designForm.aigc_watermark" />
                    <label>AIGC 水印</label>
                    <div class="hint">是否在合成试听音频的末尾添加音频节奏标识</div>
                </div>
                <button class="btn" @click="performDesign" :disabled="!isDesignEnabled || designing">
                    {{ designing ? '设计中...' : '设计音色' }}
                </button>
            </fieldset>

            <!-- 设计结果模态框 -->
            <div v-if="designResultModalVisible" class="modal-overlay" @mousedown.self="closeDesignResult">
                <div class="modal-content" style="max-width:500px;">
                    <h3>✅ 设计成功</h3>
                    <p><strong>Voice ID:</strong> {{ designResult.voice_id }}</p>
                    <p style="color:var(--gray);font-size:0.85rem;">
                        音色当前处于未激活状态，需要在语音合成接口中正式调用一次方可激活。
                    </p>
                    <div v-if="designResult.trial_audio">
                        <button class="btn" @click="playTrialAudio"
                            :class="{'btn-danger': currentPlayingId === 'trial_audio'}">
                            {{ currentPlayingId === 'trial_audio' ? '⏹ 停止' : '▶ 播放试听音频' }}
                        </button>
                    </div>
                    <div style="margin-top:16px;display:flex;gap:12px;justify-content:flex-end;">
                        <button class="btn btn-danger" @click="showDeleteUnactivatedConfirm(designResult.voice_id)">
                            删除
                        </button>
                        <button class="btn btn-success" @click="keepUnactivatedVoice(designResult, 'voice_generation')">
                            保留
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- ========== 音色列表选项卡 ========== -->
        <div v-if="currentTab === 'list'">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <h3 style="margin:0;">音色列表</h3>
                <button class="btn btn-sm" @click="fetchVoiceList" :disabled="voiceLoading">刷新</button>
            </div>
            <div v-if="voiceLoading">加载中...</div>

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
                        -->激活后音色将出现在自定义音色列表中，并扣取相应费用。
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
                            <td>{{ v.type || 'unknown' }}</td>
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

            <!-- 自定义音色 -->
            <template v-if="customVoices.length">
                <h4 style="margin:16px 0 8px 0;">🧑‍🎨 自定义音色</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Voice ID</th>
                            <th>类型</th>
                            <th>描述</th>
                            <th>创建时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in customVoices" :key="v.voice_id">
                            <td>{{ v.voice_id }}</td>
                            <td>{{ v.type || 'unknown' }}</td>
                            <td>{{ v.description ? v.description.join(', ') : '-' }}</td>
                            <td>{{ v.created_time ? new Date(v.created_time * 1000).toLocaleString() : '-' }}</td>
                            <td>
                                <button class="btn btn-sm" @click="copyText(v.voice_id)">复制</button>
                                <button class="btn btn-sm" @click="openPreview(v.voice_id)">预览</button>
                                <button class="btn btn-danger btn-sm" @click="deleteVoice(v.voice_id, v.type)">
                                    删除
                                </button>
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
                            <th>描述</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in systemVoices" :key="v.voice_id">
                            <td>{{ v.voice_id }}</td>
                            <td>{{ v.voice_name || '-' }}</td>
                            <td>{{ v.description ? v.description.join(', ') : '-' }}</td>
                            <td>
                                <button class="btn btn-sm" @click="copyText(v.voice_id)">复制</button>
                                <button class="btn btn-sm" @click="openPreview(v.voice_id)">预览</button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </template>

            <!-- 空状态 -->
            <div v-if="!voiceList.length" style="text-align:center;color:var(--gray);padding:20px 0;">
                暂无音色
            </div>

            <!-- 预览模态框 -->
            <VoicePreviewModal
                v-model:visible="previewModalVisible"
                :bridge="bridge"
                :entry-id="selectedEntryId"
                :voice-id="previewVoiceId"
                id-prefix="preview"
                @previewed="onVoicePreviewed"
            />
        </div>

        <!-- 通用删除确认模态框 -->
        <DeleteConfirmModal
            v-model:visible="deleteModal.visible"
            :title="deleteModal.title"
            :message="deleteModal.message"
            @cancel="cancelDelete"
            @confirm="confirmDelete"
        />
    </div>
    `
};
