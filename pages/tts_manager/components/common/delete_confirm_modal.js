// 公共「删除确认」模态框
// - 受控组件：通过 v-model:visible 控制显隐
// - 点击遮罩或「取消」按钮 → emit('cancel') 并自动关闭
// - 点击「确认」按钮 → emit('confirm')，是否关闭由父组件决定（便于处理异步失败场景）
// - 默认插槽用于放置自定义消息内容（不提供则使用 message 属性）

export default {
    name: 'DeleteConfirmModal',
    props: {
        // 是否可见（v-model）
        visible: { type: Boolean, default: false },

        // 标题
        title: { type: String, default: '⚠️ 确认删除' },

        // 消息文本（若父组件提供默认插槽，则本属性被忽略）
        message: { type: String, default: '' },

        // 按钮文字
        confirmText: { type: String, default: '确认删除' },
        cancelText: { type: String, default: '取消' },

        // 模态框最大宽度
        maxWidth: { type: String, default: '400px' },
    },
    emits: ['update:visible', 'confirm', 'cancel'],
    setup(props, { emit }) {
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

        return { close, handleCancel, handleConfirm };
    },
    template: /* html */ `
        <div
            v-if="visible"
            class="modal-overlay"
            @mousedown.self="handleCancel"
        >
            <div class="modal-content" :style="{ maxWidth: maxWidth, width: '90%' }">
                <h3>{{ title }}</h3>
                <div class="delete-confirm-body">
                    <slot>{{ message }}</slot>
                </div>
                <div class="delete-confirm-actions">
                    <button class="btn btn-sm btn-secondary" @click="handleCancel">
                        {{ cancelText }}
                    </button>
                    <button class="btn btn-danger" @click="handleConfirm">
                        {{ confirmText }}
                    </button>
                </div>
            </div>
        </div>
    `
};
