const { createApp, ref, shallowRef, onMounted } = Vue;

// 静态导入所有已知供应商组件
import BailianQwenAudio3_0 from './components/bailian_qwen_audio_3_0_tts.js';
import BailianQwenAudio3_1 from './components/bailian_qwen_audio_3_1_tts.js';
import BailianCosyvoiceV3_5 from './components/bailian_cosyvoice_v3_5.js'
import MinimaxSpeech2_8 from './components/minimax_speech_2_8.js';
import BailianMinimaxSpeech2_8 from './components/bailian_minimax_speech_2_8.js';
import { useAudioManager } from './composables/useAudioManager.js';

const bridge = window.AstrBotPluginPage;

const app = createApp({
    setup() {
        const groups = ref([]);
        const currentTab = ref('');
        const currentComponent = shallowRef(null);
        const currentEntries = ref([]);
        const loading = ref(true);

        // 全局单例音频管理器（共享音量，供顶层音量条使用）
        const { volume } = useAudioManager();

        // 组件映射表（template_key → Vue 组件）
        const componentMap = {
            'bailian_qwen_audio_3_0_tts': BailianQwenAudio3_0,
            'bailian_qwen_audio_3_1_tts': BailianQwenAudio3_1,
            'bailian_cosyvoice_v3_5': BailianCosyvoiceV3_5,
            'minimax_speech_2_8': MinimaxSpeech2_8,
            'bailian_minimax_speech_2_8': BailianMinimaxSpeech2_8

            // 未来添加新供应商时在此处增加映射
        };

        async function fetchProviders() {
            try {

                // 确保 bridge 已就绪
                await bridge.ready();
                const result = await bridge.apiGet('providers');

                // 后端返回 { code: 0, data: [...] }
                const data = result.data || result;
                groups.value = data;
                if (data.length > 0) {
                    currentTab.value = data[0].template_key;
                    switchTab(currentTab.value);
                    // 初始定位不走过渡，避免高亮条从原点滑入。
                    // 用 rAF 而非 nextTick：本场景下 nextTick 回调早于 v-else 挂载执行，取不到元素
                    requestAnimationFrame(() => moveTabIndicator(false));
                }
            } catch (e) {
                console.error('获取供应商列表失败:', e);
                alert('无法加载供应商配置，请检查插件是否启用并配置了 providers。\n' + e.message);
            } finally {
                loading.value = false;
            }
        }

        async function applyPageBackground() {
            try {
                const result = await bridge.apiGet('page-background');
                const data = result?.data || result;
                // 未配置背景图（data_url 为空）则不显示，保持默认主题底色
                if (!data || !data.data_url) return;
                const img = document.getElementById('page-bg-img');
                if (!img) return;
                const opacity = String(data.opacity ?? 1);
                const blur = Number(data.blur ?? 0);
                // 预加载图片，解码完成后再设置背景并提升透明度：
                // CSS 中 #page-bg-img 默认 opacity 0 且带 transition，
                // 此处赋值即触发从 0 到目标值的淡入；图片加载失败则保持透明不显示
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

        // 高亮条基准宽度（px），与 style.css .tab-indicator 的 width 保持一致：
        // 元素保持基准宽不动，用 translateX + scaleX 换算到目标标签，
        // 使过渡只跑 transform（合成器线程），背景淡入期切换也不掉帧
        const INDICATOR_BASE_WIDTH = 100;

        // 将高亮滑动条对齐到激活标签：animate=false 时瞬时定位（初始渲染/窗口尺寸变化）。
        // 直接查 DOM 而非模板 ref：v-if 挂载当帧的 ref 绑定晚于 nextTick 回调，取不到。
        // 用 getBoundingClientRect 取亚像素精度，换算 transform 而非设 left/width。
        function moveTabIndicator(animate = true) {
            const indicator = document.querySelector('.tabs .tab-indicator');
            if (!indicator) return;
            const tabs = indicator.parentElement;
            const activeTab = tabs.querySelector('.tab.active');
            if (!activeTab) return;
            const tabsRect = tabs.getBoundingClientRect();
            const tabRect = activeTab.getBoundingClientRect();
            if (!animate) {
                indicator.style.transition = 'none';
            }
            indicator.style.transform =
                `translateX(${tabRect.left - tabsRect.left}px) scaleX(${tabRect.width / INDICATOR_BASE_WIDTH})`;
            if (!animate) {
                void indicator.offsetWidth; // 强制回流，恢复过渡供下次平滑平移
                indicator.style.transition = '';
            }
        }

        function switchTab(templateKey) {
            const group = groups.value.find(g => g.template_key === templateKey);
            if (!group) return;
            currentTab.value = templateKey;
            currentEntries.value = group.entries;

            // 从映射表中获取组件
            const comp = componentMap[templateKey];
            if (comp) {
                currentComponent.value = comp;
            } else {
                console.warn(`未找到 ${templateKey} 对应的组件，将显示空占位。`);
                currentComponent.value = null;
            }

            // 等 DOM 更新后把高亮条平滑滑到新标签位置。
            // 用 rAF 而非 nextTick：本场景下 nextTick 回调早于 v-else 挂载执行，取不到元素
            requestAnimationFrame(() => moveTabIndicator(true));
        }

        function getDisplayName(key) {
            const map = {
                'bailian_qwen_audio_3_0_tts': '百炼 Qwen Audio 3.0 TTS',
                'bailian_qwen_audio_3_1_tts': '百炼 Qwen Audio 3.1 TTS',
                'bailian_cosyvoice_v3_5': '百炼 Cosyvoice-V3.5',
                'minimax_speech_2_8': 'MiniMax Speech 2.8',
                'bailian_minimax_speech_2_8': '百炼 MiniMax Speech 2.8'
                
                // 未来扩展
            };
            return map[key] || key;
        }

        onMounted(() => {
            fetchProviders();
            applyPageBackground();
            // 窗口尺寸变化会改变标签宽度，重新瞬时对齐高亮条
            window.addEventListener('resize', () => moveTabIndicator(false));
        });

        return {
            groups,
            loading,
            currentTab,
            currentComponent,
            currentEntries,
            switchTab,
            getDisplayName,
            bridge, // 传递给子组件
            volume, // 顶层音量条
        };
    }
});

app.mount('#app');
