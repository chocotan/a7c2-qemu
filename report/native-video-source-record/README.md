# 内部88字节记录区：初始化与start参数交接

这是CPU writer闭合之前的历史调查：当时已证明S88数组初始化、地址/容量返回、start字段、实际消息复制和下层对象保存。后续[CPU writer与通知计划](../native-video-record-fill/README.md)已补齐K2433e0/24b04c源合同，[engine结果构造](../native-video-engine-result/README.md)与[0500发送链](../native-imola-output-source/README.md)另有独立证据。下文“writer未找到”只描述本次早期范围，不否定后继；实际ES/像素生产、同frame完成与native执行仍未验。native gaps=63、capture=false。此时点说明在3249/381冻结批次后补充，运行代码未改。

范围为公开av-cam.bin只读静态分析；无VM、网络、硬件、物理SD或private/full来源。K为raw offset，原KVA=ffffffc001000000+K。完整原件和10窗口见[source-pins.json](source-pins.json)。

## 数组初始化和地址来源

K15ed88清零C+210c0开始的63420字节，再保存u64[C+8b450]=C+210c0、u32[C+8b458]=63420。K15f414向调用者返回该u64基址和u32容量120c，即4620个58字节记录。K14fcd4对owner加a0再进入getter；K1363f0实际调用它，K1363fc/136400把结果写到start参数P+8/P+10。

这里所有数字均为十六进制，除明确标注4620外。**S88步长58=88字节；下面start参数88=136字节，是两个不同尺寸。** 数组的零初始化不是有效编码输出。

## 已证明的start字段

P为K1363a4局部sp+18。所有指针保持u64。

| P字段 | 宽度与实际来源 |
|---|---|
| +0 | u32，owner descriptor+8的u8零扩展 |
| +8 | u64，S88数组基址 |
| +10 | u32，记录容量120c（4620） |
| +18 | u64，独立picture-info区getter K15f3f8返回的C+8b438 |
| +20 | u32，picture-info容量28（40） |
| +28 | u64，调用对象B+20；原日志名es_initial_wp(phys) |
| +30 | u64，zero_extend(W32(config[+5c]<<3))；原日志名initial_hrd_buffer |
| +38 | u32，config+54；原日志名pts_initial_value |
| +3c | u32，K136594返回值 |
| +40 | u32，显式写零 |
| +44/+48 | K1395a0输出位置，内容未闭合 |
| +70 | K139790输出位置，内容未闭合 |
| +76 | u8，调用参数a4&1 |
| +77..82 | 从a5实际复制c字节 |
| +84 | u32，u8[B+a8]==1 |

未列字段、padding及helper输出均不能补零。上表不授权把整个start参数标为已知。

## 实际消息与下层保存

K136e1c内层消息头为`0321020190000000`：u16 2103、u16 0102、u16长度90、u16零。K136e48实际copy(M+8,P,88)。于是记录区指针和容量位于内层M+10/M+18。

K94760→9479c添加18字节外层信封，总长a8；K970fc把a8字节实际复制到分配的发送缓冲R，再于K97114调用K2ef9c。内层M位于R+18。这是复制与发送源数据流，不是实际接收/完成。

下层K245ecc检查channel，command102分支调用K24d884，其state4路径经K250a88进入K2482bc；运行态state4未证明。该方法令T=O+20，在K2485d0调用K24259c执行copy(T+7a8,P,88)。因此下层快照的u64[T+7b0]保存S88指针，u32[T+7b8]保存容量；这仍是保存配置，不是写其指向的记录区。

## 第一处未闭合数据生产

K165ce8只复制24字节回调参数，再调用K160614。后者以u32[E+0]索引选择S88：完整u64基址+zero_extend(index)*58；原源没有索引界限检查。尚未证明该索引由哪个IRQ/完成事件生成，或与某个frame identity对应。

精确缺口是T+7b0指向的记录区：谁写入有效AU地址、长度、flags、PTS/DTS和其他字段，怎样在E索引通知之前变得可见。没有CPU writer、DMA/MMIO注册、硬件描述符到S88 copy或payload lease的完整证据。不得用初始化的零记录和start参数复制替代。

E1（初始化/getter）→F1（数组地址与容量）；E2（实际start字段和消息copy）→F2（配置运输）；E3（下层保存和24B回调）→F3（记录填充/通知关系仍缺）。10个窗口共4324字节经完整原件摘要和主会话独立读回核对。既有[88→96模型](../native-video-producer-contract/README.md)仍要求调用者提供完整、有效、有来源的88字节快照，不自动接收这块尚无生产证据的数组。
