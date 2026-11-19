// StepFun StepAudio 3 TTS —— 只读音色预览组件
//
// 与 MiniMax 系列音色管理界面的「音色列表」tab 同构，但只做只读预览：
//  - 进场（或切换认证配置）各拉一次「已复刻音色」与「官方系统音色」，命中
//    useVoiceListCache 的 60s 缓存则跳过网络请求（两者 voice_type 不同，缓存键天然隔离）；
//  - 复刻音色表（GET /v1/audio/voices）置顶，只有当前账号有复刻音色时才显示，
//    列：Voice ID / 文件 ID / 创建时间 / 操作（复制 + 试听）；
//  - 系统音色表（GET /v1/audio/system_voices）列出全部字段：音色名 / Voice ID /
//    描述 / 推荐场景 / 操作；推荐场景按顿号拆成小标签，空值显示占位符；
//  - 试听复用公共 VoicePreviewModal，走 voice/preview 的 voice_id 覆盖链路；
//  - 不做复刻 / 设计 / 删除：置顶给出官方 playground 外链指引，写操作去官方操作。
//
// i18n：所有可见文案经 useComponentI18n 汇入共享命名空间 views.tts_studio.components.*。
// 复用现有键（值必须与 zh-CN.json 一致），新增 sfCloneTip / sfCloneLink / sfColScene /
// sfClonedTitle / sfColFileId / sfColCreated 六个键。
// 新增 defs 已加入 tests/i18n_components_drift.test.mjs 的 SOURCES，四语已同步。

const { ref, computed, watch, onMounted } = Vue;

import { useToast } from '../composables/useToast.js';
import { useClipboard } from '../composables/useClipboard.js';
import { useComponentI18n } from '../composables/useComponentI18n.js';
import { getVoiceList, setVoiceList } from '../composables/useVoiceListCache.js';
import VoicePreviewModal from './common/voice_preview_modal.js';

// 官方音色设计/克隆入口（本组件只做外链指引，不在插件内做写操作）
const CLONE_URL = 'https://audio.stepfun.com/playground?tab=clone';

// 共享命名空间：复用键的值必须与 zh-CN.json views.tts_studio.components 段逐字一致，
// 否则 i18n_components_drift.test.mjs 的 valueMismatch 断言会失败。
const SF_I18N_DEFS = {
    authConfig: '认证配置',
    voiceListTitle: '音色列表',
    refresh: '刷新',
    loadingList: '加载中...',
    mmColName: '名称',
    mmColDesc: '描述',
    sfColScene: '推荐场景',
    colActions: '操作',
    copyBtn: '复制',
    previewBtn: '预览',
    noVoices: '暂无音色',
    mmListFail: '获取音色列表失败: ',
    linkCopied: '链接已复制，请手动粘贴到浏览器地址栏访问',
    sfCloneTip: '需要设计或克隆新音色？',
    sfCloneLink: '前往 StepFun 官方音色工作台（点击复制链接）',
    sfClonedTitle: '我的复刻音色',
    sfColFileId: '文件 ID',
    sfColCreated: '创建时间',
};

