# **AegisIPC 分布式交易系统IPC原型 \- 架构文档**

## **1\. 介绍**

本文档概述了“分布式交易系统IPC原型”的整体项目架构。其主要目标是为AI驱动的开发提供指导性技术蓝图，确保系统实现的一致性、可靠性与高性能，同时严格遵循“精简可靠”的设计原则。

## **2\. 顶层架构设计 (High Level Architecture)**

### **技术概要**

本系统是一个基于消息队列的异步、高性能进程间通信（IPC）基础设施。其核心技术采用NATS JetStream作为通信骨架，提供持久化的消息传递能力。所有通信内容将采用MessagePack信封格式进行序列化，并深度集成Pydantic进行灵活的、带数据校验的RPC（远程过程调用），以支持任意Python对象类型的传递。整体架构遵循六边形/领域驱动设计原则，确保业务逻辑与技术实现的彻底解耦。

### **架构模式**

* **异步消息驱动 (Async Message-Driven)**: 系统核心为异步模式，服务间通过消息解耦。
* **请求/响应模式 (Request/Reply)**: 在异步消息之上构建可靠的RPC模式。
* **发布/订阅模式 (Publish/Subscribe)**: 支持多对多的通信拓扑。
* **主/备高可用 (Active/Standby HA)**: 关键服务采用“先到先得”的原则确定主备角色，实现自动故障转移。
* **六边形/领域驱动设计 (Hexagonal/DDD)**: 严格分离领域、应用和基础设施层。

## **3\. 技术栈 (Tech Stack)**

| 类别 | 技术 | 版本 | 目的 | 理由 |
| :---- | :---- | :---- | :---- | :---- |
| **消息中间件** | NATS JetStream | 最新稳定版 | 核心通信骨架 | 高性能、低延迟、运维精简、支持持久化 |
| **序列化格式** | MessagePack | 最新稳定版 | RPC消息序列化 | 高性能、紧凑的二进制格式，跨语言 |
| **数据契约** | Pydantic | v2+ | 数据校验与转换 | 遵循契约驱动开发，与业务代码无缝集成 |
| **开发语言** | Python | 3.13 | 服务与SDK开发 | 项目要求 |
| **容器化** | Docker | 最新稳定版 | 环境一致性 | 遵循容器化开发与部署原则 |
| **工程工具** | uv, Black, Ruff, Mypy | 最新稳定版 | 依赖管理与代码质量 | 遵循现代化工程实践原则 |
| **测试框架** | Pytest | 最新稳定版 | 单元与集成测试 | 强大的Python测试生态 |
| **管理工具CLI** | Typer / Click | 最新稳定版 | 创建管理命令行 | 快速构建健壮的CLI工具 |

## **4\. 组件 (Components)**

* **IPC路由核心 (ipc-router)**: 系统的“大脑”，负责服务注册/发现、健康检查、消息路由和主备切换协调。
* **客户端SDK (ipc-client-sdk)**: 系统的“接口”，封装所有通信复杂性，提供给业务服务使用的、可安装的Python库。
* **管理命令行 (ipc-cli)**: 系统的“管理工具”，用于查询系统状态和执行管理操作。
* **持久化层 (Persistence Layer)**: ipc-router内部的逻辑层，负责与NATS JetStream交互，实现“精确一次投递”。

### **组件关系图**

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

## **5\. 核心工作流 (Core Workflows)**

### **工作流一：成功的“目标路由”RPC调用**

Code snippet

sequenceDiagram
    participant ClientApp as 交易服务A
    participant SDK as ipc-client-sdk
    participant Router as ipc-router
    participant NATS as NATS JetStream
    participant TargetApp as 目标服务B

    ClientApp-\>\>+SDK: call("service\_b.do\_work", resource\_id="acc\_XYZ", ...)
    SDK-\>\>+Router: PUBLISH(req\_topic, {call\_id, target, args})
    Router-\>\>NATS: 确认消息持久化
    Router-\>\>Router: 查询路由表: "acc\_XYZ" \-\> "instance\_B1"
    Router-\>\>+NATS: PUBLISH("instance\_B1\_inbox", {msg})
    NATS-\>\>-TargetApp: DELIVER(msg)
    TargetApp-\>\>TargetApp: 处理业务逻辑...
    TargetApp-\>\>+SDK: return result
    SDK-\>\>-Router: PUBLISH(reply\_topic, {call\_id, result})
    Router-\>\>Router: 根据call\_id查找返回地址
    Router-\>\>+NATS: PUBLISH("client\_A\_reply\_inbox", {msg})
    NATS-\>\>-ClientApp: DELIVER(msg)
    ClientApp-\>\>ClientApp: 收到结果

### **工作流二：“主/备”实例的自动故障转移**

Code snippet

sequenceDiagram
    participant ActiveService as 主实例 (Active)
    participant StandbyService as 备实例 (Standby)
    participant Router as ipc-router

    loop 心跳检测
        ActiveService--\>\>Router: Heartbeat
    end

    Note over ActiveService, Router: 主实例网络故障，心跳停止

    Router-\>\>Router: 心跳超时，检测到故障
    Router-\>\>Router: 将"主实例"标记为不健康
    Router-\>\>Router: 查询"备实例"并提升为新的"主用"
    Router-\>\>StandbyService: (可选)通知其成为Active

    Note over Router, StandbyService: 路由表更新，所有新请求\<br/\>将发往新的主实例

## **6\. 代码目录结构 (Source Tree)**

系统采用单体仓库（Monorepo）结构进行管理：

Plaintext

ipc-project/
├── .github/
│   └── workflows/
│       └── ci.yaml
├── docs/
│   ├── prd.md
│   └── architecture.md
├── packages/
│   ├── ipc\_client\_sdk/
│   │   ├── ipc\_client\_sdk/
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── ipc\_router/
│   │   ├── ipc\_router/
│   │   │   ├── api/
│   │   │   ├── application/
│   │   │   ├── domain/
│   │   │   └── infrastructure/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── ipc\_cli/
│       ├── ipc\_cli/
│       ├── tests/
│       └── pyproject.toml
├── docker-compose.yaml
├── pyproject.toml
└── README.md

## **7\. 测试与部署策略**

* **测试策略**: 采用单元测试、集成测试、性能测试的分层模型。集成测试将在CI环境中通过Docker Compose启动真实依赖（NATS）进行。
* **部署策略**: 采用完全容器化的方式。核心部署单元是ipc-router的Docker镜像。通过CI/CD流水线实现自动化测试、构建和部署，覆盖开发、预发布和生产三个环境。

## **8\. 错误处理与编码规范**

* **错误处理**: 所有RPC错误通过统一的Pydantic模型在消息信封的error字段中返回。客户端SDK负责将此错误模型转换为Python自定义异常，供业务代码通过try...except捕获。
* **编码规范**:
  1. **Pydantic契约为先**: 跨服务传递的数据对象必须先在共享的Pydantic模型中定义。
  2. **SDK是唯一入口**: 所有IPC交互必须通过ipc-client-sdk。
  3. **显式错误处理**: 所有远程调用必须使用try...except块进行包裹。