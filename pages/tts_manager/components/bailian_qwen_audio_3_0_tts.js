import { ref, reactive, watch, computed } from 'vue';

export default {
    name: 'BailianQwenAudio3_0',
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true },
    },
    setup(props) {
        const toastMessage = ref('');
        const toastVisible = ref(false);
        const toastType = ref('success'); // 'success' 或 'error'
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

        const prefixError = computed(() => {
            const val = form.prefix;
            if (!val) return '';
            if (!/^[a-zA-Z0-9]+$/.test(val)) return '只能包含字母和数字';
            if (val.length > 10) return '长度不能超过10个字符';
            return '';
        });

        function validatePrefix() {
            // 用于提交时的检查
            return !prefixError.value;
        }

        const selectedEntryId = ref(null);
        const voiceList = ref([]);
        const loading = ref(false);
        const creating = ref(false);

        const form = reactive({
            audio_url: '',
            prefix: '',
            language_hint: 'zh',          // 单选，存储单个语言代码
            enable_volume_normalization: false,
            enable_preprocess: false,
            max_prompt_audio_length: 10.0,
            model: 'flash',
        });

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
                form.model = newEntry.model || 'flash';
            }
        }, { immediate: true });

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

        async function createVoice() {
            if (selectedEntryId.value === null || selectedEntryId.value === undefined) {
                showError('请先选择认证配置');
                return;
            }
            if (!form.audio_url || !form.prefix) {
                showError('请填写音频 URL 和音色前缀');
                return;
            }
            if (prefixError.value) {
                showError('音色前缀格式错误：' + prefixError.value);
                return;
            }
            // 验证 max_prompt_audio_length 范围
            if (form.enable_preprocess && (form.max_prompt_audio_length < 3.0 || form.max_prompt_audio_length > 30.0)) {
                showError('最大提示音频时长必须在 3.0 ~ 30.0 秒之间');
                return;
            }
            creating.value = true;
            try {
                const payload = {
                    entry_id: selectedEntryId.value,
                    audio_url: form.audio_url,
                    prefix: form.prefix,
                    language_hints: form.language_hint ? [form.language_hint] : [],
                    enable_volume_normalization: form.enable_volume_normalization,
                    enable_preprocess: form.enable_preprocess,
                    max_prompt_audio_length: form.enable_preprocess ? form.max_prompt_audio_length : undefined,
                    model: form.model,
                };
                // 移除 undefined 值
                Object.keys(payload).forEach(key => {
                    if (payload[key] === undefined) delete payload[key];
                });
                const result = await props.bridge.apiPost('voice/create', payload);
                showSuccess('音色创建成功！Voice ID: ' + result.voice_id);
                await fetchVoices();
                // 重置表单（保留 language_hint 和 model 默认值）
                form.audio_url = '';
                form.prefix = '';
                form.enable_volume_normalization = false;
                form.enable_preprocess = false;
                form.max_prompt_audio_length = 10.0;
                // language_hint 和 model 保持不变
            } catch (e) {
                console.error('创建音色失败:', e);
                showError('创建音色失败: ' + e.message);
            } finally {
                creating.value = false;
            }
        }

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

        watch(selectedEntryId, (newId, oldId) => {
            if (newId !== null && newId !== undefined && newId !== oldId) {
                fetchVoices();
            }
        });

        function getStatusDescription(status) {
            const map = {
                'DEPLOYING': '审核中/处理中',
                'OK': '审核通过，可正常使用',
                'UNDEPLOYED': '审核未通过，不可使用'
            };
            return map[status] || status;
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
            form,
            languages,
            prefixError,
            fetchVoices,
            createVoice,
            deleteVoice,
            copyToClipboard,
            getStatusDescription
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

            <!-- 创建音色 -->
            <fieldset style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;">
                <legend>创建新音色</legend>

                <div class="form-group">
                    <label>音频 URL（公网可访问）</label>
                    <input v-model="form.audio_url" placeholder="例如：https://example.com/voice.wav" />
                    <div class="hint">支持格式：WAV(16bit)、MP3、M4A；时长 10~60 秒，文件 ≤10MB</div>
                </div>

                <div class="form-group">
                    <label>音色前缀（仅字母数字，≤10字符）</label>
                    <input v-model="form.prefix" placeholder="例如：myvoice" :class="{ 'input-error': prefixError }" />
                    <div v-if="prefixError" class="error-hint">{{ prefixError }}</div>
                    <div class="hint">生成的音色 ID 格式：{target_model}-{prefix}-{唯一标识}</div>
                </div>

                <div class="form-group">
                    <label>模型版本</label>
                    <select v-model="form.model">
                        <option value="flash">Flash</option>
                        <option value="plus">Plus</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>语言提示（单选，仅取第一个）</label>
                    <div class="language-radios">
                        <label v-for="lang in languages" :key="lang.code" class="lang-radio">
                            <input type="radio" :value="lang.code" v-model="form.language_hint" />
                            {{ lang.label }}
                        </label>
                    </div>
                    <div class="hint">辅助模型识别样本语种，提升复刻效果。若与实际不符，系统将自动检测</div>
                </div>

                <div class="form-group checkbox-group">
                    <input type="checkbox" v-model="form.enable_volume_normalization" id="vol_norm" />
                    <label for="vol_norm">启用音量归一化</label>
                    <span class="hint-inline">开启后合成音频音量可能与原始样本不同</span>
                </div>

                <div class="form-group checkbox-group">
                    <input type="checkbox" v-model="form.enable_preprocess" id="preproc" />
                    <label for="preproc">启用音频预处理（降噪、增强、规整）</label>
                    <span class="hint-inline">有背景噪音时建议开启；安静环境关闭以最大还原音色</span>
                </div>

                <div class="form-group" v-if="form.enable_preprocess">
                    <label>最大提示音频时长（秒）</label>
                    <input type="number" v-model.number="form.max_prompt_audio_length" step="0.1" min="3.0" max="30.0" />
                    <div class="hint">取值范围：3.0 ~ 30.0，默认 10.0。仅当预处理开启时生效</div>
                </div>

                <button class="btn" @click="createVoice" :disabled="creating">
                    {{ creating ? '创建中...' : '创建音色' }}
                </button>
            </fieldset>

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
                                <button class="btn btn-danger btn-sm" @click="deleteVoice(v.voice_id)">删除</button>
                            </td>
                        </tr>
                        <tr v-if="!voiceList.length">
                            <td colspan="4" style="text-align:center;color:var(--gray);">暂无音色</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `
};
