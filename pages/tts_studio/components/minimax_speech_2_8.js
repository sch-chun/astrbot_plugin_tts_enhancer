const { ref, reactive, computed, watch, onMounted, nextTick } = Vue;


import { useToast } from '../composables/useToast.js';
import { useClipboard } from '../composables/useClipboard.js';
import { useComponentI18n } from '../composables/useComponentI18n.js';
import { useAudioManager } from '../composables/useAudioManager.js';
import { validateText, countChars } from '../composables/useTextValidator.js'
import { getVoiceList, setVoiceList } from '../composables/useVoiceListCache.js'
import { base64ToBlobUrl, hexToBlobUrl } from '../composables/useAudioManager.js';
import VoicePreviewModal from './common/voice_preview_modal.js';
import DeleteConfirmModal from './common/delete_confirm_modal.js';


const MM_I18N_DEFS = {
        "authConfig": "认证配置",
        "createVoice": "创建新音色",
        "sysVoiceList": "系统音色列表",
        "basicVoiceRef": "基础音色参考库",
        "sysVoicePrefix": "系统音色列表请参考",
        "sysVoiceSuffix": "（点击复制链接）",
        "helpDoc": "帮助文档",
        "tabClone": "📁 声音复刻",
        "tabDesign": "🎨 声音设计",
        "selectAudioFile": "选择音频文件（wav (16bit), mp3, m4a）",
        "audioHint": "推荐 10~20s，最长 60s，文件 ≤ 10MB，采样率 ≥ 16kHz。",
        "voicePromptLabel": "声音描述（自然语言）",
        "voicePromptPlaceholder": "例如：沉稳的中年男性播音员，音色低沉浑厚，富有磁性，语速平稳...",
        "voicePromptHint": "用自然语言描述期望的声音特质，支持中文和英文，不超过 500 字符（汉字按 2 字符计算）。详见",
        "voiceDesignGuide": "声音设计编写指南",
        "voicePromptHintSuffix": "（点击复制链接，请手动粘贴到浏览器地址栏打开）",
        "previewTextLabel": "预览文本",
        "previewTextPlaceholder": "输入用于试听的文本...",
        "previewTextHint": "最小 15 字符，最大 200 字符（汉字按 2 字符计算）",
        "prefixLabel": "音色前缀",
        "prefixPlaceholder": "例如：design",
        "prefixInvalid": "⚠️ 仅字母数字，长度 1~10 字符",
        "prefixFormatDesign": "生成的音色名格式：{target_model}-vd-{prefix}-{唯一标识}",
        "prefixFormatClone": "生成的音色名格式：{target_model}-{prefix}-{唯一标识}",
        "langHintLabel": "语言提示",
        "langHintDesc": "辅助模型识别语种，提升合成效果。设计模式仅支持中文和英文。",
        "volNormLabel": "启用音量归一化",
        "preprocessLabel": "启用音频预处理",
        "preprocessHint": "有背景噪音时建议开启",
        "maxAudioLenLabel": "最大提示音频时长（s）",
        "maxAudioLenInvalid": "⚠️ 请输入 3.0 ~ 30.0 之间的数值",
        "sampleRateLabel": "采样率",
        "formatLabel": "输出格式",
        "modelVersionLabel": "模型版本",
        "btnClone": "📁 复刻音色",
        "btnDesign": "🎨 设计音色",
        "cloneWait": "复刻中...",
        "designWait": "创建中...",
        "voiceListTitle": "音色列表",
        "refresh": "刷新",
        "loadingList": "加载中...",
        "colCreated": "创建时间",
        "colStatus": "状态",
        "colActions": "操作",
        "designBadge": "设计",
        "copyBtn": "复制",
        "previewBtn": "预览",
        "deleteBtn": "删除",
        "noVoices": "暂无音色",
        "previewModalTitle": "🎧 音色预览",
        "previewTextColon": "预览文本:",
        "stopBtn": "⏹ 停止",
        "auditionBtn": "▶ 试听",
        "playBtn": "▶ 播放",
        "keepBtn": "保留",
        "closeBtn": "关闭",
        "confirmDeletePreviewText": "⚠️ 确定要删除此音色吗？此操作不可恢复。",
        "cancelBtn": "取消",
        "confirmDeleteBtn": "确认删除",
        "copyIdTip": "复制 ID",
        "previewVoiceTip": "预览音色",
        "defaultPreviewText": "欢迎使用声音设计功能，让我们听听这个音色的效果。",
        "dlgTitle": "⚠️ 确认删除",
        "dlgConfirm": "确认删除",
        "dlgCancel": "取消",
        "errNoEntry": "请先选择认证配置",
        "errNoFile": "请选择音频文件",
        "phaseUpload": "上传音频中…",
        "phaseSubmitClone": "提交复刻请求…",
        "phaseSubmitDesign": "提交设计请求…",
        "phaseAuditing": "等待审核中…",
        "phaseApproved": "审核通过，可正常使用",
        "phaseRejected": "审核未通过，不可使用",
        "createdOk": "音色创建成功！Voice ID:",
        "auditRejected": "音色审核未通过，不可使用：",
        "auditTimeout": "审核超时，请稍后刷新列表查看状态：",
        "unsupportedQuery": "该供应商不支持进度查询，请稍后刷新列表",
        "cloneFail": "复刻失败:",
        "createFail": "创建失败:",
        "createVoiceFail": "创建音色失败:",
        "noAudioData": "没有可播放的音频数据",
        "playFail": "播放失败:",
        "keptOk": "音色已保留:",
        "deletedOk": "音色已删除",
        "deleteOk": "删除成功",
        "deleteFail": "删除失败:",
        "fetchListFail": "获取音色列表失败:",
        "audioOnlyExt": "仅支持 wav、mp3、m4a 音频文件",
        "audioEmpty": "音频文件不能为空",
        "audioTooLarge": "音频文件不得超过 10MB",
        "audioReadFail": "读取音频文件失败",
        "audioEncodeFail": "音频文件编码失败",
        "prefixAlnum": "prefix 必须为字母数字，长度 1-10",
        "valLabelVoicePrompt": "声音描述",
        "valLabelPreviewText": "预览文本",
        "statusDeploying": "审核中/处理中",
        "statusOk": "审核通过，可正常使用",
        "statusUndeployed": "审核未通过，不可使用",
        "langZh": "中文",
        "langEn": "英语",
        "langFr": "法语",
        "langDe": "德语",
        "langJa": "日语",
        "langKo": "韩语",
        "langRu": "俄语",
        "langPt": "葡萄牙语",
        "langTh": "泰语",
        "langId": "印尼语",
        "langVi": "越南语",
        "langEs": "西班牙语",
        "langIt": "意大利语",
        "langMs": "马来西亚语",
        "langFil": "菲律宾语",
        "langAr": "阿拉伯语",
        "previewTitle": "预览音色",
        "enhanceToggle": "调用 SubAgent 增强（可选，将消耗一次 LLM 调用）",
        "synthezing": "合成中...",
        "btnSynthesize": "合成",
        "synthedOk": "合成成功！音频时长：",
        "calcDuration": "计算中…",
        "durationSec": "秒",
        "errPreviewText": "请输入预览文本",
        "errNoAudio": "预览失败: 未返回音频数据",
        "errPreviewFail": "预览失败:",
        "copyFail": "复制失败，请手动复制",
        "linkCopied": "链接已复制，请手动粘贴到浏览器地址栏访问",
        "copiedPrefix": "已复制: ",
        "valEmpty": "不能为空",
        "valMin": "不能少于 {min} 字符（当前 {count} 字符）",
        "valMax": "不能超过 {max} 字符（当前 {count} 字符）",
        "dlgDelVoicePre": "确定要删除音色 ",
        "dlgDelVoiceSuf": " 吗？此操作不可恢复。",
        "langChineseYue": "粤语",
        "langTurkish": "土耳其语",
        "langDutch": "荷兰语",
        "langUkrainian": "乌克兰语",
        "langPolish": "波兰语",
        "langRomanian": "罗马尼亚语",
        "langGreek": "希腊语",
        "langCzech": "捷克语",
        "langFinnish": "芬兰语",
        "langHindi": "印地语",
        "langBulgarian": "保加利亚语",
        "langDanish": "丹麦语",
        "langHebrew": "希伯来语",
        "langPersian": "波斯语",
        "langSlovak": "斯洛伐克语",
        "langSwedish": "瑞典语",
        "langCroatian": "克罗地亚语",
        "langHungarian": "匈牙利语",
        "langNorwegian": "挪威语",
        "langSlovenian": "斯洛文尼亚语",
        "langCatalan": "加泰罗尼亚语",
        "langNynorsk": "挪威尼诺斯克语",
        "langTamil": "泰米尔语",
        "langAfrikaans": "南非荷兰语",
        "mmTabClone": "📁 上传复刻",
        "mmTabDesign": "🎨 声音设计",
        "mmTabList": "🗂️ 音色列表",
        "mmLegendCloneAudio": "📁 复刻音频管理",
        "mmLegendPromptAudio": "🎨 示例音频管理",
        "mmLegendCloneParams": "🔊 复刻参数",
        "mmLegendDesign": "🎨 声音设计",
        "mmUploadCloneAudio": "上传复刻音频",
        "mmCustomFileName": "自定义文件名（可选）",
        "mmUploadPromptAudio": "上传示例音频",
        "mmPromptTextPlaceholder": "输入音频对应的文字内容（必填）",
        "mmMainAudio": "主音频（必选）",
        "mmPromptAudioOpt": "示例音频（可选）",
        "mmAuditionText": "试听文本",
        "mmAuditionModel": "试听模型版本",
        "mmLangBoost": "语言增强",
        "mmAsrText": "ASR 验证文本",
        "mmAsrThreshold": "ASR 相似度阈值",
        "mmNoiseReduction": "降噪",
        "mmVolNorm": "音量归一化",
        "mmAigcWatermark": "AIGC 水印",
        "mmUploadBtn": "上传",
        "mmUploading": "上传中...",
        "mmSelected": "✓ 已选",
        "mmSelect": "选择",
        "mmSave": "保存",
        "mmEdit": "编辑",
        "mmCloneBtn": "复刻音色",
        "mmCloning": "复刻中...",
        "mmDesignBtn": "设计音色",
        "mmDesigning": "设计中...",
        "mmPreviewActivate": "预览（激活）",
        "mmColFilename": "文件名",
        "mmColSize": "大小",
        "mmColSourceText": "源文本",
        "mmColType": "类型",
        "mmColDesc": "描述",
        "mmColName": "名称",
        "mmHintCloneAudio": "格式 mp3/m4a/wav，时长 10s ~ 5min，大小 ≤ 20MB",
        "mmHintPromptAudio": "可选，增强相似度。示例音频时长 < 8s，格式同主音频，上传时需填写对应的源文本",
        "mmHintVoiceId": "长度 8-256，首字母必须为英文字母，允许数字、字母、- 和 _，末位字符不可为 - 或 _，不可与已有 ID 重复",
        "mmHintAuditionText": "提供后模型将使用复刻后的音色朗读本段文本内容。试听将根据字符数正常收取语音合成费用，定价与 T2A 各接口一致",
        "mmHintLangBoost": "增强对指定的小语种和方言的识别能力。一般设置为 auto 让模型自主判断",
        "mmHintAsrText": "可选。音频复刻样本（file_id 或 clone_prompt.prompt_audio 中的音频）的预期文本内容。提供后，服务会对该音频做 ASR 识别，并将识别文本与该文本做相似度比对；若相似度低于 accuracy，请求会被拒绝",
        "mmHintAsrThreshold": "可选。配合 ASR 验证文本使用的 ASR 相似度阈值，取值范围 [0, 1]，默认 0.7",
        "mmHintAigc": "是否在合成试听音频的末尾添加音频节奏标识",
        "mmEmptyCloneAudio": "暂无复刻音频",
        "mmEmptyPromptAudio": "暂无示例音频",
        "mmNoticeTitle": "重要：音色复刻与音色设计产出的均为临时（未激活）音色",
        "mmNotice1": "9.9 元音色激活费用在首次用于语音合成时才收取（不含接口内试听）",
        "mmNotice2": "若 168h（7 天）内未在任意语音合成接口中使用，该音色将被删除",
        "mmNotice3": "本界面音色列表中的预览功能会调用一次语音合成，因此需要的音色可通过预览一次保留，不想要的音色请勿点击预览避免扣费",
        "mmPricingDoc": "MiniMax 语音定价文档",
        "mmCloneOkTitle": "✅ 复刻成功",
        "mmDesignOkTitle": "✅ 设计成功",
        "mmUnactivatedNote": "音色当前处于未激活状态，需要在语音合成接口中正式调用一次方可激活。",
        "mmUnactivatedBanner": "这些音色尚未激活，点击“预览（激活）”可调用一次语音合成激活音色，激活后音色将出现在自定义音色列表中，并扣取相应费用。",
        "mmUnactivatedHeading": "⏳ 未激活音色",
        "mmCustomHeading": "🧑‍🎨 自定义音色",
        "mmSystemHeading": "🎙️ 系统音色",
        "mmNoDemo": "没有试听音频",
        "mmUploadFail": "上传失败: ",
        "mmFetchListFail": "获取{label}列表失败: ",
        "mmDeleteConfirmMsg": "确定删除{label} {fileId} 吗？",
        "mmCloneAudioUploaded": "复刻音频上传成功",
        "mmPromptTextRequired": "请输入源文本（音频对应的文字内容）",
        "mmPromptAudioUploaded": "示例音频上传成功",
        "mmPromptTextEmpty": "源文本不能为空",
        "mmSaveFail": "保存失败: ",
        "mmPromptSaved": "源文本已保存",
        "mmFetchAudioFail": "获取音频失败: ",
        "mmSelectMainAudio": "请选择一个主音频（复刻音频）",
        "mmPromptNoText": "所选示例音频缺少源文本，请先绑定",
        "mmCloneSuccess": "音色克隆成功！Voice ID: ",
        "mmCloneFail": "克隆失败: ",
        "mmDesignSuccess": "音色设计成功！Voice ID: ",
        "mmDesignFail": "设计失败: ",
        "mmListFail": "获取音色列表失败: ",
        "mmUnactivatedNotFound": "未找到该未激活音色",
        "mmUnactivatedDeleted": "已删除未激活音色",
        "mmKeptUnactivated": "音色已保留到未激活列表，请通过预览激活",
        "blmmTabUpload": "📁 上传音频文件",
        "blmmTabUrl": "🔗 使用音频 URL",
        "blmmTabList": "📋 音色列表",
        "blmmCreateLegend": "创建新音色（声音克隆）",
        "blmmTip": "💡 提示：",
        "blmmNotice": "首次使用复刻音色进行语音合成时将激活并扣除 9.9 元解锁费。",
        "blmmPricingDoc": "模型调用价格",
        "blmmSelectLocal": "选择本地音频文件（wav, mp3, m4a）",
        "blmmSelectedPrefix": "✅ 已选择: ",
        "blmmClear": "清除",
        "blmmHintLocalAudio": "时长最少应不低于 10s，最长应不超过 5 分钟；格式需为：mp3、m4a、wav；大小需不超过 20MB",
        "blmmCustomId": "自定义音色 ID（可选）",
        "blmmPlaceholderAuto": "留空则自动生成",
        "blmmAuditionPlaceholder": "请输入试听文本，最多 1000 字符...",
        "blmmHintAudition": "试听将根据字符数正常收取语音合成费用，限制 1000 字符",
        "blmmModelVersion": "模型版本",
        "blmmHintLangBoost": "增强对指定语种的识别能力，一般设置为 auto",
        "blmmNoiseReduction": "开启降噪",
        "blmmNoiseHint": "有背景噪音时建议开启",
        "blmmPromptAudio": "示例音频（可选，增强相似度）",
        "blmmHintPrompt": "可选，时长 < 8s，文件 ≤ 20MB。提供示例音频可增强音色相似度",
        "blmmPromptTextLabel": "示例音频文本",
        "blmmPromptPlaceholder": "请输入示例音频对应的文本内容",
        "blmmHintPromptText": "示例音频对应的文本内容，需与音频内容一致",
        "blmmCloneBtn": "📁 上传并克隆",
        "blmmCloning": "克隆中...",
        "blmmUrlCloneBtn": "🔗 使用 URL 克隆",
        "blmmPublicUrl": "公网音频 URL",
        "blmmHintUrl": "音频文件的可访问 URL，支持 WAV/MP3/M4A 格式",
        "blmmConfigPrefix": "配置 #",
        "blmmClonedHeading": "🎤 复刻音色",
        "blmmUnactivatedBanner": "这些音色尚未激活，点击“预览（激活）”可调用一次语音合成激活音色，激活后音色将出现在复刻音色列表中，并扣取相应费用。",
        "blmmCloneOkTitle": "✅ 克隆成功",
        "blmmAudioFormat": "不支持的音频格式，请选择 WAV/MP3/M4A 文件",
        "blmmAudioTooLarge": "音频文件过大，请选择 10MB 以内的文件",
        "blmmReadFail": "读取文件失败",
        "blmmReadPromptFail": "读取示例音频失败",
        "blmmListFail": "获取音色列表失败: ",
        "blmmDeleteMsg": "确定删除音色 {voiceId} 吗？此操作不可撤销。",
        "blmmSelectOrUrl": "请选择音频文件或输入音频 URL",
        "blmmEnterAudition": "请输入试听文本",
        "blmmPromptTextRequired": "请填写示例音频对应的文本内容",
        "blmmDeleteUnactivatedMsg": "确定删除未激活音色 {voiceId} 吗？此操作将同时从百炼服务端删除该音色，不可恢复。",
        "mmDesignDefaultPreview": "欢迎使用 MiniMax 声音设计功能。",
        "mmUnbound": "未绑定",
        "mmPleaseSelect": "-- 请选择 --",
        "mmPleaseSelectNone": "-- 不使用 --",
        "mmPlaceholderAuto": "建议自定义，留空自动生成",
        "mmAuditionPlaceholder": "可选。≤ 1000 字",
        "mmAsrPlaceholder": "预期音频内容，≤ 200 字",
        "mmPlayDemo": "▶ 播放试听音频",
        "mmVoiceDesc": "音色描述",
        "mmVoiceDescPlaceholder": "例如：温柔的女声，略带磁性，适合朗读抒情散文...",
        "mmPreviewTextLabel": "预览文本",
        "mmPreviewTextPlaceholder": "输入用于试听的文本。≤ 500 字符",
        "mmHintPreviewText": "最大 500 字符 (汉字按 2 字符计算)；试听音频的合成将收取 2 元/万字符的费用",
        "mmCannotBeEmpty": "{label}不能为空",
        "mmCannotBeLess": "{label}不能少于 {min} 字符（当前 {count} 字符）",
        "mmCannotExceed": "{label}不能超过 {max} 字符（当前 {count} 字符）",
        "mmVidErrLen": "长度必须为 8~256 字符",
        "mmVidErrFirst": "首字符必须为英文字母",
        "mmVidErrChars": "仅允许字母、数字、-、_",
        "mmVidErrLast": "末位字符不可为 - 或 _",
        "mmUnknownError": "未知错误",
        "mmDeleteVoiceMsg": "确定删除音色 {voiceId} 吗？",
        "mmDeleteUnactivatedMsg": "确定删除未激活音色 {voiceId} 吗？此操作将同时从 MiniMax 服务端删除该音色，不可恢复。",
        "mmCloneAudioLabel": "复刻音频",
        "mmPromptAudioLabel": "示例音频",
        "mmSelectFile": "请选择一个文件",
        "mmNoAudioData": "未获取到音频数据",
        "langAuto": "auto（自动）",
        "mmSeeDetails": "详见："
    };

