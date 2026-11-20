# P1 第三十七跑：PID_SET_KEY_CLEAR 请求接收与 EE 完成验证

产品已新增 `0x90040193/0x406a/12B` 的独立零回复请求接收槽，按原来源、大小和所有权合同保存请求并释放退休；CP 96 项及22子测试、观察器426项通过。首跑 `13e6` 因槽SID接错失败，已正常退出并保留；修正后的唯一重试正在核收，暂不声明 EE 完成、快门、JPEG 或写卡通过，`capture_verified=false`。

本任务仅在隔离 QEMU 与独立 RAM 卡中执行，不访问真实设备，不写 AP 的 EE、exclusion、镜头或快门状态；用户要求跳过镜头伸出调查，继续遵循。任务复现、源码前像、原始输出和账本位于项目 `scratch/a7c2-capture-p1-runtime-20261115-candidate37/README.md`。不继续委派，报告 flavor=null。

## 实现与原程序合同

candidate36 实际请求为 `05006a402600008000000000`，来源 `0x80020002`，向 `0x90040193` 发送；原 AP 构造函数 `0x3539b0c` 创建12B请求并以全零回复参数调用共享发送函数。语料见 `analysis/appfw-decompile/corpus/parts/7/0x003530000.c:7253`。因此复用现有 `retire_slot`，不构造独立ACK，不保留已经释放的 request 指针，也不把请求退休冒充下层 PID 状态完成。

新增槽保留 first/latest 完整 wire、单调 generation 与语义待处理计数，沿用来源/长度、owner、继承进程、重入、fault、generation溢出、请求释放失败和重复释放守卫。只对原404e/4070槽输出对应的异步专用日志，避免新槽被误记为4070。`NATIVE_CP_BACKGROUND_SLOT_RETIRE` 明确保留 `handler_executed=0 completion=0 backend_missing=PID-key-clear-receiver+key-state original_CP=0 capture_verified=0`。

初始参数表及对齐常量调查未找到消费者，随后沿既有 `scratch/af-handler-identify-kimi/REPORT.md` 找到并直接复核原CP消费者 `0xae1784`，全部窗口摘要和指令保存在 `cp-keyclear-consumer-v2.json`。原命令会条件清除+0x155状态并向后台发0x3024，清23项键记录的有效位（+0x40+12×i），清14项子键记录（包含来源相关释放），再做状态重算；还可能生成0x4039等下层消息。这是有状态且有副作用的清理命令，不能将无回复误解为没有业务语义。当前新增槽只执行运输所有权和保存未执行义务；未实现真实CP对象/来源相关资源/重算后端，因此没有猜测CP基线或虚构这些副作用完成。

## 验证

首跑新增槽错误使用 `NATIVE_CP_BACKGROUND_SID=0x90030001`，实际请求为 `NATIVE_CP_CAPTURE_SID=0x90040193`，因此同一406a请求仍落到原运输并返回−1020。这个实现错误已经修正；新增测试将目的地与字面值0x90040193交叉核对，并将406a加入capture SID的65536 opcode遍历、保持background遍历不接收。首跑原失败、错误构建的derive及源码在`restore/attempt1/`保留，不回填成功。

修正后两检查组、两个线程：

| 检查 | 结果 |
| --- | --- |
| CP接收器、参数族、异步族、退休、4023、4070及still-unlock | 96 passed，22 subtests passed |
| 原始135字段parser、HDMI/UPM协调器及watcher | 426 passed |
| 新406a边界 | 实际wire连续两次、重复地址、释放失败重试、重入/别名、并发、fork、溢出、拒绝错误来源/长度、capture SID全集不误接收 |
| 公开登记 | `test_cp_406a.py` 与扩展的 `test_cp_slot_retire.py` |
| candidate36既有runner基线 | runner源码未改；69项通过/15项旧失败证据沿用，不回填全绿 |

生产observer、CPIO和derive已重建；CPIO仅 `simulation/menu-observe.so` 内容改变，成员集合和权限保持。原HDMI/UPM观察器接线、调试器detach交接及 `MENU_CAPTURE_INHIBIT_TRACE=1` 保留。当前运行使用4字符命名空间与唯一QMP命令ID，实际镜像身份由 `integration/integration-result.json` 和driver绑定核验。

## Evidence → Finding → Path

| Evidence | Finding | 下一步 |
| --- | --- | --- |
| candidate36原406a失败与AP构造语料 | 12B、无回复等待、后台SID | 新槽接管后观察原AP是否继续 |
| `cp-pins.json`、`prepare-failure.json`、`cp-keyclear-consumer-v2.json` | 初始搜索未覆盖capture命令，后续原字节已证实有状态清理与下层消息 | 将精确清理合同交给后续共享release-key模型，不伪造完成 |
| `source-readback.json`、`*.diff`、`restore/` | 仅追加槽和相关检查，已有修改保留 | 父会话核收；按对应前像恢复 |
| `integration/cp-regression.*`、`observer-regression.*` | 相关宿主检查全部通过 | 核对guest实际消费后单独记业务结果 |
| `runtime-1/` | 运行结果待核收 | EE current/shadow、尾部探针、inhibit、4038、JPEG逐项裁决 |

## 边界、恢复与空间

当前未执行真实 CP 固件、Sony loader/WBI恢复或物理硬件；本轮是 direct-bootin 诊断路径。原看门狗禁用的限制不变，不能以此证明完整相机启动或实机快门可靠性。

修改前像和完整摘要在任务 `restore/`、`manifest.json`，旧derive和candidate36原收据保持；`test_cp_opcode_batch.c` 的前像由精确单处改动反算并单独注明，未冒充事前备份。运行收尾、进程/调试器/租约、实际实占和可用字节以本轮最终 `storage.json` 为准；当前未执行回收。
