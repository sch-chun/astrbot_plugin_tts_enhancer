// 公共「音色预览」模态框
// - 输入预览文本 → 调用 bridge.apiPost('voice/preview') 合成 → 底部行内出现可重播播放器 + 时长提示
// - 播放复用全局音频单例 useAudioManager（playAudio/stopAudio），与全站其它播放器一致，
//   天然保证同一时刻只有一段音频在响；blob URL 由本组件在关闭 / 重合成时自行释放。
// - 通过 previewed 事件把预览结果通知给父组件（如激活后刷新列表）

const { ref, watch, computed, onUnmounted } = Vue;


import { useToast } from '../../composables/useToast.js';
import { useAudioManager, base64ToBlobUrl } from '../../composables/useAudioManager.js';
import { useComponentI18n } from '../../composables/useComponentI18n.js';


// 适合朗读的示例文本池（按语言）：打开模态框时按当前语言随机抽一条，便于快速试听不同语调 / 情绪。
// 覆盖陈述、疑问、感叹、播报、温柔等多种句式，长短与标点不一，方便对比音色表现。
const SAMPLES_BY_LOCALE = {
    // 覆盖日常闲聊 / 温柔治愈 / 调皮撒娇 / 激动兴奋 / 疑问好奇 / 鼓励表白等多种情绪与句式，
    // 长短与标点不一，便于对比不同音色的语气与情感表现。特意减少播报 / 公函式正式样例，
    // 让情绪更自然显现。
    'zh-CN': [
        '你好呀，今天天气真不错，我们一起去公园散步吧！',
        '生活就像一盒巧克力，你永远不知道下一颗是什么味道。',
        '请问这附近有推荐的咖啡馆吗？我想找个安静的地方看会儿书。',
        '根据最新数据，本周气温将下降五到八摄氏度，请大家注意添衣保暖。',
        '谢谢你一直以来的陪伴，没有你，我可能早就坚持不下去了。',
        '哇，这座城市的夜景也太美了吧，灯火璀璨，宛如星河落在人间。',
        '小朋友，慢一点走，前面的台阶有点滑，要小心哦。',
        '嘿，今晚要不要一起去吃那家新开的火锅？我请客！',
        '你也太厉害了吧，这道题我琢磨了一下午都没搞懂。',
        '哈哈哈刚才那只猫走路的姿势也太搞笑了，像在走时装秀。',
        '哎呀我忘带钥匙了，你能不能帮我叫个开锁的呀？',
        '明天周末耶，咱们睡到自然醒再去逛街好不好？',
        '慢慢来，不用着急，我会一直陪着你的。',
        '其实你笑起来的样子，比晴天还要好看。',
        '真的吗？！我居然中奖了，快掐我一下看是不是在做梦！',
        '太棒了，我们的方案过了！今晚必须好好庆祝一下！',
        '诶，你有没有觉得今天的云朵特别像一只巨大的棉花糖？',
        '别放弃，再试一次，我超相信你的。',
        '其实从很久以前，我就想对你说声谢谢了。',
        '哼，不理你了，除非你给我买奶茶赔罪！',
    ],
    'en-US': [
        "Hey there, the weather is really nice today—let's go for a walk in the park together!",
        "Life is like a box of chocolates; you never know what you're going to get.",
        "Excuse me, are there any recommended cafés nearby? I'd like a quiet place to read.",
        'According to the latest data, temperatures will drop by five to eight degrees this week—please dress warmly.',
        "Thank you for being by my side all along; I might have given up long ago without you.",
        'Wow, the night view of this city is absolutely stunning, ablaze with lights like a galaxy come down to earth.',
        'Little one, walk a bit slower; the steps ahead are slippery, so be careful.',
        "Hey, want to go try that new hot pot place tonight? It's on me!",
        "Whoa, you're way too awesome—I spent the whole afternoon on this problem and still couldn't crack it.",
        'Hahaha, the way that cat just walked was so ridiculous, like it was strutting down a runway.',
        "Ugh, I forgot my keys—could you call a locksmith for me?",
        "It's the weekend tomorrow! Let's sleep in and then go shopping, okay?",
        "Take your time, no rush—I'll be right here with you.",
        "You know, your smile is even prettier than a sunny day.",
        "Wait, really?! I actually won—pinch me, I must be dreaming!",
        "Yes! Our proposal got approved—we have to celebrate tonight!",
        "Hey, don't you think today's clouds look exactly like one giant cotton candy?",
        "Don't give up, just try once more—I believe in you so much.",
        "Actually, I've wanted to say thank you to you for the longest time.",
        "Hmph, I'm not talking to you unless you buy me milk tea to make up for it!",
    ],
    'ja-JP': [
        'こんにちは、今日は本当にいい天気だね。一緒に公園を散歩しよう！',
        '人生はチョコレートの箱のようなもの。次に何が出るか分からない。',
        'すみません、この近くでおすすめのカフェはありますか？静かな場所で本を読みたいんです。',
        '最新のデータによりますと、今週の気温は 5 から 8 度低下します。暖かくしてお過ごしください。',
        'いつもそばにいてくれてありがとう。あなたがいなければ、とっくに諦めていたかもしれません。',
        'わあ、この街の夜景は本当に美しいね。まるで天から降り注ぐ銀河のようだ。',
        'ちょっと、ゆっくり歩こうね。前の階段は滑りやすいから、気をつけて。',
        'ねえ、今夜あの新しい火鍋（ヒナベ）のお店に行かない？私がおごるよ！',
        'すごいなあ、あなた。この問題、私午後ずっと悩んでたのにまだ分からないよ。',
        'わはは、さっきの猫の歩き方、めちゃくちゃおかしい、まるでランウェイを歩いてるみたい。',
        'あーあ、鍵忘れちゃったの。開錠業者呼んでくれない？',
        '明日は週末だね！朝ゆっくり起きてからお買い物行こうよ、いい？',
        '急がなくていいよ、ゆっくりでいいから。ずっとそばにいるから。',
        'あのね、あなたの笑顔は晴れた日よりもっと素敵だよ。',
        'え、本当に？！私当たったの？ちょっとつねって、夢じゃないか確かめて！',
        'やったー！提案通ったよ！今夜絶対祝わないと！',
        'ねえ、今日の雲、巨大な綿あめみたいに見えない？',
        '諦めないで、もう一回やってみて。私、あなたのことめちゃくちゃ信じてるよ。',
        '実はね、ずっと前から、あなたに「ありがとう」って言いたかったの。',
        'むー、あなたと話さないんだから。ミルクティーおごって謝るまで！',
    ],
    'ru-RU': [
        'Привет! Сегодня погода просто чудесная — давай вместе пройдёмся по парку!',
        'Жизнь как коробка шоколадных конфет: никогда не знаешь, что достанется в следующий раз.',
        'Подскажите, пожалуйста, есть ли поблизости хорошее кафе? Хочу найти тихое место для чтения.',
        'Согласно последним данным, на этой неделе температура упадёт на 5–8 градусов — теплее одевайтесь.',
        'Спасибо, что всё это время был рядом. Без тебя я, наверное, давно бы сдался.',
        'Ого, ночной вид этого города просто потрясающий, словно галактика, опустившаяся на землю.',
        'Малыш, иди помедленнее, вперёд идут скользкие ступеньки — будь осторожен.',
        'Эй, хочешь сегодня вечером сходить в тот новый хого? Я угощаю!',
        'Ого, ну ты даёшь! Я целый день над этой задачей сидел и так и не разобрался.',
        'Ха-ха-ха, как эта кошка только что шла — прямо по подиуму выступала, до чего смешно.',
        'Ой, я же ключи забыл! Не вызовешь мне, случайно, замочника?',
        'Завтра же выходной! Давай выспимся, а потом пойдём гулять, ладно?',
        'Не торопись, никуда не спешим — я всё время буду рядом с тобой.',
        'Знаешь, твоя улыбка милее самого солнечного дня.',
        'Серьёзно?! Я правда выиграл — ущипни меня, я, наверное, сплю!',
        'Ура! Нашу заявку одобрили — сегодня обязательно надо отпраздновать!',
        'Слушай, а не кажется ли тебе, что сегодняшние облака похожи на огромную сахарную вату?',
        'Не сдавайся, попробуй ещё раз — я в тебя просто безумно верю.',
        'Знаешь, я с давних пор хотел сказать тебе спасибо.',
        'Фи, не буду с тобой разговаривать, пока не купишь мне молочный чай в знак извинения!',
    ],
};


