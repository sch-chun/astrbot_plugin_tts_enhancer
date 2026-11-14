const { createApp, ref, shallowRef, computed, watch, onMounted, onUnmounted, reactive } = Vue;

// 单一页面合并「音色管理」与「合成记录」两个视图。
// 两个视图共享：bridge（AstrBotPluginPage）、全局音量条、通知条、删除确认弹层，
// 以及 useAudioManager 的模块级单例（同一个 volume / 播放实例 / 播放标识）。
import BailianQwenAudio3_0 from './components/bailian_qwen_audio_3_0_tts.js';
import BailianQwenAudio3_1 from './components/bailian_qwen_audio_3_1_tts.js';
import BailianCosyvoiceV3_5 from './components/bailian_cosyvoice_v3_5.js';
import MinimaxSpeech2_8 from './components/minimax_speech_2_8.js';
import BailianMinimaxSpeech2_8 from './components/bailian_minimax_speech_2_8.js';
import { useAudioManager, base64ToBlobUrl } from './composables/useAudioManager.js';
import { selectVoiceTabs, firstUsableTab } from './voiceTabs.js';
import { clearVoiceListCache } from './composables/useVoiceListCache.js';

const bridge = window.AstrBotPluginPage;

// 页面文案随 WebUI 语言切换：所有用户可见字符串经 bridge.t("views.tts_studio.<key>", 中文兜底) 读取，
// 初始 ready 后调用一次 applyI18n()，并注册 bridge.onContext(applyI18n) 以响应语言切换（无需刷新页面）。
// i18n 文本来源：插件 .astrbot-plugin/i18n/{locale}.json 的 views.tts_studio 段（回退链 locale→zh-CN→en-US→兜底）。
const i18n = reactive({
    brand: 'TTS 增强',
    navManager: '音色管理',
    navRecords: '合成记录',
    docTitle: 'TTS 增强 · 控制台',
    globalVolume: '全局音量',
    managerTitle: 'TTS 音色管理',
    recordsTitle: 'TTS 合成记录',
    loading: '加载中...',
    emptyConfigured: '⚠️ 已配置 {n} 个供应商（{names}），但当前版本暂未提供其可视化面板。如需在此面板内管理，请配置支持前端操作的服务商（如百炼 / MiniMax）。',
    emptyNoProviders: '⚠️ 暂无 TTS 供应商配置，请在插件配置中添加 providers 条目。',
    filterLabel: '来源',
    sourceAll: '全部',
    sourceChat: '聊天语音',
    sourcePreview: '音色预览',
    sourceDesign: '设计试听',
    sourceAgent: 'Agent 发送',
    countHint: '共 {n} 条',
    clearAll: '清空全部',
    emptyFiltered: '⚠️ 当前筛选条件下没有合成记录。',
    emptyNone: '🎙️ 暂无合成记录。合成过的语音（聊天语音、音色预览、设计试听等）会自动出现在这里。',
    unknownProvider: '未知供应商',
    noText: '（无文本）',
    durationPrefix: '时长 ',
    durationUnit: 's',
    sourcePrefix: '来源：',
    stop: '⏹ 停止',
    play: '▶ 播放',
    delete: '删除',
    collapse: '收起 ▴',
    details: '详情 ▾',
    enhanceInstruction: '指令',
    enhanceVolume: '音量',
    enhanceRate: '语速',
    enhancePitch: '音调',
    enhanceLanguage: '语言',
    configVoice: '音色',
    configFormat: '格式',
    configSampleRate: '采样率',
    configModel: '模型',
    enhanceParams: 'AI 增强参数',
    configParams: '配置参数',
    noParams: '本次合成未记录参数详情。',
    cancel: '取消',
    confirm: '确认',
    confirmDeleteTitle: '⚠️ 确认删除',
    confirmClearTitle: '⚠️ 清空全部',
    confirmDeleteMsg: '确定要删除这条合成记录吗？此操作不可恢复。\n来源：{source}',
    confirmClearMsg: '确定要清空全部合成记录吗？此操作不可恢复。',
    toastDeleted: '已删除',
    toastCleared: '已清空 {n} 条记录',
    errLoadProviders: '无法加载供应商配置：',
    errReadRecords: '读取合成记录失败: ',
    errAudioMissing: '音频数据缺失',
    errPlayback: '播放失败: ',
    errFetchAudio: '获取合成音频失败: ',
    errInit: '初始化失败: ',
    unknown: '未知',
});

