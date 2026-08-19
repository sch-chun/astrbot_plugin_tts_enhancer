const { ref, reactive, watch, computed } = Vue;

export default {
    name: 'BailianQwenAudio3_0',
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true },
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
        const mode = ref('upload'); // 'upload' | 'url'

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

        // ----- URL 模式表单 -----
        const urlForm = reactive({
            audio_url: '',
            prefix: 'url_voice',
            language_hint: 'zh',
            enable_volume_normalization: false,
            enable_preprocess: false,
            max_prompt_audio_length: 10.0,
            model: 'flash',
        });

        // ----- 语言列表 -----
        const languages = [
            { code: 'zh', label: '中文' },
            { code: 'en', label: '英语' },
            { code: 'fr', label: '法语' },
            { code: 'de', label: '德语' },
            { code: 'ja', label: '日语' },
            { code: 'ko', label: '韩语' },
            { code: 'ru', label: '俄语' },
            { code: 'pt', label: '葡萄牙语' },
            { code: 'th', label: '泰语' },
            { code: 'id', label: '印尼语' },
            { code: 'vi', label: '越南语' },
            { code: 'es', label: '西班牙语' },
            { code: 'it', label: '意大利语' },
            { code: 'ms', label: '马来西亚语' },
            { code: 'fil', label: '菲律宾语' },
            { code: 'ar', label: '阿拉伯语' },
        ];

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
            // 清理 undefined 值
            Object.keys(payload).forEach(key => {
                if (payload[key] === undefined) delete payload[key];
            });
            try {
                const result = await props.bridge.apiPost('voice/create', payload);
                console.log('Create voice response:', result);
                // 成功条件：存在 voice_id 或 voice
                if (result.voice_id || result.voice) {
                    showSuccess('音色创建成功！Voice ID: ' + (result.voice_id || result.voice));
                    await fetchVoices();
                    return true;
                }
                // 错误响应（如 {status:'error', message:'...'}）
                const errMsg = result.message || result.error || '创建失败，未返回音色 ID';
                showError('创建音色失败: ' + errMsg);
                return false;
            } catch (e) {
                console.error('创建音色异常:', e);
                // 尝试提取详细错误信息
                let errMsg = e.message || '未知错误';
                // 如果异常对象包含 response，尝试解析响应体
                if (e.response) {
                    try {
                        const data = await e.response.json();
                        errMsg = data.message || data.error || errMsg;
                    } catch (_) {
                        // 无法解析 JSON，使用默认信息
                    }
                }
                showError('创建音色失败: ' + errMsg);
                return false;
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
            // 校验外部基础 URL
            const baseUrl = uploadForm.external_base_url.trim();
            if (!baseUrl) {
                showError('请填写外部访问地址（含协议和端口）');
                return;
            }
            // 简单校验 URL 格式
            try {
                new URL(baseUrl);
            } catch (_) {
                showError('外部访问地址格式不正确，请包含协议（如 https://）');
                return;
            }
            // 校验内部端口
            const intPort = parseInt(uploadForm.internal_port);
            if (isNaN(intPort) || intPort < 1024 || intPort > 65535) {
                showError('内部端口须为 1024-65535');
                return;
            }

            uploading.value = true;
            try {
                // 1. 上传文件
                const uploadResult = await props.bridge.upload('upload', uploadForm.file);
                console.log('Upload response:', uploadResult);
                if (!uploadResult.file_id) {
                    const errMsg = uploadResult.message || uploadResult.error || '上传失败，未返回 file_id';
                    showError('上传失败: ' + errMsg);
                    uploading.value = false;
                    return;
                }
                const fileId = uploadResult.file_id;
                currentFileId = fileId;

                // 2. 启动文件服务器（内部端口）
                const startResp = await props.bridge.apiPost('start_file_server', {
                    file_id: fileId,
                    internal_port: intPort,
                });
                console.log('Start server response:', startResp);
                if (startResp.success !== true) {
                    const errMsg = startResp.message || startResp.error || '启动文件服务器失败';
                    showError('启动文件服务器失败: ' + errMsg);
                    uploading.value = false;
                    return;
                }

                // 3. 构造完整的音频 URL（基础 URL + 文件名）
                const audioUrl = `${baseUrl.replace(/\/+$/, '')}/${fileId}`;

                // 4. 创建音色
                const payload = {
                    entry_id: selectedEntryId.value,
                    audio_url: audioUrl,
                    prefix: uploadForm.prefix,
                    language_hints: uploadForm.language_hint ? [uploadForm.language_hint] : [],
                    enable_volume_normalization: uploadForm.enable_volume_normalization,
                    enable_preprocess: uploadForm.enable_preprocess,
                    max_prompt_audio_length: uploadForm.enable_preprocess ? uploadForm.max_prompt_audio_length : undefined,
                    model: uploadForm.model,
                };
                const success = await callCreateVoice(payload);
                if (success) {
                    uploadForm.file = null;
                    document.getElementById('fileInput').value = '';
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
            // 简单 URL 校验
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
                    audio_url: urlForm.audio_url,
                    prefix: urlForm.prefix,
                    language_hints: urlForm.language_hint ? [urlForm.language_hint] : [],
                    enable_volume_normalization: urlForm.enable_volume_normalization,
                    enable_preprocess: urlForm.enable_preprocess,
                    max_prompt_audio_length: urlForm.enable_preprocess ? urlForm.max_prompt_audio_length : undefined,
                    model: urlForm.model,
                };
                await callCreateVoice(payload);
            } catch (e) {
                console.error('URL 创建失败:', e);
                showError('请求失败: ' + e.message);
            } finally {
                creating.value = false;
            }
        }

        // ----- 删除音色 -----
        async function deleteVoice(voiceId) {
            if (!confirm(`确定要删除音色 ${voiceId} 吗？`)) return;
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            try {
                await props.bridge.apiPost('voice/delete', {
                    entry_id: selectedEntryId.value,
                    voice_id: voiceId,
                });
                showSuccess('删除成功');
                await fetchVoices();
            } catch (e) {
                console.error('删除音色失败:', e);
                showError('删除失败: ' + e.message);
            }
        }

        // ----- 复制到剪贴板 -----
        function copyToClipboard(text) {
            const fallbackCopy = () => {
                const input = document.createElement('input');
                input.value = text;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                showSuccess('已复制: ' + text);
            };
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text)
                        .then(() => showSuccess('已复制: ' + text))
                        .catch(fallbackCopy);
                } else {
                    fallbackCopy();
                }
            } catch (e) {
                console.error('复制失败:', e);
                try { fallbackCopy(); } catch (_) {
                    showError('复制失败，请手动复制');
                }
            }
        }

        function getStatusDescription(status) {
            const map = {
                'DEPLOYING': '审核中/处理中',
                'OK': '审核通过，可正常使用',
                'UNDEPLOYED': '审核未通过，不可使用'
            };
            return map[status] || status;
        }

        async function previewVoice(voiceId) {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            try {
                const result = await props.bridge.apiPost('voice/preview', {
                    entry_id: selectedEntryId.value,
                    voice_id: voiceId,
                    text: '欢迎使用语音合成预览功能。'
                });
                // 检查响应
                if (!result.audio_base64) {
                    showError('预览失败: 未返回音频数据');
                    return;
                }
                // 解码 base64 为字节数组
                const audioBytes = Uint8Array.from(atob(result.audio_base64), c => c.charCodeAt(0));
                // 确定 MIME 类型
                const mimeType = `audio/${result.format || 'mpeg'}`;
                const blob = new Blob([audioBytes], { type: mimeType });
                const audioUrl = URL.createObjectURL(blob);
                const audio = new Audio(audioUrl);
                audio.play();
                audio.onended = () => URL.revokeObjectURL(audioUrl);
            } catch (e) {
                console.error('预览失败:', e);
                showError('预览失败: ' + e.message);
            }
        }

        // 预览模态框
        const previewModalVisible = ref(false);
        const previewVoiceId = ref('');
        const previewText = ref('欢迎使用语音合成预览功能。');
        const previewLoading = ref(false);

        function openPreviewModal(voiceId) {
            previewVoiceId.value = voiceId;
            if (!previewText.value.trim()) {
                previewText.value = '欢迎使用语音合成预览功能。';
            }
            previewModalVisible.value = true;
        }

        async function doPreview() {
            if (!previewText.value.trim()) {
                showError('请输入预览文本');
                return;
            }
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            previewLoading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/preview', {
                    entry_id: selectedEntryId.value,
                    voice_id: previewVoiceId.value,
                    text: previewText.value.trim()
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
                previewLoading.value = false;
            }
        }

        function closePreviewModal() {
            previewModalVisible.value = false;
        }

        return {
            toastMessage,
            toastVisible,
            toastType,
            selectedEntryId,
            currentEntry,
            voiceList,
            loading,
            creating,
            mode,
            // 上传模式
            uploadForm,
            uploading,
            handleFileChange,
            uploadAndClone,
            // URL 模式
            urlForm,
            createFromUrl,
            // 公共
            languages,
            fetchVoices,
            deleteVoice,
            copyToClipboard,
            getStatusDescription,
            // 预览
            previewVoice,
            previewModalVisible,
            previewVoiceId,
            previewText,
            previewLoading,
            openPreviewModal,
            doPreview,
            closePreviewModal,
        };
    },
    template: `
        <div class="bailian-tts">
            <div v-if="toastVisible" class="toast" :class="{'toast-error': toastType === 'error'}">
                {{ toastMessage }}
            </div>

            <!-- 认证配置选择 -->
            <div class="form-group">
                <label>认证配置</label>
                <select v-model="selectedEntryId">
                    <option v-for="entry in entries" :key="entry.id" :value="entry.id">
                        {{ entry.display_name || entry.api_key_masked }} 
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
                <div style="background:#fef9e7;border-left:4px solid #f0ad4e;padding:8px 12px;margin-bottom:16px;border-radius:4px;">
                    <strong>⚠️ 重要：</strong> 请确认服务器拥有公网 IPv4 地址，且防火墙已开放指定端口 (上传模式) 或音频 URL 可被公网 IPv4 访问 (URL 模式)。
                </div>

                <!-- 选项卡切换 -->
                <div style="display:flex;gap:8px;margin-bottom:16px;border-bottom:1px solid var(--border);">
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'upload' }"
                        @click="mode = 'upload'"
                        style="padding:8px 16px;border:none;background:transparent;cursor:pointer;border-bottom:2px solid transparent;"
                    >
                        📁 上传音频文件（需公网IP）
                    </button>
                    <button 
                        class="tab" 
                        :class="{ active: mode === 'url' }"
                        @click="mode = 'url'"
                        style="padding:8px 16px;border:none;background:transparent;cursor:pointer;border-bottom:2px solid transparent;"
                    >
                        🔗 使用公网音频 URL
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
                        <label>内部监听端口（服务器本地绑定的端口）</label>
                        <input v-model="uploadForm.internal_port" placeholder="例如：8080（1024-65535）" />
                        <div class="hint">临时文件服务器在本机监听的端口，需确保未被占用</div>
                    </div>

                    <div class="form-group">
                        <label>选择音频文件（wav, mp3, m4a）</label>
                        <input type="file" id="fileInput" accept=".wav,.mp3,.m4a" @change="handleFileChange" />
                        <div class="hint" v-if="uploadForm.file">已选择: {{ uploadForm.file.name }}</div>
                    </div>

                    <div class="form-group">
                        <label>音色前缀</label>
                        <input v-model="uploadForm.prefix" placeholder="例如：upload" />
                        <div class="hint">仅字母数字，≤10字符</div>
                    </div>

                    <div class="form-group">
                        <label>语言提示</label>
                        <div class="language-radios">
                            <label v-for="lang in languages" :key="lang.code" class="lang-radio">
                                <input type="radio" :value="lang.code" v-model="uploadForm.language_hint" />
                                {{ lang.label }}
                            </label>
                        </div>
                    </div>

                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="uploadForm.enable_volume_normalization" id="upload_vol_norm" />
                        <label for="upload_vol_norm">启用音量归一化</label>
                    </div>

                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="uploadForm.enable_preprocess" id="upload_preproc" />
                        <label for="upload_preproc">启用音频预处理</label>
                    </div>

                    <div class="form-group" v-if="uploadForm.enable_preprocess">
                        <label>最大提示音频时长（秒）</label>
                        <input type="number" v-model.number="uploadForm.max_prompt_audio_length" step="0.1" min="3.0" max="30.0" />
                        <div class="hint">3.0 ~ 30.0，默认 10.0</div>
                    </div>

                    <div class="form-group">
                        <label>模型版本</label>
                        <select v-model="uploadForm.model">
                            <option value="flash">Flash</option>
                            <option value="plus">Plus</option>
                        </select>
                    </div>

                    <button class="btn" @click="uploadAndClone" :disabled="uploading">
                        {{ uploading ? '上传并处理中...' : '上传并复刻' }}
                    </button>
                </div>

                <!-- URL 模式 -->
                <div v-if="mode === 'url'">
                    <div class="form-group">
                        <label>公网音频 URL</label>
                        <input v-model="urlForm.audio_url" placeholder="例如：https://example.com/voice.wav" />
                        <div class="hint">支持格式：WAV(16bit)、MP3、M4A；时长 10~60 秒，文件 ≤10MB</div>
                    </div>

                    <div class="form-group">
                        <label>音色前缀</label>
                        <input v-model="urlForm.prefix" placeholder="例如：url_voice" />
                        <div class="hint">仅字母数字，≤10字符</div>
                    </div>

                    <div class="form-group">
                        <label>语言提示</label>
                        <div class="language-radios">
                            <label v-for="lang in languages" :key="lang.code" class="lang-radio">
                                <input type="radio" :value="lang.code" v-model="urlForm.language_hint" />
                                {{ lang.label }}
                            </label>
                        </div>
                    </div>

                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="urlForm.enable_volume_normalization" id="url_vol_norm" />
                        <label for="url_vol_norm">启用音量归一化</label>
                    </div>

                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="urlForm.enable_preprocess" id="url_preproc" />
                        <label for="url_preproc">启用音频预处理</label>
                    </div>

                    <div class="form-group" v-if="urlForm.enable_preprocess">
                        <label>最大提示音频时长（秒）</label>
                        <input type="number" v-model.number="urlForm.max_prompt_audio_length" step="0.1" min="3.0" max="30.0" />
                        <div class="hint">3.0 ~ 30.0，默认 10.0</div>
                    </div>

                    <div class="form-group">
                        <label>模型版本</label>
                        <select v-model="urlForm.model">
                            <option value="flash">Flash</option>
                            <option value="plus">Plus</option>
                        </select>
                    </div>

                    <button class="btn" @click="createFromUrl" :disabled="creating">
                        {{ creating ? '创建中...' : '创建音色（URL）' }}
                    </button>
                </div>
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
                            <td>{{ v.voice_id }}</td>
                            <td>{{ v.created_at }}</td>
                            <td>
                                <span :class="'status-' + v.status.toLowerCase()" :title="getStatusDescription(v.status)">
                                    {{ v.status }}
                                </span>
                            </td>
                            <td>
                                <button class="btn btn-sm" @click="copyToClipboard(v.voice_id)" title="复制 ID" style="margin-right: 8px;">复制</button>
                                <button class="btn btn-sm" @click="openPreviewModal(v.voice_id)" :disabled="v.status !== 'OK'" title="预览音色" style="margin-right: 8px;">预览</button>
                                <button class="btn btn-danger btn-sm" @click="deleteVoice(v.voice_id)">删除</button>
                            </td>
                        </tr>
                        <tr v-if="!voiceList.length">
                            <td colspan="4" style="text-align:center;color:var(--gray);">暂无音色</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- 预览模态框 -->
            <div v-if="previewModalVisible" class="modal-overlay" @mousedown.self="closePreviewModal">
                <div class="modal-content">
                    <h3>预览音色</h3>
                    <p><strong>Voice ID:</strong> {{ previewVoiceId }}</p>
                    <div class="form-group">
                        <label>预览文本</label>
                        <textarea v-model="previewText" rows="3" placeholder="输入要试听的文本"></textarea>
                    </div>
                    <div style="display:flex; gap:12px; justify-content:flex-end;">
                        <button class="btn" @click="doPreview" :disabled="previewLoading">
                            {{ previewLoading ? '合成中...' : '试听' }}
                        </button>
                        <button class="btn btn-sm" @click="closePreviewModal" style="background: var(--gray);">关闭</button>
                    </div>
                </div>
            </div>
        </div>
    `
};
