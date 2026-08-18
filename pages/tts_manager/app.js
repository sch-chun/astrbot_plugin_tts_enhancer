import { createApp, ref, shallowRef, onMounted } from 'vue';

// 静态导入所有已知供应商组件
import BailianQwenAudio3_0 from './components/bailian_qwen_audio_3_0_tts.js';

const bridge = window.AstrBotPluginPage;

const app = createApp({
    setup() {
        const groups = ref([]);
        const currentTab = ref('');
        const currentComponent = shallowRef(null);
        const currentEntries = ref([]);
        const loading = ref(true);

        // 组件映射表（template_key → Vue 组件）
        const componentMap = {
            'bailian_qwen_audio_3_0_tts': BailianQwenAudio3_0,
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
                }
            } catch (e) {
                console.error('获取供应商列表失败:', e);
                alert('无法加载供应商配置，请检查插件是否启用并配置了 providers。\n' + e.message);
            } finally {
                loading.value = false;
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
        }

        function getDisplayName(key) {
            const map = {
                'bailian_qwen_audio_3_0_tts': '百炼 Qwen-Audio-TTS',
                // 未来扩展
            };
            return map[key] || key;
        }

        onMounted(() => {
            fetchProviders();
        });

        return {
            groups,
            currentTab,
            currentComponent,
            currentEntries,
            switchTab,
            getDisplayName,
            bridge, // 传递给子组件
        };
    }
});

app.mount('#app');
