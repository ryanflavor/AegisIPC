# **项目简报: AegisIPC (分布式交易系统IPC原型)**

## **1\. 执行摘要 (Executive Summary)**

本项目旨在设计并构建一个名为“AegisIPC”的、用于分布式交易系统的高性能进程间通信（IPC）组件原型。该原型专注于解决传统RPC模式扩展性不足以及异步通信中消息丢失的致命问题。它将以NATS JetStream为核心通信骨架，通过一个精简的、原生集成Pydantic的客户端SDK，提供支持多对多拓扑、保证“精确一次”消息投递、并具备自动故障转移能力的高可用通信底座。

## **2\. 问题陈述 (Problem Statement)**

现有的点对点RPC模式无法满足分布式交易系统多服务间灵活通信的需求。先前基于ZeroMQ的异步改造尝试，因其“发后不管，异步取回”的机制存在请求与响应解耦带来的消息丢失风险。在交易系统中，任何消息（特别是交易指令的执行回报）的丢失都是不可接受的，可能导致资金损失或策略失效。因此，当前的核心问题是：如何构建一个既能支持多对多拓扑、具备高性能，又能提供可靠消息投递保证的进程间通信组件。

## **3\. 解决方案构想 (Proposed Solution)**

我们将构建一个由中央路由服务(ipc-router)和客户端库(ipc-client-sdk)组成的稳定可靠的IPC基础设施。其核心特性将包括：

* **多对多通信模型**: 支持服务发现和灵活的服务组/目标路由。
* **可靠的异步请求/响应**: 通过ACK确认和幂等消费者机制，实现“精确一次”投递保证。
* **高性能**: 满足低延迟和高吞吐量的交易场景需求。
* **清晰的客户端API**: 深度集成Pydantic，提供简洁、类型安全的API，让业务服务可以轻松地发起调用并安全地获取结果。
* **易于集成**: 提供一个轻量级、依赖少的Python客户端库 (SDK)，可以被现有项目以最小的代码改动快速集成。
* **高可用性**: 支持主/备服务模式和自动故障转移。

## **4\. 目标用户 (Target Users)**

* **主要用户**: 交易系统后端服务的**开发人员**。他们需要一个简单、可靠的工具来处理服务间的通信，而无需关心底层的复杂性。

## **5\. 目标与成功指标 (Goals & Success Metrics)**

### **项目目标 (Project Objectives)**

* 验证一个基于NATS JetStream和Pydantic的、可靠、高性能、多对多的IPC架构方案的可行性。
* 产出一个可被其他开发者轻松集成的客户端库（SDK），证明该方案的可用性和开发者友好性。

### **开发者成功指标 (Developer Success Metrics)**

* **集成效率**: 一个新开发者能在30分钟内理解其API并成功将一个服务接入到通信网络中。
* **API直观性**: 客户端API感觉就像是进行一次本地方法调用，无需处理复杂的异步回调逻辑。
* **可靠性信心**: 经过压力测试后，开发团队对“消息不会丢失”这一核心保证建立了高度信任。

### **关键性能指标 (Key Performance Indicators \- KPIs)**

* **消息延迟 (Latency)**: P99延迟 \< 5ms。
* **吞吐量 (Throughput)**: \> 200 TPM，且架构支持水平扩展。
* **可靠性 (Reliability)**: 在长时间压力测试中，消息丢失率必须为 **0%**。

## **6\. MVP范围 (MVP Scope)**

MVP的范围将通过三个核心史诗（Epics）来交付：

1. **Epic 1: 核心路由与可靠投递**: 构建项目基础框架，实现服务注册发现、两种核心路由模式，并完成“精确一次投递”的核心逻辑。
2. **Epic 2: 高可用与故障转移**: 增加主/备实例的健康检查、状态同步和自动故障转移机制。
3. **Epic 3: 可观测性、可管理性与性能验证**: 实现结构化日志、性能指标暴露、管理接口，并执行性能基准测试。

**范围之外**: 复杂的分布式事务协调器（如Saga）、图形化的管理界面、服务间的认证和加密等安全性功能。

## **7\. 技术考量 (Technical Considerations)**

* **架构范式**: 采用基于消息队列的异步架构，遵循六边形/领域驱动设计原则。
* **核心技术**: 通信骨架采用 **NATS JetStream**。
* **序列化格式**: 采用 **MessagePack** 包装的、原生集成 **Pydantic** 的RPC消息“信封”格式。
* **项目结构**: 采用单体仓库（Monorepo）结构，包含ipc-router, ipc-client-sdk, ipc-cli等多个独立的Python包。
* **部署**: 采用完全容器化的方式，通过CI/CD流水线进行自动化测试与部署。

## **8\. 制约与假设 (Constraints & Assumptions)**

* **制约**: 客户端库必须是Python；消息传递的可靠性是最高优先级。
* **假设**: 服务将部署在同一个数据中心内的低延迟、受信任的网络环境中。

## **9\. 风险 (Risks)**

* **主要风险**: “精确一次投递”和“无缝高可用切换”的技术实现复杂性较高，需要在集成测试中进行充分验证。




###
/BMad:agents:sm *draft-next-story, ultralthink

/BMad:agents:po *validate-next-story '/home/ryan/workspace/github/AegisIPC/docs/stories/1.2.story.md'，ultralthink

/BMad:agents:dev is running… *develop-story '/home/ryan/workspace/github/AegisIPC/docs/stories/1.1.story.md'，ultralthink,be careful and make the repo productive level.

/BMad:agents:qa *review '/home/ryan/workspace/github/AegisIPC/docs/stories/1.1.story.md',ultralthink
