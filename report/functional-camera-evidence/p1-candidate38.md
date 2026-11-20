# P1 第三十八跑：set_trinity_mode 参数接收与资源快照前沿

产品已实现 `0x90030001/type5/0x40ee/12B` 原始参数接收：从请求 `+8` 读取字节并写入参数 `+0x180` 的32位值，标记共同 dirty，按原来源/尺寸/所有权规则释放请求，无独立ACK。相关 CP 96 项及22子测试、观察器426项通过，guest `a79b` 已实际消费该请求并继续；之后停在人脸资源源快照服务 `rc=-95`，尚未完成 EE、快门或JPEG，`capture_verified=false`。

本任务按父会话授权完成，不继续委派。只使用独立QEMU、RAM卡和既有原AP输入，不连接真实设备，不修改AP的EE/exclusion/镜头/快门值；镜头伸出调查按用户要求跳过。任务入口、精确前像、原始日志和账本在 `scratch/a7c2-capture-p1-runtime-20261115-candidate38/README.md`，报告flavor=null。

## 原始合同与实现

CP SHA256固定为 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。表项 `0x10fbca8` 为 `(0x40ee,0x359e89,0,0,0x364b01)`；handler `0x359e88` 是 `ldrb request+8 → str.w [P+0x180]`，随后仅条件调试输出并返回1。checker `0x364b00` 只在条件下比较已存值并记录差异，不构成值域限制。共同dispatcher对apply-control=0调用dirty setter `0x996fec`，因此不能因handler本身没有调用apply就省略dirty。周期apply消费尚未闭合，日志保持 `apply_completed=0 completion=0`。

AP构造器原VA `0x3538160`（语料命名带额外0x100000为`FUN_03638160`）构造12B，以全零回复参数向`0x90030001`发送。交接文字把此SID称为capture，但产品常量和实际wire均确认它是background；`0x90040193`才是capture。本轮实际请求为 `0500ee402600008000000000`，来源`0x80020002`。

实现复用已有参数owner和`STORE_BYTE`，新增一个表项，不新增抽象或未消费槽；保留fork/并发/release失败/来源/尺寸等守卫。日志增补`handler_executed=1`，只表示该参数handler执行，不表示真实CP、硬件apply或capture已通过。

## 验证与原失败保留

两组检查、两线程：

| 检查 | 结果与实际范围 |
| --- | --- |
| CP接收、参数、退休、异步族、still-unlock | 96 passed，22 subtests passed |
| 原135字段parser、HDMI/UPM协调器与watcher | 426 passed |
| 40ee扩展检查 | 256值、全config value/known/wire逐字节比较、错误来源/尺寸/目的地/type、release失败重试、重入、fork、65536 opcode遍历、实际wire连续重放 |
| 公开入口 | 扩展`test_cp_opcode_batch.py`并补登记public-model-tests.json |
| 最终生产构建 | `integration-final/integration-result.json`绑定observer/CPIO/derive SHA；CPIO仅menu-observe.so改变，成员和mode保持 |

首轮构建遗漏共同dirty标记，在VM启动前发现，原`integration/`和derive保留为前一版构建证据；修正后独立构建`integration-final/`，没有回填旧收据。

首跑`a79b`已实际记录`NATIVE_CP_BACKGROUND_PARAMETER_ACCEPT opcode=0x40ee parameter_offset=0x180 parameter_bytes=4 value=0 apply_marked=1 request_free_rc=0 handler_executed=1`。随后原AP创建三个face DMM creator并进入API40源快照；broker第197项收到opcode11/1168B，第198项返回`actual_source_result=-95`，guest保留fault。根因是旧诊断runner只给QEMU child配置functional profile，broker却从宿主`os.environ`校验双profile，未启用即按设计拒绝。此结论没有涉及真实人脸算法故障或原CP运行结果。

首跑QEMU通过正常QMP quit退出，rc0、无信号、租约到退出，调试器/mailbox detach且broker cleanup无错误；业务状态仍failed。唯一重试`runtime-2/`沿用同一最终构建，显式给宿主和guest设置相同functional profile并断言相等，未改产品校验或降低资源边界。重试结果待最终核收。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| `cp-40ee-consumer.json`、`source-verification.json`、AP构造语料 | 40ee是后台12B参数写入，带共同dirty，无独立ACK | 接入现有参数owner，独立记录apply未完成 |
| `manifest.json`、`restore/`、`source-readback.json`及diff | 最小变更且保留既有修改和精确恢复点 | 父会话按逐文件diff核收，勿整树覆盖 |
| `integration-final/cp-regression.*`、`observer-regression.*` | 宿主相关检查通过 | 与guest真实消费分别记账 |
| `runtime-1/`、`a79b`原broker和console | 40ee已越过；宿主source profile未启用造成-95 | 保留失败，独立重试配置一致性 |
| `runtime-2/` | 运行验证中 | 核EE写1、exclusion1294→1295、自然快门4038、JPEG与释放链，不以运输成功替代 |

## 覆盖、恢复与空间

仍是direct-bootin诊断路径，不执行真实CP固件、Sony loader或WBI恢复，原看门狗禁用的限制保持；不能用于证明实机完整启动或拍摄可靠性。已有candidate36 runner旧69通过/15失败基线不变，本轮未重跑或回填该无修改基线。

源码前像及摘要在任务`manifest.json`；旧失败和构建身份均留存。新增/保留实占、文件系统可用字节、进程/租约/调试器收尾以最终`storage.json`记录；当前未执行回收，测试输出、构建收据和运行现场保留供父会话核收。
