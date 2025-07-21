# **5\. 核心工作流 (Core Workflows)**

## **工作流一：成功的“目标路由”RPC调用**

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

## **工作流二：“主/备”实例的自动故障转移**

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