const MM_LANG_BOOST = [
    { value: "auto", langKey: "langAuto" },
    { value: "Chinese", langKey: "langZh" },
    { value: "Chinese,Yue", langKey: "langChineseYue" },
    { value: "English", langKey: "langEn" },
    { value: "Arabic", langKey: "langAr" },
    { value: "Russian", langKey: "langRu" },
    { value: "Spanish", langKey: "langEs" },
    { value: "French", langKey: "langFr" },
    { value: "Portuguese", langKey: "langPt" },
    { value: "German", langKey: "langDe" },
    { value: "Turkish", langKey: "langTurkish" },
    { value: "Dutch", langKey: "langDutch" },
    { value: "Ukrainian", langKey: "langUkrainian" },
    { value: "Vietnamese", langKey: "langVi" },
    { value: "Indonesian", langKey: "langId" },
    { value: "Japanese", langKey: "langJa" },
    { value: "Italian", langKey: "langIt" },
    { value: "Korean", langKey: "langKo" },
    { value: "Thai", langKey: "langTh" },
    { value: "Polish", langKey: "langPolish" },
    { value: "Romanian", langKey: "langRomanian" },
    { value: "Greek", langKey: "langGreek" },
    { value: "Czech", langKey: "langCzech" },
    { value: "Finnish", langKey: "langFinnish" },
    { value: "Hindi", langKey: "langHindi" },
    { value: "Bulgarian", langKey: "langBulgarian" },
    { value: "Danish", langKey: "langDanish" },
    { value: "Hebrew", langKey: "langHebrew" },
    { value: "Malay", langKey: "langMs" },
    { value: "Persian", langKey: "langPersian" },
    { value: "Slovak", langKey: "langSlovak" },
    { value: "Swedish", langKey: "langSwedish" },
    { value: "Croatian", langKey: "langCroatian" },
    { value: "Filipino", langKey: "langFil" },
    { value: "Hungarian", langKey: "langHungarian" },
    { value: "Norwegian", langKey: "langNorwegian" },
    { value: "Slovenian", langKey: "langSlovenian" },
    { value: "Catalan", langKey: "langCatalan" },
    { value: "Nynorsk", langKey: "langNynorsk" },
    { value: "Tamil", langKey: "langTamil" },
    { value: "Afrikaans", langKey: "langAfrikaans" }
];

