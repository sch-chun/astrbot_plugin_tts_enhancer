"""Web 路由模块集合。

从 ``main._register_routes`` 巨型方法中拆分出的各类路由注册器统一置于此处：
``voice``（供应商列表 + 音色 CRUD + 预览）、``file``（音频上传 + 供应商文件管理）、
``kv``（通用键值存储）、``records``（合成记录管理 + 管理页背景图）。

每个模块暴露一个 ``register_*(plugin)`` 函数，以闭包捕获传入的插件实例，
由 ``main._register_routes`` 统一调用。
"""
