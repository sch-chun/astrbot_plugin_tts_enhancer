const { ref, reactive, computed, watch, onMounted } = Vue;

import { useToast } from '../composables/useToast.js';
import { useClipboard } from '../composables/useClipboard.js';
import { useComponentI18n } from '../composables/useComponentI18n.js';
import { useAudioManager } from '../composables/useAudioManager.js';
import { validateText } from '../composables/useTextValidator.js';
import { getVoiceList, setVoiceList } from '../composables/useVoiceListCache.js';
import VoicePreviewModal from './common/voice_preview_modal.js';
import DeleteConfirmModal from './common/delete_confirm_modal.js';

// 共享命名空间声明：本对象所有键都会汇入前缀 views.tts_studio.components.*
// 与 MM_I18N_DEFS 以及 common/ 下 bailian_speech_synthesizer、delete_confirm_modal、
// voice_preview_modal 的内联 defs 共用同一扁平命名空间。同名键的值必须保持一致，
// 否则修改一处会静默影响其它组件。改完务必重新生成 .astrbot-plugin/i18n/zh-CN.json
//（命名空间一致性校验见 tests/i18n_components_drift.test.mjs）。
const BLMM_I18N_DEFS = {
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
        "blmmUrlPlaceholder": "例如：https://example.com/voice.wav",
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
        "blmmPromptTooLarge": "示例音频文件过大，请选择 20MB 以内的文件",
        "blmmDefaultAuditionText": "你好，这是试听文本。",
        "blmmColVoiceId": "Voice ID",
        "blmmColType": "类型",
        "blmmColName": "名称",
        "blmmVolNorm": "开启音量归一化",
        "blmmAigcWatermark": "添加 AIGC 水印",
        "blmmHintAigc": "在合成音频末尾添加音频节奏标识",
        "blmmCloneSuccess": "音色克隆成功！Voice ID: ",
        "blmmCloneFail": "克隆失败: ",
        "blmmHintAuditionAfterClone": "克隆成功后将使用此文本生成试听音频，限制 1000 字符",
        "blmmCopyIdTip": "复制 ID",
        "blmmPreviewTip": "预览音色",
        "blmmLangZh": "汉语",
        "blmmLangChineseYue": "粤语",
        "blmmLangEn": "英语",
        "blmmLangAr": "阿拉伯语",
        "blmmLangRu": "俄语",
        "blmmLangEs": "西班牙语",
        "blmmLangFr": "法语",
        "blmmLangPt": "葡萄牙语",
        "blmmLangDe": "德语",
        "blmmLangTurkish": "土耳其语",
        "blmmLangDutch": "荷兰语",
        "blmmLangUkrainian": "乌克兰语",
        "blmmLangVi": "越南语",
        "blmmLangId": "印尼语",
        "blmmLangJa": "日语",
        "blmmLangIt": "意大利语",
        "blmmLangKo": "韩语",
        "blmmLangTh": "泰语",
        "blmmLangPolish": "波兰语",
        "blmmLangRomanian": "罗马尼亚语",
        "blmmLangGreek": "希腊语",
        "blmmLangCzech": "捷克语",
        "blmmLangFinnish": "芬兰语",
        "blmmLangHindi": "印地语",
        "blmmLangBulgarian": "保加利亚语",
        "blmmLangDanish": "丹麦语",
        "blmmLangHebrew": "希伯来语",
        "blmmLangMs": "马来语",
        "blmmLangPersian": "波斯语",
        "blmmLangSlovak": "斯洛伐克语",
        "blmmLangSwedish": "瑞典语",
        "blmmLangCroatian": "克罗地亚语",
        "blmmLangFil": "菲律宾语",
        "blmmLangHungarian": "匈牙利语",
        "blmmLangNorwegian": "挪威语",
        "blmmLangSlovenian": "斯洛文尼亚语",
        "blmmLangCatalan": "加泰罗尼亚语",
        "blmmLangNynorsk": "挪威尼诺斯克语",
        "blmmLangTamil": "泰米尔语",
        "blmmLangAfrikaans": "南非荷兰语",
        "blmmLangAuto": "自动",
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

const BLMM_LANG_BOOST = [
    { value: "Chinese", langKey: "blmmLangZh" },
    { value: "Chinese,Yue", langKey: "blmmLangChineseYue" },
    { value: "English", langKey: "blmmLangEn" },
    { value: "Arabic", langKey: "blmmLangAr" },
    { value: "Russian", langKey: "blmmLangRu" },
    { value: "Spanish", langKey: "blmmLangEs" },
    { value: "French", langKey: "blmmLangFr" },
    { value: "Portuguese", langKey: "blmmLangPt" },
    { value: "German", langKey: "blmmLangDe" },
    { value: "Turkish", langKey: "blmmLangTurkish" },
    { value: "Dutch", langKey: "blmmLangDutch" },
    { value: "Ukrainian", langKey: "blmmLangUkrainian" },
    { value: "Vietnamese", langKey: "blmmLangVi" },
    { value: "Indonesian", langKey: "blmmLangId" },
    { value: "Japanese", langKey: "blmmLangJa" },
    { value: "Italian", langKey: "blmmLangIt" },
    { value: "Korean", langKey: "blmmLangKo" },
    { value: "Thai", langKey: "blmmLangTh" },
    { value: "Polish", langKey: "blmmLangPolish" },
    { value: "Romanian", langKey: "blmmLangRomanian" },
    { value: "Greek", langKey: "blmmLangGreek" },
    { value: "Czech", langKey: "blmmLangCzech" },
    { value: "Finnish", langKey: "blmmLangFinnish" },
    { value: "Hindi", langKey: "blmmLangHindi" },
    { value: "Bulgarian", langKey: "blmmLangBulgarian" },
    { value: "Danish", langKey: "blmmLangDanish" },
    { value: "Hebrew", langKey: "blmmLangHebrew" },
    { value: "Malay", langKey: "blmmLangMs" },
    { value: "Persian", langKey: "blmmLangPersian" },
    { value: "Slovak", langKey: "blmmLangSlovak" },
    { value: "Swedish", langKey: "blmmLangSwedish" },
    { value: "Croatian", langKey: "blmmLangCroatian" },
    { value: "Filipino", langKey: "blmmLangFil" },
    { value: "Hungarian", langKey: "blmmLangHungarian" },
    { value: "Norwegian", langKey: "blmmLangNorwegian" },
    { value: "Slovenian", langKey: "blmmLangSlovenian" },
    { value: "Catalan", langKey: "blmmLangCatalan" },
    { value: "Nynorsk", langKey: "blmmLangNynorsk" },
    { value: "Tamil", langKey: "blmmLangTamil" },
    { value: "Afrikaans", langKey: "blmmLangAfrikaans" },
    { value: "auto", langKey: "blmmLangAuto" }
];

export default {
    name: 'BailianMinimaxSpeech2_8',
    components: { VoicePreviewModal, DeleteConfirmModal },
    props: {
        entries: { type: Array, required: true },
        bridge: { type: Object, required: true },
        templateKey: { type: String, required: true }
    },
    setup(props) {

        // ---------- i18n ----------
        const t = useComponentI18n(props.bridge, BLMM_I18N_DEFS);
        const MM_MSG = {
            empty: (l) => t.mmCannotBeEmpty.replace('{label}', l),
            min: (l, m, c) => t.mmCannotBeLess.replace('{label}', l).replace('{min}', m).replace('{count}', c),
            max: (l, m, c) => t.mmCannotExceed.replace('{label}', l).replace('{max}', m).replace('{count}', c),
        };
        const languageBoostOptions = computed(() => BLMM_LANG_BOOST.map(o => ({ value: o.value, label: t[o.langKey] })));
        if (!cloneParams.text) cloneParams.text = t.blmmDefaultAuditionText;


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

        // ---------- 全局音频控制 ----------
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
        const currentTab = ref('upload'); // 'upload' | 'url' | 'list'

        // ---------- 声音克隆（支持本地文件和 URL）----------
        const cloneParams = reactive({
            voice_id: '',
            audio_url: '',
            text: '',  // default set below
            model: 'HD',
            language_boost: 'auto',
            need_noise_reduction: false,
            need_volume_normalization: false,
            aigc_watermark: false,
        });
        const cloning = ref(false);

        // 本地文件选择
        const fileInputRef = ref(null);
        const selectedAudioFile = ref(null);
        const audioFileBase64 = ref(''); // 存储转换后的 Data URL

        // 示例音频（可选，用于增强相似度）
        const promptFileInputRef = ref(null);
        const selectedPromptFile = ref(null);
        const promptFileBase64 = ref('');
        const promptText = ref(''); // 示例音频对应的文本

        // 文件读取为 Base64 Data URL
        function handleAudioFileSelect(event) {
            const file = event.target.files[0];
            if (!file) {
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
                return;
            }

            // 校验文件类型
            const validTypes = ['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a'];
            if (!validTypes.includes(file.type) && !file.name.match(/\.(wav|mp3|m4a)$/i)) {
                showError(t.blmmAudioFormat);
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
                return;
            }

            // 校验文件大小（建议 < 10MB）
            if (file.size > 10 * 1024 * 1024) {
                showError(t.blmmAudioTooLarge);
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
                return;
            }

            selectedAudioFile.value = file;

            // 读取为 Base64 Data URL
            const reader = new FileReader();
            reader.onload = (e) => {
                audioFileBase64.value = e.target.result; // 完整的 Data URL
            };
            reader.onerror = () => {
                showError(t.blmmReadFail);
                selectedAudioFile.value = null;
                audioFileBase64.value = '';
            };
            reader.readAsDataURL(file);
        }

        // 清除文件选择
        function clearAudioFile() {
            selectedAudioFile.value = null;
            audioFileBase64.value = '';
            if (fileInputRef.value) {
                fileInputRef.value.value = '';
            }
        }

        // 示例音频文件选择
        function handlePromptFileSelect(event) {
            const file = event.target.files[0];
            if (!file) {
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
                return;
            }

            // 校验文件类型
            const validTypes = ['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a'];
            if (!validTypes.includes(file.type) && !file.name.match(/\.(wav|mp3|m4a)$/i)) {
                showError(t.blmmAudioFormat);
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
                return;
            }

            // 校验文件大小（< 20MB）
            if (file.size > 20 * 1024 * 1024) {
                showError(t.blmmPromptTooLarge);
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
                return;
            }

            selectedPromptFile.value = file;

            // 读取为 Base64 Data URL
            const reader = new FileReader();
            reader.onload = (e) => {
                promptFileBase64.value = e.target.result;
            };
            reader.onerror = () => {
                showError(t.blmmReadPromptFail);
                selectedPromptFile.value = null;
                promptFileBase64.value = '';
            };
            reader.readAsDataURL(file);
        }

        // 清除示例音频
        function clearPromptFile() {
            selectedPromptFile.value = null;
            promptFileBase64.value = '';
            promptText.value = '';
            if (promptFileInputRef.value) {
                promptFileInputRef.value.value = '';
            }
        }

        // ---------- 音色列表 ----------
        const voiceList = ref([]);
        const voiceLoading = ref(false);

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
                const items = result.items || [];
                setVoiceList(params, items); // 非终态内部跳过，不写缓存

                // 回填前校验 entry：await 期间切供应商会被旧响应覆盖（P3）
                if (selectedEntryId.value === params.entry_id) {
                    voiceList.value = items;
                }
                await syncUnactivated(items);
            } catch (e) {
                showError(t.blmmListFail + e.message);
            } finally {
                voiceLoading.value = false;
            }
        }

        // 删除音色
        async function deleteVoice(voiceId) {
            showDeleteConfirm(
                t.dlgTitle,
                t.blmmDeleteMsg.replace('{voiceId}', voiceId),
                async () => {
                    try {
                        await props.bridge.apiPost('voice/delete', {
                            entry_id: selectedEntryId.value,
                            voice_id: voiceId
                        });
                        showSuccess(t.deleteOk);
                        await fetchVoiceList(true);
                    } catch (e) {
                        showError(t.deleteFail + e.message);
                    }
                }
            );
        }

        // 预览音色
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

        // ---------- 未激活音色管理 ----------
        const unactivatedVoices = ref([]);

        async function loadUnactivatedVoices() {
            try {
                const result = await props.bridge.apiPost('kv/get', {
                    key: 'bailian_minimax_unactivated_list'
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
                key: 'bailian_minimax_unactivated_list',
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
                });
                await saveUnactivatedVoices(list);
            }
        }

        async function removeUnactivatedVoice(voiceId) {
            const list = unactivatedVoices.value.filter(v => v.voice_id !== voiceId);
            await saveUnactivatedVoices(list);
        }

        function showDeleteUnactivatedConfirm(voiceId) {
            showDeleteConfirm(
                t.dlgTitle,
                t.blmmDeleteUnactivatedMsg.replace('{voiceId}', voiceId),
                async () => {
                    try {
                        // 调用 API 删除服务端音色
                        await props.bridge.apiPost('voice/delete', {
                            entry_id: selectedEntryId.value,
                            voice_id: voiceId
                        });
                        // 删除本地
                        await removeUnactivatedVoice(voiceId);
                        showSuccess(t.mmUnactivatedDeleted);
                    } catch (e) {
                        showError(t.deleteFail + e.message);
                    }
                }
            );
        }

        async function keepUnactivatedVoice(result) {
            const voiceInfo = {
                voice_id: result.voice_id,
                type: 'voice_cloning',
                created_time: Date.now(),
            };
            await addUnactivatedVoice(voiceInfo);
            showSuccess(t.mmKeptUnactivated);
            closeCloneResult();
        }

        // ---------- 克隆操作 ----------
        async function performClone() {
            if (!selectedEntryId.value) {
                showError(t.errNoEntry);
                return;
            }

            // 确定 audio_url：优先使用本地文件转换的 Data URL，否则使用手动输入的 URL
            let finalAudioUrl = '';
            if (audioFileBase64.value) {
                finalAudioUrl = audioFileBase64.value;
            } else if (cloneParams.audio_url.trim()) {
                finalAudioUrl = cloneParams.audio_url.trim();
            } else {
                showError(t.blmmSelectOrUrl);
                return;
            }

            if (!cloneParams.text.trim()) {
                showError(t.blmmEnterAudition);
                return;
            }
            if (textError.value) {
                showError(textError.value);
                return;
            }

            cloning.value = true;
            try {
                const payload = {
                    entry_id: selectedEntryId.value,
                    voice_id: cloneParams.voice_id.trim() || undefined,
                    audio_url: finalAudioUrl,
                    text: cloneParams.text.trim(),
                    model: cloneParams.model,
                    language_boost: cloneParams.language_boost || undefined,
                    need_noise_reduction: cloneParams.need_noise_reduction || undefined,
                    need_volume_normalization: cloneParams.need_volume_normalization || undefined,
                    aigc_watermark: cloneParams.aigc_watermark || undefined,
                };

                // 可选：示例音频
                if (promptFileBase64.value) {
                    if (!promptText.value.trim()) {
                        showError(t.blmmPromptTextRequired);
                        cloning.value = false;
                        return;
                    }
                    payload.prompt_audio_url = promptFileBase64.value;
                    payload.prompt_text = promptText.value.trim();
                }

                const result = await props.bridge.apiPost('voice/create', payload);
                if (result.voice_id) {
                    showSuccess(t.blmmCloneSuccess + result.voice_id);
                    
                    // 如果有试听音频，显示试听模态框
                    if (result.demo_audio) {
                        cloneResult.value = result;
                        cloneResultModalVisible.value = true;
                    } else {
                    // 没有试听音频，直接刷新列表
                    await fetchVoiceList(true);
                    }
                    
                    // 清空表单（保留试听文本）
                    cloneParams.voice_id = '';
                    cloneParams.audio_url = '';
                    clearAudioFile();
                    clearPromptFile();
                } else {
                    showError(t.blmmCloneFail + (result.message || result.error || t.mmUnknownError));
                }
            } catch (e) {
                showError(t.blmmCloneFail + e.message);
            } finally {
                cloning.value = false;
            }
        }

        // ---------- 复制功能 ----------
        const { copyText, copyLink } = useClipboard(showSuccess, showError);

        // ---------- 生命周期 ----------
        watch(selectedEntryId, (newId) => {
            if (newId && currentTab.value === 'list') {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        watch(currentTab, (newTab) => {
            if (newTab === 'list' && selectedEntryId.value) {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        onMounted(() => {
            if (selectedEntryId.value && currentTab.value === 'list') {
                loadUnactivatedVoices();
                fetchVoiceList();
            }
        });

        // ---------- 计算属性 ----------
        const systemVoices = computed(() => {
            return voiceList.value.filter(v => v.type === 'system');
        });
        const customVoices = computed(() => {
            return voiceList.value.filter(v => v.type === 'voice_cloning');
        });

        // ---------- 删除确认模态框 ----------
        const deleteModal = reactive({
            visible: false,
            title: t.dlgTitle,
            message: '',
            onConfirm: null,
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

        // ---------- 校验 ----------
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
            required: true,
            messages: MM_MSG,
        }).error);

        const isTextValid = computed(() => !textError.value);

        // 克隆按钮启用条件
        const isUploadEnabled = computed(() => {
            return !!audioFileBase64.value &&
                cloneParams.text.trim() &&
                isVoiceIdValid.value &&
                isTextValid.value;
        });

        const isUrlEnabled = computed(() => {
            return !!cloneParams.audio_url.trim() &&
                cloneParams.text.trim() &&
                isVoiceIdValid.value &&
                isTextValid.value;
        });

        return {

            // i18n
            t,
            languageBoostOptions,

            // Toast
            toastMessage, toastVisible, toastType,
            showToast, showSuccess, showError,
            onToastMouseEnter, onToastMouseLeave,

            // 认证
            selectedEntryId, currentEntry,

            // 音频
            volume, currentPlayingId,
            isPlaying, playAudio, stopAudio,

            // 选项卡
            currentTab,

            // 克隆
            cloneParams, cloning, fileInputRef, selectedAudioFile,
            promptFileInputRef, selectedPromptFile, promptText,
            performClone, handleAudioFileSelect, clearAudioFile,
            handlePromptFileSelect, clearPromptFile,

            // 音色列表
            voiceList, voiceLoading,
            systemVoices, customVoices,
            fetchVoiceList, deleteVoice, openPreview,

            // 预览
            previewModalVisible, previewVoiceId,

            // 复刻结果
            cloneResultModalVisible, cloneResult,
            closeCloneResult, playDemoAudio,

            // 未激活音色
            unactivatedVoices,
            loadUnactivatedVoices, addUnactivatedVoice, onVoicePreviewed,
            removeUnactivatedVoice, showDeleteUnactivatedConfirm, keepUnactivatedVoice,
            
            // 复制
            copyText, copyLink,

            // 删除确认
            deleteModal,
            cancelDelete, confirmDelete,

            // 校验
            voiceIdError, isVoiceIdValid,
            textError, isTextValid,
            isUploadEnabled, isUrlEnabled,
        };
    },
    template: /*html*/ `
<div class="bailian-tts">

    <Teleport to="body">
        <!-- Toast -->
        <Transition name="toast">
            <div v-if="toastVisible"
                class="toast"
                :class="{'toast-error': toastType === 'error'}"
                @mouseenter="onToastMouseEnter"
                @mouseleave="onToastMouseLeave"
            >
                {{ toastMessage }}
            </div>
        </Transition>
    </Teleport>

    <!-- 认证配置选择 -->
    <div class="form-group">
        <label>{{ t.authConfig }}</label>
        <select v-model="selectedEntryId">
            <option v-for="entry in entries" :key="entry.id" :value="entry.id">
                {{ entry.display_name || (t.blmmConfigPrefix + entry.id) }}
            </option>
        </select>
    </div>

    <!-- 音色创建区域 -->
    <fieldset
        style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:20px;"
    >
        <legend>{{ t.blmmCreateLegend }}</legend>

        <div
            style="
                background:rgba(241,151,27,0.15);
                border-left:4px solid #f0971b;
                padding:8px 12px;
                margin-bottom:16px;
                border-radius:4px;
                color:var(--text);
            "
        >
            <strong>{{ t.blmmTip }}</strong>{{ t.blmmNotice }}
            <ul style="margin: 4px 0 0 0; padding-left: 20px; color: var(--text);">
                <li>
                    {{ t.mmSeeDetails }}<span class="link-copy"
                        @click="copyLink(
                            'https://docs.bailian.console.aliyun.com/zh/model-studio/model-pricing#minimax-2'
                        )"
                        style="color:var(--primary);cursor:pointer;text-decoration:underline;"
                    >{{ t.blmmPricingDoc }}</span>{{ t.sysVoiceSuffix }}
                </li>
            </ul>
        </div>

        <!-- 选项卡切换 -->
        <div
            style="display:flex;gap:8px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;"
        >
            <button 
                class="tab" 
                data-label="{{ t.blmmTabUpload }}"
                :class="{ active: currentTab === 'upload' }"
                @click="currentTab = 'upload'"
                style="
                    padding:8px 16px;
                    border:none;
                    background:transparent;
                    cursor:pointer;
                    border-bottom:2px solid transparent;
                "
            >📁 {{ t.blmmTabUpload }}</button>
            <button 
                class="tab" 
                data-label="{{ t.blmmTabUrl }}"
                :class="{ active: currentTab === 'url' }"
                @click="currentTab = 'url'"
                style="
                    padding:8px 16px;
                    border:none;
                    background:transparent;
                    cursor:pointer;
                    border-bottom:2px solid transparent;
                "
            >🔗 {{ t.blmmTabUrl }}</button>
            <button 
                class="tab" 
                data-label="{{ t.blmmTabList }}"
                :class="{ active: currentTab === 'list' }"
                @click="currentTab = 'list'"
                style="
                    padding:8px 16px;
                    border:none;
                    background:transparent;
                    cursor:pointer;
                    border-bottom:2px solid transparent;
                "
            >📋 {{ t.blmmTabList }}</button>
        </div>

        <!-- 上传音频文件表单 -->
        <div v-if="currentTab === 'upload'">
            <div class="form-group">
                <label>{{ t.blmmSelectLocal }}</label>
                <input type="file" 
                    ref="fileInputRef"
                    @change="handleAudioFileSelect"
                    accept=".wav,.mp3,.m4a" />
                <div v-if="selectedAudioFile" class="hint" style="color:var(--primary);">
                    {{ t.blmmSelectedPrefix }}{{ selectedAudioFile.name }} ({{ (selectedAudioFile.size / 1024).toFixed(1) }} KB)
                    <span style="color:var(--primary);cursor:pointer;text-decoration:underline;margin-left:8px;"
                        @click="clearAudioFile">{{ t.blmmClear }}</span>
                </div>
                <div class="hint">{{ t.blmmHintLocalAudio }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.blmmCustomId }}</label>
                <input type="text" v-model="cloneParams.voice_id" 
                    placeholder="{{ t.blmmPlaceholderAuto }}" 
                    :class="{ 'input-error': !isVoiceIdValid }" />
                <div v-if="voiceIdError" class="error-hint">⚠️ {{ voiceIdError }}</div>
                <div class="hint">{{ t.mmHintVoiceId }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.mmAuditionText }}</label>
                <textarea 
                    v-model="cloneParams.text" 
                    rows="3" 
                    placeholder="{{ t.blmmAuditionPlaceholder }}" 
                    :class="{ 'input-error': !isTextValid }"
                    style="
                        width:100%;
                        padding:8px;
                        border:1px solid var(--border);
                        border-radius:var(--radius);
                        background:var(--bg);
                        color:var(--text);
                        resize:vertical;
                    "
                ></textarea>
                <div v-if="textError" class="error-hint">⚠️ {{ textError }}</div>
                <div class="hint">{{ t.blmmHintAudition }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.blmmModelVersion }}</label>
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
                <div class="hint">{{ t.blmmHintLangBoost }}</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_noise_reduction" id="upload_noise" />
                <label for="upload_noise">{{ t.blmmNoiseReduction }}</label>
                <div class="hint">{{ t.blmmNoiseHint }}</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_volume_normalization" id="upload_vol_norm" />
                <label for="upload_vol_norm">{{ t.blmmVolNorm }}</label>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.aigc_watermark" id="upload_aigc" />
                <label for="upload_aigc">{{ t.blmmAigcWatermark }}</label>
                <div class="hint">{{ t.blmmHintAigc }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.blmmPromptAudio }}</label>
                <input type="file" 
                    ref="promptFileInputRef"
                    @change="handlePromptFileSelect"
                    accept=".wav,.mp3,.m4a" />
                <div v-if="selectedPromptFile" class="hint" style="color:var(--primary);">
                    {{ t.blmmSelectedPrefix }}{{ selectedPromptFile.name }} ({{ (selectedPromptFile.size / 1024).toFixed(1) }} KB)
                    <span style="color:var(--primary);cursor:pointer;text-decoration:underline;margin-left:8px;"
                        @click="clearPromptFile">{{ t.blmmClear }}</span>
                </div>
                <div class="hint">{{ t.blmmHintPrompt }}</div>
            </div>

            <div v-if="selectedPromptFile" class="form-group">
                <label>{{ t.blmmPromptTextLabel }}</label>
                <input type="text" v-model="promptText" 
                    placeholder="{{ t.blmmPromptPlaceholder }}" />
                <div class="hint">{{ t.blmmHintPromptText }}</div>
            </div>

            <button
                class="btn"
                @click="performClone"
                :disabled="!isUploadEnabled || cloning"
            >
                {{ cloning ? t.blmmCloning : t.blmmCloneBtn }}
            </button>
        </div>

        <!-- 使用音频 URL 表单 -->
        <div v-if="currentTab === 'url'">
            <div class="form-group">
                <label>{{ t.blmmPublicUrl }}</label>
                <input type="url" v-model="cloneParams.audio_url" 
                    :placeholder="t.blmmUrlPlaceholder" />
                <div class="hint">{{ t.blmmHintUrl }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.blmmCustomId }}</label>
                <input type="text" v-model="cloneParams.voice_id" 
                    placeholder="{{ t.blmmPlaceholderAuto }}" 
                    :class="{ 'input-error': !isVoiceIdValid }" />
                <div v-if="voiceIdError" class="error-hint">⚠️ {{ voiceIdError }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.mmAuditionText }}</label>
                <textarea 
                    v-model="cloneParams.text" 
                    rows="3" 
                    placeholder="{{ t.blmmAuditionPlaceholder }}" 
                    :class="{ 'input-error': !isTextValid }"
                    style="
                        width:100%;
                        padding:8px;
                        border:1px solid var(--border);
                        border-radius:var(--radius);
                        background:var(--bg);
                        color:var(--text);
                        resize:vertical;
                    "
                ></textarea>
                <div v-if="textError" class="error-hint">⚠️ {{ textError }}</div>
                <div class="hint">{{ t.blmmHintAuditionAfterClone }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.blmmModelVersion }}</label>
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
                <div class="hint">{{ t.blmmHintLangBoost }}</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_noise_reduction" id="url_noise" />
                <label for="url_noise">{{ t.blmmNoiseReduction }}</label>
                <div class="hint">{{ t.blmmNoiseHint }}</div>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.need_volume_normalization" id="url_vol_norm" />
                <label for="url_vol_norm">{{ t.blmmVolNorm }}</label>
            </div>

            <div class="form-group checkbox-group">
                <input type="checkbox" v-model="cloneParams.aigc_watermark" id="url_aigc" />
                <label for="url_aigc">{{ t.blmmAigcWatermark }}</label>
                <div class="hint">{{ t.blmmHintAigc }}</div>
            </div>

            <div class="form-group">
                <label>{{ t.blmmPromptAudio }}</label>
                <input type="file" 
                    ref="promptFileInputRef"
                    @change="handlePromptFileSelect"
                    accept=".wav,.mp3,.m4a" />
                <div v-if="selectedPromptFile" class="hint" style="color:var(--primary);">
                    {{ t.blmmSelectedPrefix }}{{ selectedPromptFile.name }} ({{ (selectedPromptFile.size / 1024).toFixed(1) }} KB)
                    <span style="color:var(--primary);cursor:pointer;text-decoration:underline;margin-left:8px;"
                        @click="clearPromptFile">{{ t.blmmClear }}</span>
                </div>
                <div class="hint">{{ t.blmmHintPrompt }}</div>
            </div>

            <div v-if="selectedPromptFile" class="form-group">
                <label>{{ t.blmmPromptTextLabel }}</label>
                <input type="text" v-model="promptText" 
                    placeholder="{{ t.blmmPromptPlaceholder }}" />
                <div class="hint">{{ t.blmmHintPromptText }}</div>
            </div>

            <button
                class="btn"
                @click="performClone"
                :disabled="!isUrlEnabled || cloning"
            >
                {{ cloning ? t.blmmCloning : t.blmmUrlCloneBtn }}
            </button>
        </div>

        <!-- 音色列表 -->
        <div v-if="currentTab === 'list'">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <h3 style="margin:0;">{{ t.voiceListTitle }}</h3>
                <button class="btn btn-sm" @click="fetchVoiceList(true)" :disabled="voiceLoading">{{ t.refresh }}</button>
            </div>
            <div v-if="voiceLoading">{{ t.loadingList }}</div>
            <template v-else>
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
                        <span>{{ t.blmmUnactivatedBanner }}</span>
                    </div>
                    <h4 style="margin:16px 0 8px 0;">{{ t.mmUnactivatedHeading }}</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>{{ t.blmmColVoiceId }}</th>
                                <th>{{ t.blmmColType }}</th>
                                <th>{{ t.colCreated }}</th>
                                <th>{{ t.colActions }}</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="v in unactivatedVoices" :key="v.voice_id">
                                <td>{{ v.voice_id }}</td>
                                <td>{{ v.type || 'voice_cloning' }}</td>
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

                <!-- 复刻音色 -->
                <template v-if="customVoices.length">
                    <h4 style="margin:16px 0 8px 0;">{{ t.blmmClonedHeading }}</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>{{ t.blmmColVoiceId }}</th>
                                <th>{{ t.blmmColName }}</th>
                                <th>{{ t.colCreated }}</th>
                                <th>{{ t.colActions }}</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="v in customVoices" :key="v.voice_id">
                                <td>{{ v.voice_id }}</td>
                                <td>{{ v.voice_name || '-' }}</td>
                                <td>{{ v.created_at || '-' }}</td>
                                <td>
                                    <button
                                        class="btn btn-sm"
                                        @click="copyText(v.voice_id)"
                                        :title="t.blmmCopyIdTip"
                                        style="margin-right: 4px;"
                                    >{{ t.copyBtn }}</button>
                                    <button
                                        class="btn btn-sm"
                                        @click="openPreview(v.voice_id)"
                                        :title="t.blmmPreviewTip"
                                        style="margin-right: 4px;"
                                    >{{ t.previewBtn }}</button>
                                    <button
                                        class="btn btn-danger btn-sm"
                                        @click="deleteVoice(v.voice_id)"
                                    >{{ t.deleteBtn }}</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </template>

                <!-- 系统音色 -->
                <template v-if="systemVoices.length">
                    <h4 style="margin:16px 0 8px 0;">{{ t.mmSystemHeading }}</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>{{ t.blmmColVoiceId }}</th>
                                <th>{{ t.blmmColName }}</th>
                                <th>{{ t.colActions }}</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="v in systemVoices" :key="v.voice_id">
                                <td>{{ v.voice_id }}</td>
                                <td>{{ v.voice_name || '-' }}</td>
                                <td>
                                    <button
                                        class="btn btn-sm"
                                        @click="copyText(v.voice_id)"
                                        :title="t.blmmCopyIdTip"
                                        style="margin-right: 4px;"
                                    >{{ t.copyBtn }}</button>
                                    <button
                                        class="btn btn-sm"
                                        @click="openPreview(v.voice_id)"
                                        :title="t.blmmPreviewTip"
                                    >{{ t.previewBtn }}</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </template>

                <!-- 空状态 -->
                <div v-if="!voiceList.length && !unactivatedVoices.length"
                    style="text-align:center;color:var(--gray);padding:20px 0;">
                    {{ t.noVoices }}
                </div>
            </template>
        </div>
    </fieldset>

    <!-- 复刻结果试听模态框 -->
    <Teleport to="body">
        <Transition name="modal">
            <div v-if="cloneResultModalVisible" class="modal-overlay" @mousedown.self="closeCloneResult">
                <div class="modal-content" style="max-width:500px;">
                    <h3>{{ t.blmmCloneOkTitle }}</h3>
                    <p><strong>Voice ID:</strong> {{ cloneResult.voice_id }}</p>
                    <p style="color:var(--gray);font-size:0.85rem;">
                        {{ t.mmUnactivatedNote }}
                    </p>
                    <div v-if="cloneResult.demo_audio">
                        <button class="btn" @click="playDemoAudio"
                            :class="{'btn-danger': currentPlayingId === 'demo_audio'}">
                            {{ currentPlayingId === 'demo_audio' ? t.stopBtn : t.mmPlayDemo }}
                        </button>
                    </div>
                    <div style="margin-top:16px;display:flex;gap:12px;justify-content:flex-end;">
                        <button class="btn btn-danger" @click="showDeleteUnactivatedConfirm(cloneResult.voice_id)">{{ t.deleteBtn }}
                        </button>
                        <button class="btn btn-success" @click="keepUnactivatedVoice(cloneResult)">{{ t.keepBtn }}
                        </button>
                    </div>
                </div>
            </div>
        </Transition>
    </Teleport>

    <!-- 预览模态框 -->
    <VoicePreviewModal
        v-model:visible="previewModalVisible"
        :bridge="bridge"
        :entry-id="selectedEntryId"
        :voice-id="previewVoiceId"
        id-prefix="bailian_minimax_preview"
        @previewed="onVoicePreviewed"
    />

    <!-- 删除确认模态框 -->
    <DeleteConfirmModal
        :visible="deleteModal.visible"
        :title="deleteModal.title"
        :message="deleteModal.message"
        @confirm="confirmDelete"
        @cancel="cancelDelete"
    />
</div>
`
};