export default {
    name: 'VoicePreviewModal',
    props: {
        // 是否可见（v-model）
        visible: { type: Boolean, default: false },

        // 桥接对象（提供 apiPost）
        bridge: { type: Object, required: true },

        // 认证配置 id
        entryId: { type: [Number, String], default: null },

        // 当前预览的音色 id
        voiceId: { type: String, default: '' },

        // 默认预览文本（未被父组件覆盖时，打开模态框会从示例池随机抽一条替换）
        initialText: { type: String, default: '' },

        // 播放标识前缀，与本音色 voiceId 拼成全局唯一播放 id，复用全局音频单例
        idPrefix: { type: String, default: 'voice_preview' },

        // 后端未返回 format 时的缺省音频格式
        defaultFormat: { type: String, default: 'mp3' },

        // 合成来源：标记本次预览应记入「合成记录」的来源类别
        // （preview=音色预览 / design_preview=设计试听，缺省为 preview）
        source: { type: String, default: 'preview' },

        // 模态框标题（为空时由组件按当前语言回填）
        title: { type: String, default: '' },
    },
    emits: ['update:visible', 'previewed'],
    setup(props, { emit }) {
        const {
            toastMessage, toastVisible, toastType,
            showError,
            onToastMouseEnter, onToastMouseLeave,
        } = useToast();

        // 复用全局音频单例：playAudio/stopAudio 保证全站同一时刻只响一段，
        // currentPlayingId 用于按钮在「播放 / 停止」间切换。
        const { currentPlayingId, playAudio, stopAudio } = useAudioManager();

        // 组件级 i18n 自检
        // 注意：内联 defs 的键汇入共享命名空间 views.tts_studio.components.*，
        // 与 MM_I18N_DEFS / BLMM_I18N_DEFS 等共用，同名键值必须一致，改完需重新生成 zh-CN.json。
        const t = useComponentI18n(props.bridge, {
            previewTitle: '预览音色',
            previewTextLabel: '预览文本',
            previewTextPlaceholder: '输入用于试听的文本...',
            enhanceToggle: '调用 SubAgent 增强（可选，将消耗一次 LLM 调用）',
            stopBtn: '⏹ 停止',
            playBtn: '▶ 播放',
            synthedOk: '合成成功！音频时长：',
            calcDuration: '计算中…',
            durationSec: '秒',
            synthezing: '合成中...',
            btnSynthesize: '合成',
            closeBtn: '关闭',
            errPreviewText: '请输入预览文本',
            errNoEntry: '请先选择认证配置',
            errNoAudio: '预览失败: 未返回音频数据',
            errPreviewFail: '预览失败:',
        });

        // 按当前语言选取示例文本池（随 WebUI 语言切换实时更新，而非 setup 时定死）
        const currentLocale = ref(
            (props.bridge && typeof props.bridge.getLocale === 'function')
                ? props.bridge.getLocale() : 'zh-CN'
        );
        const SAMPLES = computed(
            () => SAMPLES_BY_LOCALE[currentLocale.value] || SAMPLES_BY_LOCALE['zh-CN']
        );

        // 随机抽取一条示例；避免与当前文本相同（池子大于 1 时），连续打开不至于重复。
        function pickRandomSample(current) {
            const pool = SAMPLES.value;
            if (pool.length <= 1) {
                return pool[0] || '';
            }
            let next = current;
            while (next === current) {
                next = pool[Math.floor(Math.random() * pool.length)];
            }
            return next;
        }

        // 语言切换时同步刷新示例池（否则 setup 时锁定的语言会一直生效，导致样例文本不随界面语言变化）
        let offLocale = null;
        if (props.bridge && typeof props.bridge.onContext === 'function') {
            offLocale = props.bridge.onContext(() => {
                currentLocale.value =
                    (props.bridge && typeof props.bridge.getLocale === 'function')
                        ? props.bridge.getLocale() : 'zh-CN';
            });
        }
        onUnmounted(() => { if (typeof offLocale === 'function') offLocale(); });

        const text = ref(props.initialText);
        const loading = ref(false);
        // 可选：调用 SubAgent 增强（默认关闭，保持预览零 LLM 开销）
        const useEnhance = ref(false);

        // 合成后的音频（blob URL）；非空时行内出现播放器
        const audioUrl = ref('');
        // 音频时长（秒）；合成后由独立 probe 探测，不依赖是否自动播放成功
        const audioDuration = ref(0);

        // 全局唯一播放 id：前缀 + 音色 id，避免与其它组件的播放器（demo/file/trial）冲突
        const playId = computed(() => `${props.idPrefix}_${props.voiceId}`);

        // 释放音频：先停掉播放（cleanup 为 null，单例不会误回收我们的 URL），
        // 再 revoke 上一段 blob URL；关闭模态框 / 重新合成前调用，避免内存泄漏。
        function revokeAudio() {
            stopAudio();
            if (audioUrl.value) {
                try { URL.revokeObjectURL(audioUrl.value); } catch (_) {}
            }
            audioUrl.value = '';
            audioDuration.value = 0;
        }

        function close() {
            revokeAudio();
            emit('update:visible', false);
        }

        // 打开时：若文本为空，或仍是系统示例（未被用户改写），随机抽一条朗读示例；
        // 已含用户自定义文本则保留，避免关闭重开时误删输入。
        watch(() => props.visible, (v) => {
            if (!v) return;
            const cur = text.value.trim();
            if (!cur || SAMPLES.value.includes(cur)) {
                text.value = pickRandomSample(cur);
            }
        });

        async function doPreview() {
            if (!text.value.trim()) {
                showError(t.errPreviewText);
                return;
            }
            if (props.entryId === null || props.entryId === undefined) {
                showError(t.errNoEntry);
                return;
            }
            loading.value = true;
            try {
                const result = await props.bridge.apiPost('voice/preview', {
                    entry_id: props.entryId,
                    voice_id: props.voiceId,
                    text: text.value.trim(),
                    source: props.source,
                    enhance: useEnhance.value,
                });
                if (!result.audio_base64) {
                    showError(t.errNoAudio);
                    return;
                }
                // 释放上一段音频，替换为新合成结果
                revokeAudio();
                const mimeType = `audio/${result.format || props.defaultFormat}`;
                audioUrl.value = base64ToBlobUrl(result.audio_base64, mimeType);
                emit('previewed', { voiceId: props.voiceId, result });
                // 探测时长（仅加载 metadata，不播放），与是否自动播放成功无关
                probeDuration(audioUrl.value);
                // 尝试自动播放（受浏览器自动播放策略限制，失败则保持播放器可见供手动播放）
                playAudio(audioUrl.value, playId.value, { cleanup: null });
            } catch (e) {
                console.error('预览失败:', e);
                showError(t.errPreviewFail + ' ' + e.message);
            } finally {
                loading.value = false;
            }
        }

        // 用独立 Audio 探测时长，避免依赖播放；探测期间若已重合成则丢弃旧结果
        function probeDuration(url) {
            audioDuration.value = 0;
            const probe = new Audio(url);
            probe.preload = 'metadata';
            probe.onloadedmetadata = () => {
                if (audioUrl.value === url) {
                    audioDuration.value = probe.duration || 0;
                }
                probe.onloadedmetadata = null;
            };
            probe.onerror = () => { probe.onloadedmetadata = null; };
            probe.load();
        }

        function togglePreviewPlay() {
            if (!audioUrl.value) return;
            // playAudio 对相同 id 自动 toggle 为停止，故单个按钮即「播放 / 停止」
            playAudio(audioUrl.value, playId.value, { cleanup: null });
        }

        function formatDuration(s) {
            if (!s || isNaN(s) || s <= 0) return t.calcDuration;
            return `${s.toFixed(1)} ${t.durationSec}`;
        }

        return {
            // 通知框
            toastMessage, toastVisible, toastType,
            onToastMouseEnter, onToastMouseLeave,

            // 状态
            text, loading, useEnhance,
            audioUrl, playId, currentPlayingId, audioDuration,

            // i18n
            t,

            // 方法
            close, doPreview, togglePreviewPlay, formatDuration,
        };
    },
    template: /* html */ `
        <Teleport to="body">
            <Transition name="modal">
                <div v-if="visible" class="modal-overlay" @mousedown.self="close">
                    <div class="modal-content">
                        <h3>{{ title || t.previewTitle }}</h3>
                        <p><strong>Voice ID:</strong> {{ voiceId }}</p>
                        <div class="form-group">
                            <label>{{ t.previewTextLabel }}</label>
                            <textarea v-model="text" rows="3" :placeholder="t.previewTextPlaceholder"></textarea>
                        </div>
                        <label class="enhance-toggle">
                            <input type="checkbox" v-model="useEnhance" />
                            <span>{{ t.enhanceToggle }}</span>
                        </label>
                        <div class="preview-actions">
                            <!-- 左侧：合成成功后的可重播播放 + 时长提示 -->
                            <div class="preview-play" v-if="audioUrl">
                                <button class="btn btn-sm" @click="togglePreviewPlay">
                                    {{ currentPlayingId === playId ? t.stopBtn : t.playBtn }}
                                </button>
                                <span class="preview-hint">{{ t.synthedOk }}{{ formatDuration(audioDuration) }}</span>
                            </div>
                            <!-- 右侧：合成 / 关闭 -->
                            <div class="preview-buttons">
                                <button
                                    class="btn"
                                    @click="doPreview"
                                    :disabled="loading"
                                >
                                    {{ loading ? t.synthezing : t.btnSynthesize }}
                                </button>
                                <button class="btn btn-sm btn-secondary" @click="close">{{ t.closeBtn }}</button>
                            </div>
                        </div>
                    </div>
                </div>
            </Transition>

            <!-- 组件内部 toast（与父组件相互独立） -->
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
    `
};
