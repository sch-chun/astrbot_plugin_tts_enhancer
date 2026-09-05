const { ref, reactive, watch, computed, nextTick } = Vue;

export default {
    name: 'BailianSpeechSynthesizer',
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
                designHelpLink: 'https://help.aliyun.com/zh/model-studio/voice-design-user-guide'
            })
        }
    },
    setup(props) {

        // ----- Toast 提示 -----
        const toastMessage = ref('');
        const toastVisible = ref(false);
        const toastType = ref('success');
        let toastTimer = null;

        function showToast(msg, type = 'success') {
            toastMessage.value = msg;
            toastType.value = type;
            toastVisible.value = true;
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => {
                toastVisible.value = false;
                toastMessage.value = '';
            }, 3000);
        }
        function showSuccess(msg) { showToast(msg, 'success'); }
        function showError(msg) { showToast(msg, 'error'); }

        // ----- 公共状态 -----
        const selectedEntryId = ref(null);
        const voiceList = ref([]);
        const loading = ref(false);
        const creating = ref(false);
        const mode = ref('upload'); // 'upload' | 'url' | 'design'

        // ----- 上传模式表单 -----
        const uploadForm = reactive({
            file: null,
            external_base_url: '',
            internal_port: '',
            prefix: 'upload',
            language_hint: 'zh',
            enable_volume_normalization: false,
            enable_preprocess: false,
            max_prompt_audio_length: 10.0,
            model: 'flash',
        });
        const uploading = ref(false);
        let currentFileId = null;
        // 用于重置文件输入框的 ref
        const fileInputRef = ref(null);

        // ----- URL 模式表单 -----
        const urlForm = reactive({
            audio_url: '',
            prefix: 'urlvoice',
            language_hint: 'zh',
            enable_volume_normalization: false,
            enable_preprocess: false,
            max_prompt_audio_length: 10.0,
            model: 'flash',
        });

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

        // ----- 当前表单（根据模式）-----
        const currentForm = computed(() => {
            if (mode.value === 'upload') return uploadForm;
            if (mode.value === 'url') return urlForm;
            return designForm;
        });

        // ----- 字符数计算函数（汉字按2字符，其他1字符）-----
        function countChars(text) {
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

        // ----- 设计模式字符数校验 -----
        const voicePromptChars = computed(() => countChars(designForm.voice_prompt));
        const previewTextChars = computed(() => countChars(designForm.preview_text));
        const isVoicePromptValid = computed(() => voicePromptChars.value <= 500);
        const isPreviewTextValid = computed(() => previewTextChars.value <= 200 && previewTextChars.value >= 15);
        const isPrefixValidForDesign = computed(() => {
            return /^[a-zA-Z0-9]{1,10}$/.test(designForm.prefix);
        });
        const isDesignFormValid = computed(() => {
            return isPrefixValidForDesign.value && isVoicePromptValid.value && isPreviewTextValid.value;
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
                uploadForm.model = newEntry.model || 'flash';
                urlForm.model = newEntry.model || 'flash';
                designForm.model = newEntry.model || 'flash';
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
                    } catch (_) {}
                }
                showError('创建音色失败: ' + errMsg);
                return null;
            }
        }

        // ----- 上传模式：上传文件 + 启动服务器 + 创建音色 + 停止服务器 -----
        function handleFileChange(event) {
            const file = event.target.files[0];
            if (file) {
                uploadForm.file = file;
            }
        }

        async function uploadAndClone() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            if (!uploadForm.file) {
                showError('请选择音频文件');
                return;
            }
            const baseUrl = uploadForm.external_base_url.trim();
            if (!baseUrl) {
                showError('请填写外部访问地址（含协议和端口）');
                return;
            }
            try {
                new URL(baseUrl);
            } catch (_) {
                showError('外部访问地址格式不正确，请包含协议（如 https://）');
                return;
            }
            const intPort = parseInt(uploadForm.internal_port);
            if (isNaN(intPort) || intPort < 1024 || intPort > 65535) {
                showError('内部端口须为 1024-65535');
                return;
            }

            uploading.value = true;
            try {
                const uploadResult = await props.bridge.upload(
                    'upload',
                    uploadForm.file,
                    {
                        max_sec: 60,
                        auto_trim: true,
                    }
                );
                if (!uploadResult.file_id) {
                    const errMsg = uploadResult.message || uploadResult.error || '上传失败，未返回 file_id';
                    showError('上传失败: ' + errMsg);
                    uploading.value = false;
                    return;
                }
                const fileId = uploadResult.file_id;
                currentFileId = fileId;

                const startResp = await props.bridge.apiPost('start_file_server', {
                    file_id: fileId,
                    internal_port: intPort,
                });
                if (startResp.success !== true) {
                    const errMsg = startResp.message || startResp.error || '启动文件服务器失败';
                    showError('启动文件服务器失败: ' + errMsg);
                    uploading.value = false;
                    return;
                }

                const audioUrl = `${baseUrl.replace(/\/+$/, '')}/${fileId}`;
                const payload = {
                    entry_id: selectedEntryId.value,
                    mode: 'clone',
                    audio_url: audioUrl,
                    prefix: uploadForm.prefix,
                    language_hints: uploadForm.language_hint ? [uploadForm.language_hint] : [],
                    enable_volume_normalization: uploadForm.enable_volume_normalization,
                    enable_preprocess: uploadForm.enable_preprocess,
                    max_prompt_audio_length: uploadForm.enable_preprocess ? uploadForm.max_prompt_audio_length : undefined,
                    model: uploadForm.model,
                };
                const result = await callCreateVoice(payload);
                if (result) {
                    showSuccess('音色创建成功！Voice ID: ' + result.voice_id);
                    await fetchVoices();
                    uploadForm.file = null;
                    // 使用 ref 重置文件输入
                    if (fileInputRef.value) {
                        fileInputRef.value.value = '';
                    }
                }
            } catch (e) {
                console.error('上传复刻失败:', e);
                showError('请求失败: ' + e.message);
            } finally {
                uploading.value = false;
                if (currentFileId) {
                    try {
                        await props.bridge.apiPost('stop_file_server', { file_id: currentFileId });
                        currentFileId = null;
                    } catch (e) {
                        console.warn('停止文件服务器失败:', e);
                    }
                }
            }
        }

        // ----- URL 模式：直接使用公网音频 URL 创建音色 -----
        async function createFromUrl() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            if (!urlForm.audio_url) {
                showError('请填写公网音频 URL');
                return;
            }
            try {
                new URL(urlForm.audio_url);
            } catch (_) {
                showError('URL 格式不正确');
                return;
            }

            creating.value = true;
            try {
                const payload = {
                    entry_id: selectedEntryId.value,
                    mode: 'clone',
                    audio_url: urlForm.audio_url,
                    prefix: urlForm.prefix,
                    language_hints: urlForm.language_hint ? [urlForm.language_hint] : [],
                    enable_volume_normalization: urlForm.enable_volume_normalization,
                    enable_preprocess: urlForm.enable_preprocess,
                    max_prompt_audio_length: urlForm.enable_preprocess ? urlForm.max_prompt_audio_length : undefined,
                    model: urlForm.model,
                };
                const result = await callCreateVoice(payload);
                if (result) {
                    showSuccess('音色创建成功！Voice ID: ' + result.voice_id);
                    await fetchVoices();
                }
            } catch (e) {
                console.error('URL 创建失败:', e);
                showError('请求失败: ' + e.message);
            } finally {
                creating.value = false;
            }
        }

        // ----- 设计模式：创建音色并打开预览模态框 -----
        const previewModalVisible = ref(false);
        const previewVoiceId = ref('');
        const previewAudioBase64 = ref('');
        const previewAudioFormat = ref('wav');
        const previewText = ref('欢迎使用声音设计功能，让我们听听这个音色的效果。');
        const previewDeleteConfirm = ref(false);

        // 存储预览音频的 blob URL（局部变量，不用 window）
        const previewAudioUrl = ref(null);

        async function createFromDesign() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            if (!designForm.voice_prompt.trim()) {
                showError('请填写声音描述');
                return;
            }
            if (!isVoicePromptValid.value) {
                showError('声音描述超过 500 字符限制（当前 ' + voicePromptChars.value + ' 字符）');
                return;
            }
            if (!designForm.preview_text.trim()) {
                showError('请填写预览文本');
                return;
            }
            if (!isPreviewTextValid.value) {
                showError('预览文本超过 15 ~ 200 字符限制（当前 ' + previewTextChars.value + ' 字符）');
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
        function closePreviewModal() {
            previewModalVisible.value = false;
            previewDeleteConfirm.value = false;
            // 释放 blob URL
            if (previewAudioUrl.value) {
                URL.revokeObjectURL(previewAudioUrl.value);
                previewAudioUrl.value = null;
            }
        }

        function playPreviewAudio() {
            if (!previewAudioBase64.value) {
                showError('没有可播放的音频数据');
                return;
            }
            try {
                const audioBytes = Uint8Array.from(atob(previewAudioBase64.value), c => c.charCodeAt(0));
                const mimeType = `audio/${previewAudioFormat.value}`;
                const blob = new Blob([audioBytes], { type: mimeType });
                const audioUrl = URL.createObjectURL(blob);
                // 释放旧的 URL
                if (previewAudioUrl.value) {
                    URL.revokeObjectURL(previewAudioUrl.value);
                }
                previewAudioUrl.value = audioUrl;
                const audio = new Audio(audioUrl);
                audio.play();
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
        const listPreviewText = ref('欢迎使用语音合成预览功能。');
        const listPreviewLoading = ref(false);

        function openListPreviewModal(voiceId) {
            listPreviewVoiceId.value = voiceId;
            if (!listPreviewText.value.trim()) {
                listPreviewText.value = '欢迎使用语音合成预览功能。';
            }
            listPreviewModalVisible.value = true;
        }

        async function doListPreview() {
            if (!listPreviewText.value.trim()) {
                showError('请输入预览文本');
                return;
            }
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            listPreviewLoading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/preview', {
                    entry_id: selectedEntryId.value,
                    voice_id: listPreviewVoiceId.value,
                    text: listPreviewText.value.trim()
                });
                if (!result.audio_base64) {
                    showError('预览失败: 未返回音频数据');
                    return;
                }
                const audioBytes = Uint8Array.from(atob(result.audio_base64), c => c.charCodeAt(0));
                const mimeType = `audio/${result.format || 'mpeg'}`;
                const blob = new Blob([audioBytes], { type: mimeType });
                const audioUrl = URL.createObjectURL(blob);
                const audio = new Audio(audioUrl);
                audio.play();
                audio.onended = () => URL.revokeObjectURL(audioUrl);
            } catch (e) {
                console.error('预览失败:', e);
                showError('预览失败: ' + e.message);
            } finally {
                listPreviewLoading.value = false;
            }
        }

        function closeListPreviewModal() {
            listPreviewModalVisible.value = false;
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
        function copyToClipboard(text) {
            try {
                const input = document.createElement('input');
                input.value = text;

                // 确保元素在视口内但不可见，避免页面滚动
                input.style.position = 'fixed';
                input.style.top = '-9999px';
                input.style.left = '-9999px';
                document.body.appendChild(input);
                input.select();

                // 针对移动端 iOS 的兼容
                input.setSelectionRange(0, 99999);
                const success = document.execCommand('copy');
                document.body.removeChild(input);
                
                if (success) {
                    showSuccess('已复制: ' + text);
                } else {
                    showError('复制失败，请手动复制');
                }
            } catch (e) {
                console.error('复制失败:', e);
                showError('复制失败，请手动复制');
            }
        }

        function copyHelpLink() {
            const link = props.providerConfig.designHelpLink || 'https://help.aliyun.com/zh/model-studio/voice-design-user-guide';
            copyToClipboard(link);
            showSuccess('链接已复制，请手动粘贴到浏览器地址栏访问');
        }

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

        const isPortValid = computed(() => {
            if (mode.value !== 'upload') return true;
            const port = parseInt(uploadForm.internal_port);
            return !isNaN(port) && port >= 1024 && port <= 65535;
        });

        const isFormValid = computed(() => {
            const prefixOK = isPrefixValid.value;
            const lengthOK = isMaxLengthValid.value;
            const portOK = isPortValid.value;
            return prefixOK && lengthOK && portOK;
        });

        return {

            // 数据
            toastMessage,
            toastVisible,
            toastType,
            selectedEntryId,
            currentEntry,
            voiceList,
            loading,
            creating,
            designing,
            mode,
            currentForm,
            uploadForm,
            uploading,
            urlForm,
            designForm,
            deleteModalVisible,
            deleteTargetId,
            languages,

            // 设计模式校验
            voicePromptChars,
            previewTextChars,
            isVoicePromptValid,
            isPreviewTextValid,
            isPrefixValidForDesign,
            isDesignFormValid,

            // 预览
            previewModalVisible,
            previewVoiceId,
            previewText,
            playPreviewAudio,
            keepVoice,
            closePreviewModal,
            previewDeleteConfirm,
            confirmDeletePreview,

            // 列表预览
            listPreviewModalVisible,
            listPreviewVoiceId,
            listPreviewText,
            listPreviewLoading,
            openListPreviewModal,
            doListPreview,
            closeListPreviewModal,

            // 删除
            deleteVoice,
            confirmDelete,
            cancelDelete,
            
            // 公共方法
            fetchVoices,
            copyToClipboard,
            copyHelpLink,
            getStatusDescription,

            // 校验
            isPrefixValid,
            isMaxLengthValid,
            isFormValid,
            isPortValid,

            // 上传文件 ref
            fileInputRef,
            handleFileChange,
            uploadAndClone,
            createFromUrl,
            createFromDesign,
            
            // 供应商配置（用于模板）
            providerConfig: props.providerConfig,
        };
    },
    template: /*html*/ `
        <div class="bailian-tts">
            <div v-if="toastVisible" class="toast" :class="{'toast-error': toastType === 'error'}">
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
            <fieldset style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;">
                <legend>创建新音色</legend>

                <!-- 公网 IPv4 确认提示 -->
                <div v-if="mode !== 'design'" style="background:rgba(241,151,27,0.15);border-left:4px solid #f0971b;padding:8px 12px;margin-bottom:16px;border-radius:4px;color:var(--text);">
                    <strong>⚠️ 重要：</strong> 请确认服务器拥有公网 IPv4 地址，且防火墙已开放指定端口 (上传模式) 或音频 URL 可被公网 IPv4 访问 (URL 模式)。
                </div>

                <!-- 系统音色提示（仅当供应商支持系统音色且非设计模式） -->
                <div v-if="providerConfig.supportsSystemVoices && mode !== 'design'" 
                    style="background:rgba(37,99,235,0.1);border-left:4px solid var(--primary);padding:8px 12px;margin-bottom:16px;border-radius:4px;color:var(--text);">
                    💡 系统音色列表请参考 
                    <template v-if="providerConfig.systemVoiceLinks && providerConfig.systemVoiceLinks.length">
                        <span v-for="(link, idx) in providerConfig.systemVoiceLinks" :key="idx">
                            <span class="link-copy" @click="copyToClipboard(link.url)" 
                                style="color:var(--primary);cursor:pointer;text-decoration:underline;margin:0 4px;">
                                {{ link.label }}
                            </span>
                            <span v-if="idx < providerConfig.systemVoiceLinks.length - 1">、</span>
                        </span>
                    </template>
                    <template v-else>
                        <span class="link-copy" @click="copyToClipboard(providerConfig.systemVoiceHelpLink)" 
                            style="color:var(--primary);cursor:pointer;text-decoration:underline;">
                            帮助文档
                        </span>
                    </template>
                    （点击复制链接）
                </div>

                <!-- 选项卡切换 -->
                <div style="display:flex;gap:8px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;">
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'upload' }"
                        @click="mode = 'upload'"
                        style="padding:8px 16px;border:none;background:transparent;cursor:pointer;border-bottom:2px solid transparent;"
                    >
                        📁 上传音频文件
                    </button>
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'url' }"
                        @click="mode = 'url'"
                        style="padding:8px 16px;border:none;background:transparent;cursor:pointer;border-bottom:2px solid transparent;"
                    >
                        🔗 使用音频 URL
                    </button>
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'design' }"
                        @click="mode = 'design'"
                        style="padding:8px 16px;border:none;background:transparent;cursor:pointer;border-bottom:2px solid transparent;"
                    >
                        🎨 声音设计
                    </button>
                </div>

                <!-- 上传模式 -->
                <div v-if="mode === 'upload'">
                    <div class="form-group">
                        <label>外部访问地址（基础 URL）</label>
                        <input v-model="uploadForm.external_base_url" placeholder="例如：https://abc.sample.com:8080 或 http://123.123.123.123:8080" />
                        <div class="hint">请包含协议（http:// 或 https://）、域名/IP 和端口，末尾不要加斜杠</div>
                    </div>

                    <div class="form-group">
                        <label>内部监听端口</label>
                        <input
                            v-model="uploadForm.internal_port"
                            placeholder="例如：8080（1024-65535）"
                            :class="{ 'input-error': !isPortValid }"
                        />
                        <div v-if="!isPortValid" class="error-hint">
                            ⚠️ 必须是 1024-65535 之间的整数
                        </div>
                    </div>

                    <div class="form-group">
                        <label>选择音频文件（wav (16bit), mp3, m4a）</label>
                        <input type="file" ref="fileInputRef" accept=".wav,.mp3,.m4a" @change="handleFileChange" />
                        <div class="hint">推荐 10~20s，最长 60s。文件 ≤ 10MB，采样率 ≥ 16kHz。大于 60s 的文件将被自动裁剪。</div>
                    </div>
                </div>

                <!-- URL 模式 -->
                <div v-if="mode === 'url'">
                    <div class="form-group">
                        <label>公网音频 URL（wav (16bit), mp3, m4a）</label>
                        <input v-model="urlForm.audio_url" placeholder="例如：https://example.com/voice.wav" />
                        <div class="hint">推荐 10~20s，最长 60s。文件 ≤ 10MB，采样率 ≥ 16kHz。</div>
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
                            :class="{ 'input-error': !isVoicePromptValid && designForm.voice_prompt }"
                            style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);resize:vertical;"
                        ></textarea>
                        <div v-if="!isVoicePromptValid && designForm.voice_prompt" class="error-hint">
                            ⚠️ 声音描述超过 500 字符限制（当前 {{ voicePromptChars }} 字符，汉字按 2 字符计算）
                        </div>
                        <div class="hint">
                            用自然语言描述期望的声音特质，支持中文和英文，不超过 500 字符（汉字按 2 字符计算）。详见 
                            <span style="color:var(--primary);cursor:pointer;text-decoration:underline;" @click="copyHelpLink">声音设计编写指南</span>
                            （点击复制链接，请手动粘贴到浏览器地址栏打开）
                        </div>
                    </div>

                    <div class="form-group">
                        <label>预览文本</label>
                        <textarea 
                            v-model="designForm.preview_text" 
                            rows="2" 
                            placeholder="输入用于试听的文本..." 
                            :class="{ 'input-error': !isPreviewTextValid && designForm.preview_text }"
                            style="width:100%;padding:8px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);resize:vertical;"
                        ></textarea>
                        <div v-if="!isPreviewTextValid && designForm.preview_text" class="error-hint">
                            ⚠️ 预览文本超过 200 字符限制（当前 {{ previewTextChars }} 字符，汉字按 2 字符计算）
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
                        <input type="checkbox" v-model="currentForm.enable_volume_normalization" :id="mode + '_vol_norm'" />
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
                        <option value="flash">Flash</option>
                        <option value="plus">Plus</option>
                    </select>
                </div>

                <!-- 提交按钮 -->
                <button
                    v-if="mode === 'upload'"
                    class="btn"
                    @click="uploadAndClone"
                    :disabled="!isFormValid || uploading"
                >
                    {{ uploading ? '上传并处理中...' : '📁 上传并复刻' }}
                </button>
                <button
                    v-else-if="mode === 'url'"
                    class="btn"
                    @click="createFromUrl"
                    :disabled="!isFormValid || creating"
                >
                    {{ creating ? '创建中...' : '🔗 创建音色' }}
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
                                <span v-if="v.voice_id && v.voice_id.includes('-vd-')" style="background:#dbeafe;color:#1e40af;padding:0 6px;border-radius:4px;font-size:0.7rem;margin-left:4px;">设计</span>
                            </td>
                            <td>{{ v.created_at }}</td>
                            <td>
                                <span :class="'status-' + v.status.toLowerCase()" :title="getStatusDescription(v.status)">
                                    {{ v.status }}
                                </span>
                            </td>
                            <td>
                                <button class="btn btn-sm" @click="copyToClipboard(v.voice_id)" title="复制 ID" style="margin-right: 4px;">复制</button>
                                <button class="btn btn-sm" @click="openListPreviewModal(v.voice_id)" :disabled="v.status !== 'OK'" title="预览音色" style="margin-right: 4px;">预览</button>
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
                        <button class="btn" @click="playPreviewAudio">▶ 试听</button>
                    </div>
                    <div style="border-top:1px solid var(--border);padding-top:16px;">
                        <div v-if="!previewDeleteConfirm" style="display:flex;gap:12px;justify-content:flex-end;">
                            <button class="btn btn-success" @click="keepVoice">保留</button>
                            <button class="btn btn-danger" @click="previewDeleteConfirm = true">删除</button>
                            <button class="btn btn-sm btn-secondary" @click="closePreviewModal">关闭</button>
                        </div>
                        <div v-else style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
                            <div style="color:var(--danger);font-weight:bold;">⚠️ 确定要删除此音色吗？此操作不可恢复。</div>
                            <div style="display:flex;gap:12px;">
                                <button class="btn btn-sm btn-secondary" @click="previewDeleteConfirm = false">取消</button>
                                <button class="btn btn-danger" @click="confirmDeletePreview">确认删除</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 删除确认模态框（用于音色列表） -->
            <div v-if="deleteModalVisible" class="modal-overlay" @mousedown.self="cancelDelete">
                <div class="modal-content" style="max-width:400px;width:90%;">
                    <h3>⚠️ 确认删除</h3>
                    <p>确定要删除音色 <strong>{{ deleteTargetId }}</strong> 吗？此操作不可恢复。</p>
                    <div style="display:flex;gap:12px;justify-content:flex-end;border-top:1px solid var(--border);padding-top:16px;">
                        <button class="btn btn-sm" @click="cancelDelete" style="background:var(--gray);">取消</button>
                        <button class="btn btn-danger" @click="confirmDelete">确认删除</button>
                    </div>
                </div>
            </div>

            <!-- 列表预览模态框 -->
            <div v-if="listPreviewModalVisible" class="modal-overlay" @mousedown.self="closeListPreviewModal">
                <div class="modal-content">
                    <h3>预览音色</h3>
                    <p><strong>Voice ID:</strong> {{ listPreviewVoiceId }}</p>
                    <div class="form-group">
                        <label>预览文本</label>
                        <textarea v-model="listPreviewText" rows="3" placeholder="输入要试听的文本"></textarea>
                    </div>
                    <div style="display:flex; gap:12px; justify-content:flex-end;">
                        <button class="btn" @click="doListPreview" :disabled="listPreviewLoading">
                            {{ listPreviewLoading ? '合成中...' : '试听' }}
                        </button>
                        <button class="btn btn-sm btn-secondary" @click="closeListPreviewModal">关闭</button>
                    </div>
                </div>
            </div>
        </div>
    `
};
