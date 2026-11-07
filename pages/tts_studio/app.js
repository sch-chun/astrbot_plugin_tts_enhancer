const { createApp, ref, shallowRef, computed, watch, onMounted, onUnmounted } = Vue;

// 单一页面合并「音色管理」与「合成记录」两个视图。
// 两个视图共享：bridge（AstrBotPluginPage）、全局音量条、通知条、删除确认弹层，
// 以及 useAudioManager 的模块级单例（同一个 volume / 播放实例 / 播放标识）。
import BailianQwenAudio3_0 from './components/bailian_qwen_audio_3_0_tts.js';
import BailianQwenAudio3_1 from './components/bailian_qwen_audio_3_1_tts.js';
import BailianCosyvoiceV3_5 from './components/bailian_cosyvoice_v3_5.js';
import MinimaxSpeech2_8 from './components/minimax_speech_2_8.js';
import BailianMinimaxSpeech2_8 from './components/bailian_minimax_speech_2_8.js';
import { useAudioManager, base64ToBlobUrl } from './composables/useAudioManager.js';

const bridge = window.AstrBotPluginPage;

const app = createApp({
    setup() {
        // ---------- 共享状态 ----------
        const activeView = ref('manager'); // 'manager' | 'records'

        // 各视图独立加载态：外壳（左栏 + 顶栏音量条）立即渲染，
        // 表单 / 列表数据就绪后再渲染，避免整页干等「加载中」。
        const managerLoading = ref(true);
        const recordsLoading = ref(true);
        // 瞬时层（确认弹层 / 通知条）仅在初始加载完成后再挂载，避免加载阶段闪烁。
        const booted = ref(false);

        // 全局单例音频管理器：两个视图共用同一音量 / 播放实例 / 播放标识，
        // 因此全局音量条与「正在播放」高亮在任一视图都一致，且不会出现两套音量互相打架。
        const { volume, currentPlayingId, playAudio, stopAudio, isPlaying } = useAudioManager();

        // 共享通知条（toast）
        const toast = ref({ visible: false, message: '', type: 'info', pause: false });
        let toastTimer = null;
        function showToast(message, type = 'info') {
            toast.value = { visible: true, message, type, pause: false };
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => {
                if (!toast.value.pause) toast.value.visible = false;
                else {
                    const t = setInterval(() => {
                        if (!toast.value.pause) {
                            toast.value.visible = false;
                            clearInterval(t);
                        }
                    }, 300);
                }
            }, 3000);
        }
        const showError = (msg) => showToast(msg, 'error');

        // 共享删除确认弹层
        const confirm = ref({ visible: false, title: '', message: '', action: null });
        function showConfirm(title, message, action) {
            confirm.value = { visible: true, title, message, action };
        }
        function cancelConfirm() {
            confirm.value = { visible: false, title: '', message: '', action: null };
        }
        async function doConfirm() {
            const action = confirm.value.action;
            cancelConfirm();
            if (typeof action === 'function') {
                try { await action(); } catch (e) { showError(e.message); }
            }
        }

        // ---------- 音色管理视图（来自 tts_manager） ----------
        const groups = ref([]);
        const currentTab = ref('');
        const currentComponent = shallowRef(null);
        const currentEntries = ref([]);

        const componentMap = {
            'bailian_qwen_audio_3_0_tts': BailianQwenAudio3_0,
            'bailian_qwen_audio_3_1_tts': BailianQwenAudio3_1,
            'bailian_cosyvoice_v3_5': BailianCosyvoiceV3_5,
            'minimax_speech_2_8': MinimaxSpeech2_8,
            'bailian_minimax_speech_2_8': BailianMinimaxSpeech2_8,
            // template_key → 前端 Vue 组件，仅负责「该供应商的 UI 由哪个组件实现」。
            // tab 可见性已由后端 capabilities.voice_management 决定；此处只需在新增支持
            // 音色管理的供应商时同步注册其组件，否则该 tab 会渲染空白。
        };

        const visibleGroups = computed(() =>
            // tab 可见性由后端 capabilities.voice_management 决定（单一数据源），
            // 不再依赖前端 componentMap 硬编码，避免「后端说支持、前端 tab 不显示」的漂移。
            groups.value.filter(g => g.capabilities?.voice_management)
        );

        async function fetchProviders() {
            managerLoading.value = true;
            try {
                const result = await bridge.apiGet('providers');
                const data = result.data || result;
                groups.value = data;
                if (visibleGroups.value.length > 0) {
                    currentTab.value = visibleGroups.value[0].template_key;
                    switchTab(currentTab.value);
                    requestAnimationFrame(() => moveTabIndicator(false));
                }
            } catch (e) {
                console.error('获取供应商列表失败:', e);
                showError('无法加载供应商配置：' + e.message);
            } finally {
                managerLoading.value = false;
            }
        }

        // 将高亮滑动条对齐到激活标签；逻辑同原 tts_manager（仅查询选择器保持 .tabs）。
        function moveTabIndicator(animate = true) {
            const indicator = document.querySelector('.tabs .tab-indicator');
            if (!indicator) return;
            const tabs = indicator.parentElement;
            const activeTab = tabs.querySelector('.tab.active');
            if (!activeTab) return;
            const tabsRect = tabs.getBoundingClientRect();
            const tabRect = activeTab.getBoundingClientRect();
            if (!animate) indicator.style.transition = 'none';
            const baseWidth = indicator.offsetWidth;
            indicator.style.transform =
                `translateX(${tabRect.left - tabsRect.left}px) scaleX(${tabRect.width / baseWidth})`;
            if (!animate) {
                void indicator.offsetWidth;
                indicator.style.transition = '';
            }
        }

        function switchTab(templateKey) {
            const group = groups.value.find(g => g.template_key === templateKey);
            if (!group) return;
            currentTab.value = templateKey;
            currentEntries.value = group.entries;
            const comp = componentMap[templateKey];
            currentComponent.value = comp || null;
            requestAnimationFrame(() => moveTabIndicator(true));
        }

        let resizeRafId = 0;
        function onResize() {
            if (resizeRafId) return;
            resizeRafId = requestAnimationFrame(() => {
                resizeRafId = 0;
                moveTabIndicator(false);
            });
        }

        // ---------- 合成记录视图（来自 synthesis_records，复用共享音频单例） ----------
        const records = ref([]);
        const sourceFilter = ref('all');

        const SOURCE_LABELS = {
            chat: '聊天语音',
            preview: '音色预览',
            design_preview: '设计试听',
            agent: 'Agent 发送',
        };

        const filteredRecords = computed(() => {
            if (sourceFilter.value === 'all') return records.value;
            return records.value.filter(r => r.source === sourceFilter.value);
        });

        function sourceLabel(source) {
            return SOURCE_LABELS[source] || source || '未知';
        }

        function formatTime(iso) {
            if (!iso) return '';
            try {
                const d = new Date(iso);
                if (isNaN(d.getTime())) return iso;
                return d.toLocaleString();
            } catch (_) {
                return iso;
            }
        }

        function formatSize(bytes) {
            if (bytes == null) return '';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
        }

        // 合成记录详情分两组展示：
        //  - AI 增强参数（rec.params）：来自 SubAgent 增强，如指令 / 音量 / 语速 / 音调 / 语言；
        //  - 配置参数（rec.config）：本次合成使用的供应商配置快照，如音色 / 格式 / 采样率 / 模型。
        // 仅展示存在且非空的字段，缺省/空值自动跳过；不含 api_key 等密钥。
        const ENHANCE_LABELS = {
            instruction: '指令',
            volume: '音量',
            rate: '语速',
            pitch: '音调',
            language_hints: '语言',
        };
        const CONFIG_LABELS = {
            voice: '音色',
            format: '格式',
            sample_rate: '采样率',
            model: '模型',
        };

        function _paramsToList(source, labels) {
            if (!source || typeof source !== 'object') return [];
            const items = [];
            for (const [key, label] of Object.entries(labels)) {
                let value = source[key];
                if (value === undefined || value === null || value === '') continue;
                if (key === 'language_hints' && Array.isArray(value)) {
                    value = value.join('/');
                }
                items.push({ label, value: String(value) });
            }
            return items;
        }

        function recordParams(rec) {
            return _paramsToList(rec && rec.params, ENHANCE_LABELS);
        }

        function recordConfig(rec) {
            return _paramsToList(rec && rec.config, CONFIG_LABELS);
        }

        // 每条记录展开/收起详情的本地状态（按记录 id 记录）
        const expanded = ref({});
        function toggleExpand(rec) {
            expanded.value[rec.id] = !expanded.value[rec.id];
        }

        async function fetchRecords() {
            recordsLoading.value = true;
            try {
                const result = await bridge.apiPost('synthesis-records', {});
                // dashboard 桥会把后端响应解包一层：result 已是内层 data（记录数组），
                // 也可能仍是带 .data 的完整响应，这里两者兼容。
                const data = result?.data ?? result;
                records.value = Array.isArray(data) ? data : [];
            } catch (e) {
                console.error('读取合成记录失败:', e);
                showError('读取合成记录失败: ' + e.message);
                records.value = [];
            } finally {
                recordsLoading.value = false;
            }
        }

        async function togglePlay(rec) {
            if (isPlaying(rec.id)) {
                stopAudio();
                return;
            }
            try {
                const result = await bridge.apiPost('synthesis-records/audio', { id: rec.id });
                // 同 fetchRecords：兼容 dashboard 解包与未解包两种结构。
                const payload = result?.data ?? result;
                if (!payload || !payload.audio_base64) {
                    showError('音频数据缺失');
                    return;
                }
                const mimeType = `audio/${payload.format || 'mp3'}`;
                const audioUrl = base64ToBlobUrl(payload.audio_base64, mimeType);
                playAudio(audioUrl, rec.id, {
                    cleanup: () => URL.revokeObjectURL(audioUrl),
                    onError: (e) => showError('播放失败: ' + e.message),
                });
            } catch (e) {
                console.error('获取合成音频失败:', e);
                showError('获取合成音频失败: ' + e.message);
            }
        }

        function confirmDelete(rec) {
            showConfirm(
                '⚠️ 确认删除',
                `确定要删除这条合成记录吗？此操作不可恢复。\n来源：${sourceLabel(rec.source)}`,
                async () => {
                    await bridge.apiPost('synthesis-records/delete', { id: rec.id });
                    await fetchRecords();
                    showToast('已删除');
                }
            );
        }

        function confirmClear() {
            showConfirm(
                '⚠️ 清空全部',
                '确定要清空全部合成记录吗？此操作不可恢复。',
                async () => {
                    const result = await bridge.apiPost('synthesis-records/clear', {});
                    // 同 fetchRecords：兼容 dashboard 解包与未解包两种结构。
                    const deleted = (result?.data?.deleted) ?? result?.deleted ?? 0;
                    stopAudio();
                    await fetchRecords();
                    showToast(`已清空 ${deleted} 条记录`);
                }
            );
        }

        // ---------- 背景图（共享，仅配置时由 JS 注入） ----------
        async function applyPageBackground() {
            try {
                const result = await bridge.apiGet('page-background');
                // 注意：dashboard 的 api:get 代理会把后端响应解包一层，
                // resolve 的是内层 data 对象（无 .data 字段）；保留 || result 兜底
                // 以兼容两种结构，否则取到的 data 为 undefined 会静默跳过背景图。
                const data = result?.data || result;
                if (!data || !data.data_url) return;
                const img = document.getElementById('page-bg-img');
                if (!img) return;
                const opacity = String(data.opacity ?? 1);
                const blur = Number(data.blur ?? 0);
                const preload = new Image();
                preload.onload = () => {
                    img.style.backgroundImage = `url("${data.data_url}")`;
                    img.style.filter = blur > 0 ? `blur(${blur}px)` : 'none';
                    img.style.opacity = opacity;
                };
                preload.src = data.data_url;
            } catch (e) {
                console.warn('加载背景图失败:', e);
            }
        }

        // ---------- 视图切换：切换时停掉正在播放的音频，避免跨视图残留 ----------
        function switchView(view) {
            if (view === activeView.value) return;
            activeView.value = view;
            stopAudio();
            if (view === 'records') fetchRecords();
        }

        // ---------- 挂载 ----------
        onMounted(() => {
            Promise.resolve(bridge.ready())
                .then(() => {
                    applyPageBackground();
                    // 两个视图各自管理加载态，外壳不阻塞，无需等待全部数据再挂载。
                    // 两者都结束后才置 booted，瞬时层（弹层 / 通知）随后挂载，避免加载期闪烁。
                    return Promise.allSettled([fetchProviders(), fetchRecords()]);
                })
                .then(() => {
                    booted.value = true;
                })
                .catch((e) => {
                    console.error('初始化失败:', e);
                    showError('初始化失败: ' + e.message);
                    // 初始化失败时也要解除阻塞，避免一直显示加载占位。
                    managerLoading.value = false;
                    recordsLoading.value = false;
                    booted.value = true;
                });
            window.addEventListener('resize', onResize);
        });

        onUnmounted(() => {
            window.removeEventListener('resize', onResize);
            if (resizeRafId) {
                cancelAnimationFrame(resizeRafId);
                resizeRafId = 0;
            }
        });

        return {
            // 布局 / 共享
            activeView,
            switchView,
            bridge,
            volume,
            toast,
            confirm,
            cancelConfirm,
            doConfirm,

            // 各视图加载态（外壳先行，内容后渲染）
            managerLoading,
            recordsLoading,
            booted,

            // 音色管理视图
            groups,
            visibleGroups,
            currentTab,
            currentComponent,
            currentEntries,
            switchTab,

            // 合成记录视图
            records,
            filteredRecords,
            sourceFilter,
            sourceLabel,
            formatTime,
            formatSize,
            togglePlay,
            isPlaying,
            confirmDelete,
            confirmClear,
            // 记录展开详情（AI 增强参数 / 配置参数）
            expanded,
            toggleExpand,
            recordParams,
            recordConfig,
        };
    },
});

app.mount('#app');

// 移除 Vue 编译前的静态占位（boot-loader），避免裸模板 {{ }} 在 ES 模块加载期闪现。
// 挂载同步完成后 DOM 已是编译后的外壳（含 loading-block 占位），直接接管显示。
const bootLoader = document.getElementById('boot-loader');
if (bootLoader) bootLoader.remove();