export default {
    name: 'MinimaxSpeech2_8',
    components: { VoicePreviewModal, DeleteConfirmModal },
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true }
    },
    setup(props) {

        // ---------- i18n ----------
        const t = useComponentI18n(props.bridge, MM_I18N_DEFS, 'views.tts_studio.components');
        const MM_MSG = {
            empty: (l) => t.mmCannotBeEmpty.replace('{label}', l),
            min: (l, m, c) => t.mmCannotBeLess.replace('{label}', l).replace('{min}', m).replace('{count}', c),
            max: (l, m, c) => t.mmCannotExceed.replace('{label}', l).replace('{max}', m).replace('{count}', c),
        };
        const languageBoostOptions = computed(() => MM_LANG_BOOST.map(o => ({ value: o.value, label: t[o.langKey] })));


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
                onError: (e) => showError(t.playFail + e.message),
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

        // ---------- 供应商文件通用操作（复刻/示例音频共用） ----------
        // 上传到本地 → 转发给供应商 /file/upload；校验结果与成功后行为通过参数注入
        async function uploadProviderFile({ inputRef, uploadingRef, filenameRef, purpose, validate, onSuccess }) {
            const input = inputRef.value;
            if (!input || !input.files || !input.files[0]) {
                showError(t.mmSelectFile);
                return;
            }
            const file = input.files[0];
            if (!selectedEntryId.value) {
                showError(t.errNoEntry);
                return;
            }

            let validated = null;
            if (validate) {
                validated = await validate(file);
                if (!validated) return;
            }

            uploadingRef.value = true;
            try {
                // 1. 上传到本地
                const uploadResult = await props.bridge.upload('upload', file);
                if (!uploadResult.file_id) {
                    showError(t.mmUploadFail + (uploadResult.message || uploadResult.error || t.mmUnknownError));
                    return;
                }

                // 2. 调用 /file/upload 传递给供应商
                const payload = {
                    entry_id: selectedEntryId.value,
                    file_id: uploadResult.file_id,
                    purpose,
                };
                const customName = filenameRef ? filenameRef.value.trim() : '';
                if (customName) {
                    payload.filename = customName;
                }

                const result = await props.bridge.apiPost('file/upload', payload);
                if (result.file_id) {
                    if (onSuccess) await onSuccess(result.file_id, input, validated);
                } else {
                    showError(t.mmUploadFail + (result.message || result.error || t.mmUnknownError));
                }
            } catch (e) {
                showError(t.mmUploadFail + e.message);
            } finally {
                uploadingRef.value = false;
            }
        }

        // 拉取供应商某类目的文件列表；onLoaded 可做额外处理（如加载 KV 源文本）
        async function fetchProviderFiles({ purpose, filesRef, loadingRef, label, onLoaded }) {
            if (!selectedEntryId.value) return;
            loadingRef.value = true;
            try {
                const result = await props.bridge.apiPost('file/list', {
                    entry_id: selectedEntryId.value,
                    purpose,
                });
                const files = result.files || [];
                filesRef.value = files;
                if (onLoaded) await onLoaded(files);
            } catch (e) {
                showError(t.mmFetchListFail.replace('{label}', label) + e.message);
            } finally {
                loadingRef.value = false;
            }
        }

        // 删除供应商某类目的文件；onSuccess 负责删除后的收尾与刷新
        function deleteProviderFile({ purpose, fileId, label, onSuccess }) {
            showDeleteConfirm(
                t.dlgTitle,
                t.mmDeleteConfirmMsg.replace('{label}', label).replace('{fileId}', fileId),
                async () => {
                    await props.bridge.apiPost('file/delete', {
                        entry_id: selectedEntryId.value,
                        file_id: fileId,
                        purpose,
                    });
                    if (onSuccess) await onSuccess(fileId);
                }
            );
        }

        async function handleCloneUpload() {
            await uploadProviderFile({
                inputRef: cloneFileInput,
                uploadingRef: cloneUploading,
                filenameRef: cloneCustomFileName,
                purpose: 'voice_clone',
                onSuccess: async (_fileId, input) => {
                    showSuccess(t.mmCloneAudioUploaded);
                    cloneCustomFileName.value = '';
                    input.value = '';
                    await fetchCloneFiles();
                },
            });
        }

        async function fetchCloneFiles() {
            await fetchProviderFiles({
                purpose: 'voice_clone',
                filesRef: cloneFiles,
                loadingRef: cloneLoading,
                label: t.mmCloneAudioLabel,
            });
        }

        function deleteCloneFile(fileId) {
            deleteProviderFile({
                purpose: 'voice_clone',
                fileId,
                label: t.mmCloneAudioLabel,
                onSuccess: async (fileId) => {
                    showSuccess(t.deleteOk);
                    if (selectedCloneFileId.value === fileId) {
                        selectedCloneFileId.value = null;
                    }
                    await fetchCloneFiles();
                },
            });
        }

        async function handlePromptUpload() {
            await uploadProviderFile({
                inputRef: promptFileInput,
                uploadingRef: promptUploading,
                filenameRef: promptCustomFileName,
                purpose: 'prompt_audio',
                validate: () => {
                    const text = promptTextInput.value.trim();
                    if (!text) {
                        showError(t.mmPromptTextRequired);
                        return null;
                    }
                    return text;
                },
                onSuccess: async (fileId, input, text) => {
                    await props.bridge.apiPost('kv/set', {
                        key: `minimax_prompt_${fileId}`,
                        value: text,
                    });
                    showSuccess(t.mmPromptAudioUploaded);
                    promptTextInput.value = '';
                    promptCustomFileName.value = '';
                    input.value = '';
                    await fetchPromptFiles();
                },
            });
        }

        async function fetchPromptFiles() {
            await fetchProviderFiles({
                purpose: 'prompt_audio',
                filesRef: promptFiles,
                loadingRef: promptLoading,
                label: t.mmPromptAudioLabel,
                onLoaded: async (files) => {
                    for (const f of files) {
                        const fileId = f.file_id;
                        if (!(fileId in promptTexts)) {
                            const kv = await props.bridge.apiPost('kv/get', {
                                key: `minimax_prompt_${fileId}`
                            });
                            promptTexts[fileId] = kv.value || '';
                        }
                    }
                },
            });
        }

        async function savePromptText(fileId) {
            const text = promptTexts[fileId] || '';
            if (!text.trim()) {
                showError(t.mmPromptTextEmpty);
                return;
            }
            try {
                await props.bridge.apiPost('kv/set', {
                    key: `minimax_prompt_${fileId}`,
                    value: text
                });
                showSuccess(t.mmPromptSaved);
                editingPrompt.value = null;
            } catch (e) {
                showError(t.mmSaveFail + e.message);
            }
        }

        async function deletePromptFile(fileId) {
            deleteProviderFile({
                purpose: 'prompt_audio',
                fileId,
                label: t.mmPromptAudioLabel,
                onSuccess: async (fileId) => {
                    await props.bridge.apiPost('kv/delete', {
                        key: `minimax_prompt_${fileId}`
                    });
                    delete promptTexts[fileId];
                    showSuccess(t.deleteOk);
                    await fetchPromptFiles();
                },
            });
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
                    const url = base64ToBlobUrl(result.audio_base64, 'audio/mp3');
                    playAudio(url, buttonId, () => URL.revokeObjectURL(url));
                } else {
                    showError(t.mmNoAudioData);
                }
            } catch (e) {
                showError(t.mmFetchAudioFail + e.message);
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
                showError(t.errNoEntry);
                return;
            }
            if (!selectedCloneFileId.value) {
                showError(t.mmSelectMainAudio);
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
                    showError(t.mmPromptNoText);
                    return;
                }
                payload.prompt_file_id = selectedPromptFileId.value;
                payload.prompt_text = promptText;
            }
            cloning.value = true;
            try {
                const result = await props.bridge.apiPost('voice/create', payload);
                if (result.voice_id) {
                    showSuccess(t.mmCloneSuccess + result.voice_id);

                    // 如果有试听音频，打开模态框
                    if (result.demo_audio) {
                        cloneResult.value = result;
                        cloneResultModalVisible.value = true;
                    } else {

                    // 无试听，直接刷新音色列表
                    await fetchVoiceList(true);
                    }
                } else {
                    showError(t.mmCloneFail + (result.message || result.error || t.mmUnknownError));
                }
            } catch (e) {
                showError(t.mmCloneFail + e.message);
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
            fetchVoiceList(true);  // 刷新音色列表
        }

        function playDemoAudio() {
            if (cloneResult.value && cloneResult.value.demo_audio) {
                playAudio(cloneResult.value.demo_audio, 'demo_audio');
            } else {
                showError(t.mmNoDemo);
            }
        }

        // ---------- 声音设计 ----------
        const designForm = reactive({
            prompt: '',
            preview_text: t.mmDesignDefaultPreview,
            voice_id: '',
            aigc_watermark: false,
        });
        const designing = ref(false);
        const designResultModalVisible = ref(false);
        const designResult = ref(null);

        async function performDesign() {
            if (!selectedEntryId.value) {
                showError(t.errNoEntry);
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
                    showSuccess(t.mmDesignSuccess + result.voice_id);
                    if (result.trial_audio) {
                        designResult.value = result;
                        designResultModalVisible.value = true;
                    } else {
                        await fetchVoiceList(true);
                    }
                } else {
                    showError(t.mmDesignFail + (result.message || result.error || t.mmUnknownError));
                }
            } catch (e) {
                showError(t.mmDesignFail + e.message);
            } finally {
                designing.value = false;
            }
        }

        function closeDesignResult() {
            designResultModalVisible.value = false;
            designResult.value = null;
            fetchVoiceList(true);
        }

        function playTrialAudio() {
            if (designResult.value && designResult.value.trial_audio) {
                const hex = designResult.value.trial_audio;
                const url = hexToBlobUrl(hex, 'audio/mp3');
                playAudio(url, 'trial_audio', () => URL.revokeObjectURL(url));
            } else {
                showError(t.mmNoDemo);
            }
        }

        // ---------- 音色列表 ----------
        const voiceList = ref([]);
        const voiceLoading = ref(false);
        const voiceListRefresh = ref(0);

        // 把「已出现在自定义列表中的未激活音色」从本地未激活清单移除，避免两处重复显示。
        // 命中缓存与回源两条路径都调用，确保切 tab 不复请求时未激活区块也保持同步（P2）。
        async function syncUnactivated(items) {
            const activeVoiceIds = new Set((items || []).map(v => v.voice_id));
            const toRemove = unactivatedVoices.value.filter(v => activeVoiceIds.has(v.voice_id));
            if (toRemove.length === 0) return;
            const remaining = unactivatedVoices.value.filter(v => !activeVoiceIds.has(v.voice_id));
            await saveUnactivatedVoices(remaining);
        }

        // force=true 时绕过缓存、强制回源（用于创建 / 删除 / 预览激活 / 手动刷新等操作后的刷新）；
        // 回源成功后自动覆盖缓存（非终态内部跳过）。切换标签页 / 视图导致的重新挂载默认走缓存，避免重复加载。
        async function fetchVoiceList(force = false) {
            if (!selectedEntryId.value) return;
            const params = { entry_id: selectedEntryId.value, voice_type: 'all' };
            if (!force) {
                const cached = getVoiceList(params);
                if (cached) {
                    voiceList.value = cached; // 副本，组件 mutate 不污染缓存
                    await syncUnactivated(cached);
                    return;
                }
            }
            voiceLoading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/list', params);

                // 后端 list_voice 返回 items 和 total，但 MiniMax 适配器 list_voice 返回包含 items
                const items = result.items || [];
                setVoiceList(params, items); // 非终态内部跳过，不写缓存

                // 回填前校验 entry：await 期间切供应商会被旧响应覆盖（P3）
                if (selectedEntryId.value === params.entry_id) {
                    voiceList.value = items;
                }
                await syncUnactivated(items);
            } catch (e) {
                showError(t.mmListFail + e.message);
            } finally {
                voiceLoading.value = false;
            }
        }

        // 删除音色
        async function deleteVoice(voiceId, voiceType) {
            showDeleteConfirm(
                t.dlgTitle,
                t.mmDeleteVoiceMsg.replace('{voiceId}', voiceId),
                async () => {
                    await props.bridge.apiPost('voice/delete', {
                        entry_id: selectedEntryId.value,
                        voice_id: voiceId,
                        voice_type: voiceType
                    });
                    showSuccess(t.deleteOk);
                    await fetchVoiceList(true);
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
                await fetchVoiceList(true);
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
            title: t.dlgTitle,
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
            if (id.length < 8 || id.length > 256) return t.mmVidErrLen;
            if (!/^[A-Za-z]/.test(id)) return t.mmVidErrFirst;
            if (!/^[A-Za-z0-9\-_]+$/.test(id)) return t.mmVidErrChars;
            if (/[-_]$/.test(id)) return t.mmVidErrLast;
            return '';
        });

        const isVoiceIdValid = computed(() => {
            if (!cloneParams.voice_id.trim()) return true;
            return !voiceIdError.value;
        });

        const textError = computed(() => validateText(cloneParams.text, {
            label: t.mmAuditionText,
            max: 1000,
            messages: MM_MSG,
        }).error);

        const textValidationError = computed(() => validateText(cloneParams.text_validation, {
            label: t.mmAsrText,
            max: 200,
            messages: MM_MSG,
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
            label: t.mmVoiceDesc,
            required: true,
            messages: MM_MSG,
        }).error);

        const designTextError = computed(() => validateText(designForm.preview_text, {
            label: t.mmPreviewTextLabel,
            max: 500,
            required: true,
            messages: MM_MSG,
        }).error);

        const designVoiceIdError = computed(() => {
            const id = designForm.voice_id.trim();
            if (!id) return '';
            if (id.length < 8 || id.length > 256) return t.mmVidErrLen;
            if (!/^[A-Za-z]/.test(id)) return t.mmVidErrFirst;
            if (!/^[A-Za-z0-9\-_]+$/.test(id)) return t.mmVidErrChars;
            if (/[-_]$/.test(id)) return t.mmVidErrLast;
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
            showError(t.mmUnactivatedNotFound);
            return;
        }
        const voiceType = entry.type || 'voice_cloning';
        showDeleteConfirm(
            t.dlgTitle,
            t.mmDeleteUnactivatedMsg.replace('{voiceId}', voiceId),
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
                    showSuccess(t.mmUnactivatedDeleted);

                    // 如果是复刻或设计结果模态框，关闭它们
                    if (cloneResultModalVisible.value) {
                        closeCloneResult();
                    }
                    if (designResultModalVisible.value) {
                        closeDesignResult();
                    }
                } catch (e) {
                    showError(t.deleteFail + e.message);
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
            showSuccess(t.mmKeptUnactivated);
            if (type === 'voice_cloning') {
                closeCloneResult();
            } else {
                closeDesignResult();
            }
        }

        // 返回所有响应式数据和方法
        return {

            // i18n
            t,
            languageBoostOptions,

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

        <Teleport to="body">
            <!-- Toast -->
            <Transition name="toast">
                <div
                    v-if="toastVisible"
                    class="toast"
                    :class="{'toast-error': toastType === 'error'}"
                    @mouseenter="onToastMouseEnter"
                    @mouseleave="onToastMouseLeave"
                >
                    {{ toastMessage }}
                </div>
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
                    <strong>{{ t.mmNoticeTitle }}</strong>
                    <ul style="margin: 4px 0 0 0; padding-left: 20px; color: var(--text);">
                        <li>{{ t.mmNotice1 }}</li>
                        <li>{{ t.mmNotice2 }}</li>
                        <li>{{ t.mmNotice3 }}</li>
                        <li>
                            {{ t.mmSeeDetails }}<span class="link-copy"
                                @click="copyLink(
                                    'https://platform.minimaxi.com/docs/guides/pricing-paygo#%E8%AF%AD%E9%9F%B3'
                                )"
                                style="color:var(--primary);cursor:pointer;text-decoration:underline;"
                            >{{ t.mmPricingDoc }}</span>{{ t.sysVoiceSuffix }}
                        </li>
                    </ul>
                </div>
            </div>
        </div>

        <!-- 选项卡 -->
        <div class="tabs" style="border-bottom:2px solid var(--border);margin:12px 0;">
            <button class="tab" data-label="{{ t.mmTabClone }}" :class="{ active: currentTab === 'clone' }" @click="currentTab = 'clone'">📁 {{ t.mmTabClone }}
            </button>
            <button class="tab" data-label="{{ t.mmTabDesign }}" :class="{ active: currentTab === 'design' }" @click="currentTab = 'design'">🎨 {{ t.mmTabDesign }}
            </button>
            <button class="tab" data-label="{{ t.mmTabList }}" :class="{ active: currentTab === 'list' }" @click="currentTab = 'list'">🗂️ {{ t.mmTabList }}
            </button>
        </div>

        <!-- ========== 复刻选项卡 ========== -->
        <div v-if="currentTab === 'clone'">
            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>📁 {{ t.mmLegendCloneAudio }}</legend>
                <div class="form-group">
                    <label>{{ t.mmUploadCloneAudio }}</label>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                        <input
                            type="file" ref="cloneFileInput" accept=".mp3,.m4a,.wav" style="flex:1;min-width:150px;"
                        />
                        <input
                            v-model="cloneCustomFileName" placeholder="{{ t.mmCustomFileName }}"
                            style="flex:1;min-width:120px;"
                        />
                        <button
                            class="btn" @click="handleCloneUpload" :disabled="!isCloneUploadEnabled || cloneUploading"
                        >{{ cloneUploading ? t.mmUploading : t.mmUploadBtn }}</button>
                    </div>
                    <div class="hint">{{ t.mmHintCloneAudio }}</div>
                </div>
                <div v-if="cloneLoading">{{ t.loadingList }}</div>
                <table v-else>
                    <thead><tr><th>File ID</th><th>{{ t.mmColFilename }}</th><th>{{ t.mmColSize }}</th><th>{{ t.colCreated }}</th><th>{{ t.colActions }}</th></tr></thead>
                    <tbody>
                        <tr v-for="f in cloneFiles" :key="f.file_id">
                            <td>{{ f.file_id }}</td>
                            <td>{{ f.filename }}</td>
                            <td>{{ (f.bytes / 1024).toFixed(1) }} KB</td>
                            <td>{{ new Date(f.created_at * 1000).toLocaleString() }}</td>
                            <td>
                                <button class="btn btn-sm" @click="playFile(f.file_id)"
                                    :class="{'btn-danger': currentPlayingId === 'file_' + f.file_id}">
                                    {{ currentPlayingId === 'file_' + f.file_id ? t.stopBtn : t.playBtn }}
                                </button>
                                <button class="btn btn-sm"
                                    @click="selectedCloneFileId = f.file_id"
                                    :style="{
                                        background: selectedCloneFileId === f.file_id ? 'var(--success)' : 'var(--gray)'
                                    }"
                                >
                                    {{ selectedCloneFileId === f.file_id ? t.mmSelected : t.mmSelect }}
                                </button>
                                <button class="btn btn-danger btn-sm" @click="deleteCloneFile(f.file_id)">{{ t.deleteBtn }}</button>
                            </td>
                        </tr>
                        <tr v-if="!cloneFiles.length">
                            <td colspan="5" style="text-align:center;color:var(--gray);">{{ t.mmEmptyCloneAudio }}</td>
                        </tr>
                    </tbody>
                </table>
            </fieldset>

            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>🎤 {{ t.mmLegendPromptAudio }}</legend>
                <div class="form-group">
                    <label>{{ t.mmUploadPromptAudio }}</label>

                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
                        <input
                            type="file" ref="promptFileInput" accept=".mp3,.m4a,.wav" style="flex:1;min-width:150px;"
                        />
                        <input 
                            v-model="promptCustomFileName"
                            placeholder="{{ t.mmCustomFileName }}"
                            style="flex:1;min-width:120px;"
                        />
                    </div>

                    <div style="display:flex;gap:8px;align-items:flex-start;">
                        <textarea
                            v-model="promptTextInput"
                            placeholder="{{ t.mmPromptTextPlaceholder }}"
                            rows="2" style="flex:1;min-width:150px;"
                        ></textarea>
                        <button
                            class="btn" @click="handlePromptUpload"
                            :disabled="!isPromptUploadEnabled || promptUploading"
                        >{{ promptUploading ? t.mmUploading : t.mmUploadBtn }}</button>
                    </div>
                    <div class="hint">{{ t.mmHintPromptAudio }}</div>
                </div>
                <div v-if="promptLoading">{{ t.loadingList }}</div>
                <table v-else>
                    <thead><tr><th>File ID</th><th>{{ t.mmColFilename }}</th><th>{{ t.mmColSourceText }}</th><th>{{ t.colActions }}</th></tr></thead>
                    <tbody>
                        <tr v-for="f in promptFiles" :key="f.file_id">
                            <td>{{ f.file_id }}</td>
                            <td>{{ f.filename }}</td>
                            <td>
                                <div v-if="editingPrompt === f.file_id">
                                    <textarea v-model="promptTexts[f.file_id]" rows="2" style="width:100%;"></textarea>
                                    <button class="btn btn-sm" @click="savePromptText(f.file_id)">{{ t.mmSave }}</button>
                                    <button class="btn btn-sm btn-secondary" @click="editingPrompt = null">{{ t.cancelBtn }}</button>
                                </div>
                                <div v-else>
                                    <span v-if="isPromptBindable(f.file_id)">{{ promptTexts[f.file_id] }}</span>
                                    <span v-else style="color:var(--danger);">{{ t.mmUnbound }}</span>
                                    <button class="btn btn-sm" @click="editingPrompt = f.file_id">{{ t.mmEdit }}</button>
                                </div>
                            </td>
                            <td>
                                <button class="btn btn-sm" @click="playFile(f.file_id)"
                                    :class="{'btn-danger': currentPlayingId === 'file_' + f.file_id}">
                                    {{ currentPlayingId === 'file_' + f.file_id ? t.stopBtn : t.playBtn }}
                                </button>
                                <button class="btn btn-sm"
                                    :disabled="!isPromptBindable(f.file_id)"
                                    @click="selectedPromptFileId = f.file_id"
                                    :style="{
                                        background: selectedPromptFileId === f.file_id ? 'var(--success)' : 'var(--gray)'
                                    }"
                                >
                                    {{ selectedPromptFileId === f.file_id ? t.mmSelected : t.mmSelect }}
                                </button>
                                <button class="btn btn-danger btn-sm" @click="deletePromptFile(f.file_id)">{{ t.deleteBtn }}</button>
                            </td>
                        </tr>
                        <tr v-if="!promptFiles.length">
                            <td colspan="4" style="text-align:center;color:var(--gray);">{{ t.mmEmptyPromptAudio }}</td>
                        </tr>
                    </tbody>
                </table>
            </fieldset>

            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>🔊 {{ t.mmLegendCloneParams }}</legend>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div class="form-group">
                        <label>{{ t.mmMainAudio }}</label>
                        <select v-model="selectedCloneFileId">
                            <option value="">{{ t.mmPleaseSelect }}</option>
                            <option v-for="f in cloneFiles" :key="f.file_id" :value="f.file_id">
                                {{ f.file_id }} - {{ f.filename }}
                            </option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>{{ t.mmPromptAudioOpt }}</label>
                        <select v-model="selectedPromptFileId">
                            <option value="">{{ t.mmPleaseSelectNone }}</option>
                            <option v-for="f in bindablePrompts" :key="f.file_id" :value="f.file_id">
                                {{ f.file_id }} - {{ promptTexts[f.file_id] }}
                            </option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Voice ID</label>
                        <input v-model="cloneParams.voice_id" placeholder="{{ t.mmPlaceholderAuto }}"
                            :class="{'input-error': voiceIdError}" />
                        <div v-if="voiceIdError" class="error-hint">⚠️ {{ voiceIdError }}</div>
                        <div class="hint">{{ t.mmHintVoiceId }}</div>
                    </div>
                    <div class="form-group">
                        <label>{{ t.mmAuditionText }}</label>
                        <input v-model="cloneParams.text" placeholder="{{ t.mmAuditionPlaceholder }}"
                            :class="{'input-error': textError}" />
                        <div v-if="textError" class="error-hint">⚠️ {{ textError }}</div>
                        <div class="hint">{{ t.mmHintAuditionText }}</div>
                    </div>
                    <div
                        v-if="cloneParams.text && cloneParams.text.trim()"
                        style="grid-column: 1 / -1; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;"
                    >
                        <div class="form-group">
                            <label>{{ t.mmAuditionModel }}</label>
                            <select v-model="cloneParams.model">
                                <option value="HD">HD</option>
                                <option value="Turbo">Turbo</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>{{ t.mmLangBoost }}</label>
                            <select v-model="cloneParams.language_boost">
                            <option v-for="opt in languageBoostOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                        </select>
                            <div class="hint">{{ t.mmHintLangBoost }}</div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>{{ t.mmAsrText }}</label>
                        <input
                            v-model="cloneParams.text_validation"
                            placeholder="{{ t.mmAsrPlaceholder }}"
                            :class="{'input-error': textValidationError}"
                        />
                        <div v-if="textValidationError" class="error-hint">⚠️ {{ textValidationError }}</div>
                        <div class="hint">{{ t.mmHintAsrText }}</div>
                    </div>
                    <div class="form-group">
                        <label>{{ t.mmAsrThreshold }}</label>
                        <input type="number" v-model.number="cloneParams.accuracy" min="0" max="1" step="0.1" />
                        <div class="hint">{{ t.mmHintAsrThreshold }}</div>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="cloneParams.need_noise_reduction" />
                        <label>{{ t.mmNoiseReduction }}</label>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="cloneParams.need_volume_normalization" />
                        <label>{{ t.mmVolNorm }}</label>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" v-model="cloneParams.aigc_watermark" />
                        <label>{{ t.mmAigcWatermark }}</label>
                        <div class="hint">{{ t.mmHintAigc }}</div>
                    </div>
                </div>
                <button class="btn" @click="performClone" :disabled="!isCloneEnabled || cloning">
                    {{ cloning ? t.mmCloning : t.mmCloneBtn }}
                </button>
            </fieldset>

            <!-- 复刻结果模态框 -->
            <Teleport to="body">
                <Transition name="modal">
                    <div v-if="cloneResultModalVisible" class="modal-overlay" @mousedown.self="closeCloneResult">
                        <div class="modal-content" style="max-width:500px;">
                            <h3>{{ t.mmCloneOkTitle }}</h3>
                            <p><strong>Voice ID:</strong> {{ cloneResult.voice_id }}</p>
                            <p style="color:var(--gray);font-size:0.85rem;">
                                {{ t.mmUnactivatedNote }}
                            </p>
                            <button class="btn" @click="playDemoAudio"
                                :class="{'btn-danger': currentPlayingId === 'demo_audio'}">
                                {{ currentPlayingId === 'demo_audio' ? t.stopBtn : t.mmPlayDemo }}
                            </button>
                            <div style="margin-top:16px;display:flex;gap:12px;justify-content:flex-end;">
                                <button class="btn btn-danger" @click="showDeleteUnactivatedConfirm(cloneResult.voice_id)">{{ t.deleteBtn }}
                                </button>
                                <button class="btn btn-success" @click="keepUnactivatedVoice(cloneResult, 'voice_cloning')">{{ t.keepBtn }}
                                </button>
                            </div>
                        </div>
                    </div>
                </Transition>
            </Teleport>
        </div>

        <!-- ========== 声音设计选项卡 ========== -->
        <div v-if="currentTab === 'design'">
            <fieldset
                style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
            >
                <legend>🎨 {{ t.mmLegendDesign }}</legend>
                <div class="form-group">
                    <label>{{ t.mmVoiceDesc }} <span style="color:var(--danger);">*</span></label>
                    <textarea
                        v-model="designForm.prompt"
                        rows="3"
                        placeholder="{{ t.mmVoiceDescPlaceholder }}"
                        style="width:100%;
                        :class="{'input-error': designPromptError}"
                    ></textarea>
                    <div v-if="designPromptError" class="error-hint">⚠️ {{ designPromptError }}</div>
                </div>
                <div class="form-group">
                    <label>{{ t.mmPreviewTextLabel }} <span style="color:var(--danger);">*</span></label>
                    <textarea
                        v-model="designForm.preview_text"
                        rows="2"
                        placeholder="{{ t.mmPreviewTextPlaceholder }}" style="width:100%;"
                        :class="{'input-error': designTextError}"
                    ></textarea>
                    <div v-if="designTextError" class="error-hint">⚠️ {{ designTextError }}</div>
                    <div class="hint">{{ t.mmHintPreviewText }}</div>
                </div>
                <div class="form-group">
                    <label>Voice ID</label>
                    <input v-model="designForm.voice_id" placeholder="{{ t.mmPlaceholderAuto }}"
                        :class="{'input-error': designVoiceIdError}" />
                    <div v-if="designVoiceIdError" class="error-hint">⚠️ {{ designVoiceIdError }}</div>
                    <div class="hint">{{ t.mmHintVoiceId }}</div>
                </div>
                <div class="form-group checkbox-group">
                    <input type="checkbox" v-model="designForm.aigc_watermark" />
                    <label>{{ t.mmAigcWatermark }}</label>
                    <div class="hint">{{ t.mmHintAigc }}</div>
                </div>
                <button class="btn" @click="performDesign" :disabled="!isDesignEnabled || designing">
                    {{ designing ? t.mmDesigning : t.mmDesignBtn }}
                </button>
            </fieldset>

            <!-- 设计结果模态框 -->
            <Teleport to="body">
                <Transition name="modal">
                    <div v-if="designResultModalVisible" class="modal-overlay" @mousedown.self="closeDesignResult">
                        <div class="modal-content" style="max-width:500px;">
                            <h3>{{ t.mmDesignOkTitle }}</h3>
                            <p><strong>Voice ID:</strong> {{ designResult.voice_id }}</p>
                            <p style="color:var(--gray);font-size:0.85rem;">
                                {{ t.mmUnactivatedNote }}
                            </p>
                            <div v-if="designResult.trial_audio">
                                <button class="btn" @click="playTrialAudio"
                                    :class="{'btn-danger': currentPlayingId === 'trial_audio'}">
                                    {{ currentPlayingId === 'trial_audio' ? t.stopBtn : t.mmPlayDemo }}
                                </button>
                            </div>
                            <div style="margin-top:16px;display:flex;gap:12px;justify-content:flex-end;">
                                <button class="btn btn-danger" @click="showDeleteUnactivatedConfirm(designResult.voice_id)">{{ t.deleteBtn }}
                                </button>
                                <button class="btn btn-success" @click="keepUnactivatedVoice(designResult, 'voice_generation')">{{ t.keepBtn }}
                                </button>
                            </div>
                        </div>
                    </div>
                </Transition>
            </Teleport>
        </div>

        <!-- ========== 音色列表选项卡 ========== -->
        <div v-if="currentTab === 'list'">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <h3 style="margin:0;">{{ t.voiceListTitle }}</h3>
                <button class="btn btn-sm" @click="fetchVoiceList(true)" :disabled="voiceLoading">{{ t.refresh }}</button>
            </div>
            <div v-if="voiceLoading">{{ t.loadingList }}</div>

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
                    <span>{{ t.mmUnactivatedBanner }}</span>
                </div>
                <h4 style="margin:16px 0 8px 0;">{{ t.mmUnactivatedHeading }}</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Voice ID</th>
                            <th>{{ t.mmColType }}</th>
                            <th>{{ t.colCreated }}</th>
                            <th>{{ t.colActions }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in unactivatedVoices" :key="v.voice_id">
                            <td>{{ v.voice_id }}</td>
                            <td>{{ v.type || 'unknown' }}</td>
                            <td>{{ v.created_time ? new Date(v.created_time).toLocaleString() : '-' }}</td>
                            <td>
                                <button class="btn btn-sm" @click="copyText(v.voice_id)">{{ t.copyBtn }}</button>
                                <button class="btn btn-sm" @click="openPreview(v.voice_id)">{{ t.mmPreviewActivate }}</button>
                                <button class="btn btn-danger btn-sm" @click="showDeleteUnactivatedConfirm(v.voice_id)">{{ t.deleteBtn }}
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </template>

            <!-- 自定义音色 -->
            <template v-if="customVoices.length">
                <h4 style="margin:16px 0 8px 0;">🧑‍🎨 {{ t.mmCustomHeading }}</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Voice ID</th>
                            <th>{{ t.mmColType }}</th>
                            <th>{{ t.mmColDesc }}</th>
                            <th>{{ t.colCreated }}</th>
                            <th>{{ t.colActions }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in customVoices" :key="v.voice_id">
                            <td>{{ v.voice_id }}</td>
                            <td>{{ v.type || 'unknown' }}</td>
                            <td>{{ v.description ? v.description.join(', ') : '-' }}</td>
                            <td>{{ v.created_time ? new Date(v.created_time * 1000).toLocaleString() : '-' }}</td>
                            <td>
                                <button class="btn btn-sm" @click="copyText(v.voice_id)">{{ t.copyBtn }}</button>
                                <button class="btn btn-sm" @click="openPreview(v.voice_id)">{{ t.previewBtn }}</button>
                                <button class="btn btn-danger btn-sm" @click="deleteVoice(v.voice_id, v.type)">{{ t.deleteBtn }}
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </template>

            <!-- 系统音色 -->
            <template v-if="systemVoices.length">
                <h4 style="margin:16px 0 8px 0;">🎙️ {{ t.mmSystemHeading }}</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Voice ID</th>
                            <th>{{ t.mmColName }}</th>
                            <th>{{ t.mmColDesc }}</th>
                            <th>{{ t.colActions }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in systemVoices" :key="v.voice_id">
                            <td>{{ v.voice_id }}</td>
                            <td>{{ v.voice_name || '-' }}</td>
                            <td>{{ v.description ? v.description.join(', ') : '-' }}</td>
                            <td>
                                <button class="btn btn-sm" @click="copyText(v.voice_id)">{{ t.copyBtn }}</button>
                                <button class="btn btn-sm" @click="openPreview(v.voice_id)">{{ t.previewBtn }}</button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </template>

            <!-- 空状态 -->
            <div v-if="!voiceList.length" style="text-align:center;color:var(--gray);padding:20px 0;">
                {{ t.noVoices }}
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
