# 第二条控制连接：InfraImaging type8 OUT0 → InfraBB type8 IN0

`run-en0re8bn`已实际消费第二条type8控制边回复：原AP258/TID381接收唯一56B完成并释放rc0/fault0/ap1，标志01acad0f写入并读回1，posthook mask检查确认零新增DMM/格式副作用，首边数据/格式保持。本轮SD和退出双锁通过；715测试/139子测试、原ABI及独立两边内容复核通过。见[本轮收据](imaging-control-edge-native-proof.json)。`imaging_control_connection_native_verified=true`仅指这条有限虚拟控制边，`capture_verified=false`。

## 实际请求与限定合同

原AP在首边唯一回复消费后查询两个type8端口，实际发送：

```text
target=90050004 source=81cf61c4 bytes=64
c461cf81a0a0a0a0010040001800000040000000000000000010010028000200080000000200000000000000040005900800000001000000000000004a078492
S={8,2,0,90050004}
P={8,1,0,9284074a}
```

类型8和索引0不等于前条type0/index1。独立端口实例仍引用原六端口/21端口registry，不复制或重置旧owner。

| 项 | 原CPVA（raw=VA−108000） |
| --- | --- |
| source构造/表 | b09f06，1109ee4 / 1109f44；slot5属性1109f34→对象1a3a540 |
| sink构造/表 | 6a3918，10ef808 / 10ef958；slot8属性10ef888→对象17894dc |
| source查键与Connect | 46eef4..46ef1c→46f1b0→68b5ca，比较完整三个u32并由owned wrapper核第四SID |
| sink查键与peer Connect | 1d5938..66→1d5da4→68b818 |
| source completion | 46f43e→68b9a6 |
| sink业务标志 | 1d614a/rawce14a字节1154：将01acad0f[0]写1，原初值未知 |
| sink posthook | 1d63de传P→1d6c90；dir1成立，`3fe & (1<<0)==0`，直接1d6cf6返回 |

主会话独立核公开原件f5a47758…、两张属性表/对象表、七段原字节摘要，证据为`imaging-type8-control-source-pins.json`。没有从“type8看起来像控制”推断无副作用；实际分支确实调用posthook并在mask检查处退出。

准入后，source原构造态1→pending2并保存完整peer，sink1→active0保存source，source消费peer回复后2→0、清pending。两个内部消息与唯一AP回复为：

| 消息 | 总/内长度 | `{category,command,length,kind}` | 内容 |
| --- | --- | --- | --- |
| 原AP Connect | 64/40 | 1000/0001/40/2 | S,P |
| peer request | 64/40 | 1000/0100/40/1 | S,P |
| peer reply | 72/48 | 1000/8100/48/1 | S,P,status0,trailing0 |
| AP completion | 56/32 | 1000/8001/32/2 | S,status0,trailing0 |

虚拟内部及AP回复outer replySID为0，OSAL source为相应完整owner SID，AP目的地从本次原请求提取，不能硬编码81cf61c4。消息allocation/lease/free独立，失败不能借正常status0强走完成。

## 保持首边与资源不变

必须先核同PID首边clean/AP已消费、sink index1 marker已知为1、格式实际消费及Free、旧control pool所有allocation均已退役，当前两个type8 Get独立回复均释放、端口仍cold1、无pending/live/fault。

本边实际完成自己的握手、sink index0 marker一次写入/读回和posthook mask检查，**没有**DMM申请、SSYN通知或格式缓存更新。执行前后的首边快照、control pool全部计数及其它registry对象比较一致；测试还核mapped backing字节不变。这里的“无格式副作用”是精确分支合同，不代表整个图或硬件ready。

资源guard6复用已证前置ADF/BB与foreign Speech405/406所有权检查；新日志独立使用`FULL_IMAGING_CONTROL_CONNECT_`，不重复首边验收标签。first/profile仍只允许原先type0边；second关闭时不扩大其权限。

## 开关、实现与检查

```sh
A7C2_IMAGING_CONNECT=virtual-imaging-out1-bb-in1-v1
A7C2_IMAGING_CONTROL_CONNECT=virtual-imaging-control0-bb-control0-v1
```

第二项默认关闭，要求第一项及完整BB/ADF/Backup链、公开ALLLANG、同一a0d候选、256GB目录SD、new UI/firstboot/自然快门/安全导出。guest变量为`MENU_IMAGING_CONTROL_CONNECT`，exact ctor门禁一次owner构造；typed manifest的运行消费、硬件、图像帧和拍摄字段仍为false。

- `imaging-control-connection.c/h`：独立进程owner与私有fault/lease状态，真实sharedregistry握手，marker初值unknown，posthook分支读回、首边保持、唯一回复所有权及同waiterfree。
- `test_imaging_control_connection.py`：109个strict C11/Werror/pedantic/ASan/UBSan场景，复用真实首边/所有ADF/BB前置，包含完整wire/两个动态caller、原cache/backing/pool不变、三处分配故障、坏消息、发送/释放失败、inline/concurrent free、fork、重入快照、并发其它Get的保守拒绝和失败后拒绝重试。
- profile与完整C ctor正反门禁已并行检查，176项/139子测试通过；typed字段不把0与false、列表中的float与int混同。

未排队的失败返回−1021，原request仍由caller持有，provider不保存悬垂retained ownership；已排队后request-free失败才保存retained。另在新确定性线程测试中发现前置旧BB/首边的send-failure与in-flight free可能重复清理，父会话已按同根因加所有权保护并补回归，原正例证据不因此伪改。

## 本轮原运行验收

`run-en0re8bn`使用observer `33c007d39fe35a6e3fd36bd33b8b9bc363e0c55ea82a32f83df9a01a6d5db480`和同a0d候选。console SHA256=`96987312a48d9d5c73a9a23bb1aa088edb8a6e501e5472a172943c094c891fdb`，同轮源归档=`ab6d4e19031aeaafcd4d1402c693cdd8d6e9c0db3448ef823ca5d8e3dca4a275`。初ABI构建冻结281文件，启动器自动重建时捕获一个并行新增但**未链接**的测试文件，归档为282；编译observer SHA完全相同。严格评价器核全部282摘要及归档build脚本，确认third/BBVEF backend未链接，不将其算本轮已执行。

原AP PID258/TID381依次消费首边和type8两笔独立56B回复，消息全文、完整S/P、动态caller、指针与free均吻合。type8的独立marker保留old_value_known0、写1/readback1；mask3fe/index0实查后不执行DMM、通知或cache写。旧首边216B四操作/80B映射内容/16B摘要/cache5/Free仍完整，资源准入pool allocation/release2/2、live0、foreign Speech保持。

本轮双Fsysflush0 seq1455231021916769/1455231957438319、STOP恢复、host三文件尺寸SHA与两export全等、cleancommit和owner225001/其组/QEMU退出/双锁实际独占均通过，无SIGKILL。独立caa复核无P1–P3，核282源/候选/完整wire/全树并在内存中重跑严格评价器，结果与保存的evaluation一致。

原请求后仍有11条Connect明确拒绝，第一条为type3到ADF；302c仍未完成，EE1/0/0、JPEG/MP4为0。GTK整体okfalse保留。现按用户要求并行实现第三音频边和第四BB→VEF图像边，单VM原运行验证仍串行。