export default {
    name: 'StepfunStepaudio3Tts',
    components: { VoicePreviewModal },
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true },
    },
    setup(props) {
        const t = useComponentI18n(props.bridge, SF_I18N_DEFS);

        const {
            toastMessage, toastVisible, toastType,
            showSuccess, showError,
            onToastMouseEnter, onToastMouseLeave,
        } = useToast();

        const { copyText, copyLink } = useClipboard(showSuccess, showError);

        // 认证配置：默认选第一个（与 MiniMax 组件一致）
        const selectedEntryId = ref(null);
        watch(() => props.entries, (newVal) => {
            if (newVal && newVal.length > 0) {
                selectedEntryId.value = newVal[0].id;
            }
        }, { immediate: true });

        // 系统音色列表 + 缓存
        const voiceList = ref([]);
        const voiceLoading = ref(false);

        // 已复刻音色列表 + 缓存（voice_type=cloned，缓存键与系统音色天然隔离）
        const clonedVoiceList = ref([]);

        // entry_id 是 providers 数组索引，第一个供应商 id=0（falsy）。
        // 判断是否已选只能用 null/undefined，不能用真值——否则单供应商时永远不加载。
        const hasEntry = () =>
            selectedEntryId.value !== null && selectedEntryId.value !== undefined;

        // force=true 强制回源（手动刷新用）；否则命中 60s 缓存直接回填，跳过网络。
        async function fetchVoiceList(force = false) {
            if (!hasEntry()) return;
            const params = { entry_id: selectedEntryId.value };
            if (!force) {
                const cached = getVoiceList(params);
                if (cached) {
                    voiceList.value = cached;
                    return;
                }
            }
            voiceLoading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/list', params);
                const items = result.items || [];
                setVoiceList(params, items);
                // await 期间切换认证配置时，用旧响应覆盖新列表（P3 防护）
                if (selectedEntryId.value === params.entry_id) {
                    voiceList.value = items;
                }
            } catch (e) {
                showError(t.mmListFail + e.message);
            } finally {
                voiceLoading.value = false;
            }
        }

        // 已复刻音色：与系统音色分表加载。失败静默置空（列表整块隐藏），
        // 不弹 toast——该区块是「有才显示」的附加信息，查询失败不应打断系统音色视图。
        async function fetchClonedVoiceList() {
            if (!hasEntry()) return;
            const params = { entry_id: selectedEntryId.value, voice_type: 'cloned' };
            const cached = getVoiceList(params);
            if (cached) {
                clonedVoiceList.value = cached;
                return;
            }
            try {
                const result = await props.bridge.apiPost('voice/list', params);
                const items = result.items || [];
                setVoiceList(params, items);
                if (selectedEntryId.value === params.entry_id) {
                    clonedVoiceList.value = items;
                }
            } catch (e) {
                clonedVoiceList.value = [];
            }
        }

        // 官方 created_at 是 unix 秒；转成可读时间，空值显示占位符
        function formatCreatedAt(ts) {
            const n = Number(ts);
            if (!Number.isFinite(n) || n <= 0) return '—';
            const d = new Date(n * 1000);
            return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
        }

        // 试听：复用公共弹层，走 voice_id 覆盖链路
        const previewModalVisible = ref(false);
        const previewVoiceId = ref('');
        function openPreview(voiceId) {
            previewVoiceId.value = voiceId;
            previewModalVisible.value = true;
        }

        // 官方 recommended_scene 用顿号分隔多个场景，拆成数组展示为小标签；
        // 空串返回空数组，模板据此显示占位符。
        function splitScenes(scene) {
            if (!scene || typeof scene !== 'string') return [];
            return scene.split(/[、,，]/).map(s => s.trim()).filter(Boolean);
        }

        // 进场 / 切换认证配置时加载一次（命中缓存则不重复请求）。
        // 必须用 hasEntry()（null/undefined 判断）：单供应商 id=0 时真值判断会漏掉。
        function loadAll() {
            if (!hasEntry()) return;
            fetchVoiceList();
            fetchClonedVoiceList();
        }
        watch(selectedEntryId, loadAll);
        onMounted(loadAll);

        return {
            t,
            toastMessage, toastVisible, toastType,
            onToastMouseEnter, onToastMouseLeave,
            selectedEntryId,
            voiceList, voiceLoading, fetchVoiceList,
            clonedVoiceList, fetchClonedVoiceList, formatCreatedAt,
            copyText, copyLink, CLONE_URL,
            previewModalVisible, previewVoiceId, openPreview, splitScenes,
        };
    },
    template: /* html */ `
    <div class="stepfun-stepaudio3-tts">
        <!-- 组件内 toast -->
        <Teleport to="body">
            <Transition name="toast">
                <div
                    v-if="toastVisible"
                    class="toast"
                    :class="{'toast-error': toastType === 'error'}"
                    @mouseenter="onToastMouseEnter"
                    @mouseleave="onToastMouseLeave"
                >{{ toastMessage }}</div>
            </Transition>
        </Teleport>

        <!-- 认证配置 -->
        <div class="form-group">
            <label>{{ t.authConfig }}</label>
            <select v-model="selectedEntryId">
                <option v-for="entry in entries" :key="entry.id" :value="entry.id">
                    {{ entry.display_name || entry.api_key }}
                </option>
            </select>
        </div>

        <!-- 设计/克隆外链指引（只读组件，写操作去官方 playground）—— 置顶，列表上方 -->
        <div style="margin:0 0 12px 0;
            padding:8px 14px;
            background:rgba(59,130,246,0.12);
            border-left:4px solid #3b82f6;
            border-radius:var(--radius);
            color:var(--text);font-size:0.85rem;line-height:1.6;">
            <span>💡</span>
            <span>{{ t.sfCloneTip }}</span>
            <a href="#" @click.prevent="copyLink(CLONE_URL, { successMsg: t.linkCopied })">{{ t.sfCloneLink }}</a>
        </div>

        <!-- 已复刻音色（有才显示，置顶于系统音色表之上） -->
        <div v-if="clonedVoiceList.length">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h3 style="margin:0;">{{ t.sfClonedTitle }}</h3>
            </div>
            <div class="sf-table-wrap">
                <table class="sf-voice-table sf-clone-table">
                    <thead>
                        <tr>
                            <th class="sf-clone-col-id">Voice ID</th>
                            <th class="sf-clone-col-file">{{ t.sfColFileId }}</th>
                            <th class="sf-clone-col-created">{{ t.sfColCreated }}</th>
                            <th class="sf-col-actions">{{ t.colActions }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in clonedVoiceList" :key="v.voice_id">
                            <td class="sf-clone-col-id"><code class="format-tag">{{ v.voice_id }}</code></td>
                            <td class="sf-clone-col-file">
                                <code v-if="v.file_id" class="format-tag">{{ v.file_id }}</code>
                                <span v-else class="sf-empty">—</span>
                            </td>
                            <td class="sf-clone-col-created">{{ formatCreatedAt(v.created_at) }}</td>
                            <td class="sf-col-actions">
                                <button class="btn btn-sm" @click="copyText(v.voice_id)">{{ t.copyBtn }}</button>
                                <button class="btn btn-sm" @click="openPreview(v.voice_id)">{{ t.previewBtn }}</button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 系统音色列表 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <h3 style="margin:0;">{{ t.voiceListTitle }}</h3>
            <button class="btn btn-sm" @click="fetchVoiceList(true)" :disabled="voiceLoading">{{ t.refresh }}</button>
        </div>
        <div v-if="voiceLoading">{{ t.loadingList }}</div>

        <div v-if="voiceList.length" class="sf-table-wrap">
            <table class="sf-voice-table">
                <thead>
                    <tr>
                        <th class="sf-col-name">{{ t.mmColName }}</th>
                        <th class="sf-col-id">Voice ID</th>
                        <th class="sf-col-desc">{{ t.mmColDesc }}</th>
                        <th class="sf-col-scene">{{ t.sfColScene }}</th>
                        <th class="sf-col-actions">{{ t.colActions }}</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="v in voiceList" :key="v.voice_id">
                        <td class="sf-col-name">
                            <span class="sf-voice-name">{{ v.voice_name || '—' }}</span>
                        </td>
                        <td class="sf-col-id">
                            <code class="format-tag">{{ v.voice_id }}</code>
                        </td>
                        <td class="sf-col-desc">
                            <span :class="{ 'sf-empty': !v.description }">{{ v.description || '—' }}</span>
                        </td>
                        <td class="sf-col-scene">
                            <span v-if="splitScenes(v.recommended_scene).length" class="sf-scenes">
                                <span v-for="(s, i) in splitScenes(v.recommended_scene)" :key="i" class="scene-tag">{{ s }}</span>
                            </span>
                            <span v-else class="sf-empty">—</span>
                        </td>
                        <td class="sf-col-actions">
                            <button class="btn btn-sm" @click="copyText(v.voice_id)">{{ t.copyBtn }}</button>
                            <button class="btn btn-sm" @click="openPreview(v.voice_id)">{{ t.previewBtn }}</button>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <div v-else-if="!voiceLoading" style="text-align:center;color:var(--gray);padding:20px 0;">
            {{ t.noVoices }}
        </div>

        <!-- 试听弹层 -->
        <VoicePreviewModal
            v-model:visible="previewModalVisible"
            :bridge="bridge"
            :entry-id="selectedEntryId"
            :voice-id="previewVoiceId"
            id-prefix="sf_preview"
        />
    </div>
    `
};
