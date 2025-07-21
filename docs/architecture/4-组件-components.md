# **4\. 组件 (Components)**

* **IPC路由核心 (ipc-router)**: 系统的“大脑”，负责服务注册/发现、健康检查、消息路由和主备切换协调。
* **客户端SDK (ipc-client-sdk)**: 系统的“接口”，封装所有通信复杂性，提供给业务服务使用的、可安装的Python库。
* **管理命令行 (ipc-cli)**: 系统的“管理工具”，用于查询系统状态和执行管理操作。
* **持久化层 (Persistence Layer)**: ipc-router内部的逻辑层，负责与NATS JetStream交互，实现“精确一次投递”。

## **组件关系图**

Code snippet

graph TD
    subgraph 您的交易系统
        A\[交易服务A\] \-- 使用 \--\> B((ipc-client-sdk))
        C\[交易服务B\] \-- 使用 \--\> B
    end

    subgraph IPC基础设施
        D(ipc-router)
        E\[NATS JetStream\]
        F(ipc-cli)
    end

    B \-- RPC via MessagePack \--\> D
    D \-- 读写消息 \--\> E
    F \-- 管理命令 \--\> D
