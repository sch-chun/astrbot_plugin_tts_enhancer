// 公共「删除确认」模态框
// - 受控组件：通过 v-model:visible 控制显隐
// - 点击遮罩或「取消」按钮 → emit('cancel') 并自动关闭
// - 点击「确认」按钮 → emit('confirm')，是否关闭由父组件决定（便于处理异步失败场景）
// - 默认插槽用于放置自定义消息内容（不提供则使用 message 属性）

import { useComponentI18n } from '../../composables/useComponentI18n.js';

export default {
    name: 'DeleteConfirmModal',
    props: {
        // 是否可见（v-model）
        visible: { type: Boolean, default: false },

        // 桥接对象（提供 t / onContext，用于标题与按钮文案自检本地化；缺省时回退 zh-CN）
        bridge: { type: Object, default: null },

        // 标题（为空时由组件按当前语言回填）
        title: { type: String, default: '' },

        // 消息文本（若父组件提供默认插槽，则本属性被忽略）
        message: { type: String, default: '' },

        // 按钮文字（为空时由组件按当前语言回填）
        confirmText: { type: String, default: '' },
        cancelText: { type: String, default: '' },

        // 模态框最大宽度
        maxWidth: { type: String, default: '400px' },
    },
    emits: ['update:visible', 'confirm', 'cancel'],
    setup(props, { emit }) {
        // 组件级 i18n 自检（标题与按钮文案）
        // 注意：内联 defs 的键汇入共享命名空间 views.tts_studio.components.*，
        // 其中 dlgTitle/dlgConfirm/dlgCancel 与 bailian_speech_synthesizer 共用，值必须一致。
        const t = useComponentI18n(props.bridge, {
            dlgTitle: '⚠️ 确认删除',
            dlgConfirm: '确认删除',
            dlgCancel: '取消',
        });

        function close() {
            emit('update:visible', false);
        }

        function handleCancel() {
            emit('cancel');
            close();
        }

        function handleConfirm() {
            emit('confirm');
        }

        return { close, handleCancel, handleConfirm, t };
    },
    template: /* html */ `
        <Teleport to="body">
            <Transition name="modal">
                <div
                    v-if="visible"
                    class="modal-overlay"
                    @mousedown.self="handleCancel"
                >
                    <div class="modal-content" :style="{ maxWidth: maxWidth, width: '90%' }">
                        <h3>{{ title || t.dlgTitle }}</h3>
                        <div class="delete-confirm-body">
                            <slot>{{ message }}</slot>
                        </div>
                        <div class="delete-confirm-actions">
                            <button class="btn btn-sm btn-secondary" @click="handleCancel">
                                {{ cancelText || t.dlgCancel }}
                            </button>
                            <button class="btn btn-danger" @click="handleConfirm">
                                {{ confirmText || t.dlgConfirm }}
                            </button>
                        </div>
                    </div>
                </div>
            </Transition>
        </Teleport>
    `
};