function applyI18n() {
    for (const key of Object.keys(i18n)) {
        i18n[key] = bridge.t('views.tts_studio.' + key, i18n[key]);
    }
    document.title = i18n.docTitle;
    // 在 <html> 上挂当前 locale 类（loc-<locale>），供 CSS 区分 CJK 竖排与拉丁 90° 旋转。
    const locale = (typeof bridge.getLocale === 'function') ? bridge.getLocale() : 'zh-CN';
    const root = document.documentElement;
    root.classList.remove('loc-zh-CN', 'loc-ja-JP', 'loc-en-US', 'loc-ru-RU');
    if (locale) root.classList.add('loc-' + locale);
}

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
            // 可见性已由后端 capabilities.voice_management 决定（见 visibleGroups），不再依赖此 map；
            // 若新增支持音色管理的供应商，务必在此同步注册组件，否则 switchTab 会
            // 以 `if (!comp) return` 拦截该 tab（点击无响应、视图不会空白）。
        };

        const visibleGroups = computed(() =>
            // tab 可见性由后端 capabilities.voice_management 决定（单一数据源），
            // 不再依赖前端 componentMap 硬编码，避免「后端说支持、前端 tab 不显示」的漂移。
            // 筛选逻辑抽到 voiceTabs.js 的 selectVoiceTabs，便于单测（tests/voiceTabs.test.mjs）。
            selectVoiceTabs(groups.value)
        );

        async function fetchProviders() {
            managerLoading.value = true;
            // providers 列表重新加载意味着后端配置可能已变化（增删 entry 等），
            // 旧的音色列表缓存会指向失效的 entry_id / 参数，这里先清掉，避免命中脏数据。
            clearVoiceListCache();
            try {
                const result = await bridge.apiGet('providers');
                const data = result.data || result;
                groups.value = data;
                if (visibleGroups.value.length > 0) {
                    // 默认选中第一个「既有后端能力、又注册了前端组件」的供应商，
                    // 避免排序后第一个恰好是未注册组件者，导致整个音色管理视图空白（P3）。
                    // 选择逻辑抽到 voiceTabs.js 的 firstUsableTab，便于单测。
                    const first = firstUsableTab(visibleGroups.value, (k) => Boolean(componentMap[k]));
                    if (first) {
                        currentTab.value = first.template_key;
                        switchTab(currentTab.value);
                        requestAnimationFrame(() => moveTabIndicator(false));
                    }
                }
            } catch (e) {
                console.error('获取供应商列表失败:', e);
                showError(i18n.errLoadProviders + e.message);
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
            const comp = componentMap[templateKey];
            // 后端标记支持音色管理、但前端尚未注册组件的供应商：直接拦截，
            // 避免切到空组件导致整页音色管理视图变空白（P3，对照 componentMap 注释）。
            if (!comp) return;
            currentTab.value = templateKey;
            currentEntries.value = group.entries;
            currentComponent.value = comp;
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

        // 来源标签：记录 source 键 → i18n 键（文案随语言切换由 applyI18n 更新）。
        const SOURCE_KEYS = {
            chat: 'sourceChat',
            preview: 'sourcePreview',
            design_preview: 'sourceDesign',
            agent: 'sourceAgent',
        };

        const filteredRecords = computed(() => {
            if (sourceFilter.value === 'all') return records.value;
            return records.value.filter(r => r.source === sourceFilter.value);
        });

        function sourceLabel(source) {
            const i18nKey = SOURCE_KEYS[source];
            return (i18nKey ? i18n[i18nKey] : null) || i18n.unknown;
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
        // 字段键 → i18n 键，标签经 applyI18n 随语言切换。
        const ENHANCE_KEYS = {
            instruction: 'enhanceInstruction',
            volume: 'enhanceVolume',
            rate: 'enhanceRate',
            pitch: 'enhancePitch',
            language_hints: 'enhanceLanguage',
        };
        const CONFIG_KEYS = {
            voice: 'configVoice',
            format: 'configFormat',
            sample_rate: 'configSampleRate',
            model: 'configModel',
        };

        function _paramsToList(source, keys) {
            if (!source || typeof source !== 'object') return [];
            const items = [];
            for (const [key, i18nKey] of Object.entries(keys)) {
                let value = source[key];
                if (value === undefined || value === null || value === '') continue;
                if (key === 'language_hints' && Array.isArray(value)) {
                    value = value.join('/');
                }
                items.push({ label: i18n[i18nKey], value: String(value) });
            }
            return items;
        }

        function recordParams(rec) {
            return _paramsToList(rec && rec.params, ENHANCE_KEYS);
        }

        function recordConfig(rec) {
            return _paramsToList(rec && rec.config, CONFIG_KEYS);
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
                showError(i18n.errReadRecords + e.message);
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
                    showError(i18n.errAudioMissing);
                    return;
                }
                const mimeType = `audio/${payload.format || 'mp3'}`;
                const audioUrl = base64ToBlobUrl(payload.audio_base64, mimeType);
                playAudio(audioUrl, rec.id, {
                    cleanup: () => URL.revokeObjectURL(audioUrl),
                    onError: (e) => showError(i18n.errPlayback + e.message),
                });
            } catch (e) {
                console.error('获取合成音频失败:', e);
                showError(i18n.errFetchAudio + e.message);
            }
        }

        function confirmDelete(rec) {
            showConfirm(
                i18n.confirmDeleteTitle,
                i18n.confirmDeleteMsg.replace('{source}', sourceLabel(rec.source)),
                async () => {
                    await bridge.apiPost('synthesis-records/delete', { id: rec.id });
                    await fetchRecords();
                    showToast(i18n.toastDeleted);
                }
            );
        }

        function confirmClear() {
            showConfirm(
                i18n.confirmClearTitle,
                i18n.confirmClearMsg,
                async () => {
                    const result = await bridge.apiPost('synthesis-records/clear', {});
                    // 同 fetchRecords：兼容 dashboard 解包与未解包两种结构。
                    const deleted = (result?.data?.deleted) ?? result?.deleted ?? 0;
                    stopAudio();
                    await fetchRecords();
                    showToast(i18n.toastCleared.replace('{n}', deleted));
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

        // 已配置但无可视化面板的空态文案（含插值 {n}/{names}），随语言切换。
        const emptyConfiguredText = computed(() => {
            const names = groups.value.map(g => g.display_name || g.template_key).join('、');
            return i18n.emptyConfigured
                .replace('{n}', groups.value.length)
                .replace('{names}', names);
        });

        // ---------- 挂载 ----------
        onMounted(() => {
            // 注册语言切换监听：WebUI 切换语言时无需刷新页面即重渲所有文案。
            bridge.onContext(applyI18n);
            Promise.resolve(bridge.ready())
                .then(() => {
                    applyI18n();
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
                    showError(i18n.errInit + e.message);
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
            i18n,
            emptyConfiguredText,
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
