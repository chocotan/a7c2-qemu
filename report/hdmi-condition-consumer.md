# HDMI 第 11 条：真正的条件通知消费者

> 结论：**本次不新增 `hdmi-notify-observer.c/.h`。**公开 ALLLANG 的目标消费者已找到，是 appFw 的 `task_hdmi` 阻塞接收循环，不是得到队列绑定证据的注册回调。现有 W2 的成功 `osal_rcv_msg_tmo` / `u_osal_rcv_msg_tmo` 后观察点覆盖这条原始路径；仅证明通用回调 ABI 不足以安全替换它。
> 本文是静态原件证据，不是运行验收；`runtime_observed=0`、`ready_asserted=0`、`hardware_verified=0`、`capture_verified=0`。

## 范围与交付

- 授权范围：只读 `runtime/analysis/menu-root/` 的公开官方 ALLLANG ELF，以及已存在的 appFw 反编译语料。网络访问、真机、物理 SD、完整 dump、私有配置、VM 启动均未进行。
- 只新增本文、[字节清单](hdmi-condition-consumer-byte-pins.json)和[独立校验代码](hdmi-condition-consumer-byte-pins.py)；未改 `menu-observe.c`、构建脚本或任何既有生产输入。
- 该校验代码读取原件，核对完整 SHA256、22 个精确原字节窗口、6 个 AArch64 BL 目标和条件映射；`--self-test` 另外检查 26 个否定用例。它不执行固件、不注册接收器、不发送消息、不释放消息、不改变 ready。
- 主会话的旧 317 输入/运行记录不能覆盖本次新报告/校验代码；也不作此主张。

## 原件身份、导入与导出证据

所有地址为原始 **ELF VA**。本清单选中的窗口全部位于 `VA == file offset` 的文件段；不套用 Ghidra 的 `+0x100000`。CP 的既有 `raw+0x108000` 规则与此不同，本次没有重做 CP 生产者。

| 原件（相对 menu-root） | 字节数 | SHA256 |
|---|---:|---|
| `usr/lib/appFw.so` | 99960744 | `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b` |
| `usr/lib/libosal_uipc.so` | 43752 | `09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3` |
| `usr/lib/libInfraAvbbc.so` | 1738760 | `676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5` |

**E-imports / E-exports**：使用 `aarch64-linux-gnu-objdump -T` 检查。appFw 导入 `osal_reg_msg_queue_cb`、`osal_reg_sync_msg_queue_cb`、`osal_rcv_msg_tmo`、`osal_free_msg`；因此不能用“存在回调导入”证明目标队列经回调投递。libosal_uipc 导出这些公共接口及对应 `u_osal_*`，导入 `ioctl`、`pthread_*`、`malloc/free`。libInfraAvbbc 导入上述 OSAL 接口，导出 `BizDataflowInfraReceiver::RegSyncCb(unsigned int, void**, void (*)(void*, void*), void*)`、`ReceiveASync` 和 `InfraAvbbcMsgManager::OsalRcvMsg`。这些是可读的 ELF 动态符号，不是猜测出的 C 原型。

## 真正的接收与释放链

### E-AP-subscribe：0127 绑定的是 payload SID

appFw `0x34ecc80..0x34eccd8` 构造 12B 请求：

```text
{u16 0x2500, u16 0x0127, u16 12, u16 1, u32 0x802a0116}
       002527010c00010016012a80
```

`0x34eccb4` / `0x34eccb8` 建立 `w0=0x802a0116`，`0x34eccbc` 保存到请求 `+8`；`0x34eccc4` 调用 `0x34e4fe4`。这与请求 source `0x81cf618c` 不是同一身份。公开这个版本把 SID 写成字面值；虚拟 owner 仍应以**实际成功的 0127 payload**绑定，不能把这一个版本的常量硬套到所有输入。

### E-AP-consumer：task_hdmi，不是 callback

复用既有语料：`analysis/appfw-decompile/corpus/parts/7/0x0034e0000.c:4580..4629`，然后用原 ELF 逐条核验：

| ELF VA | 原始行为 |
|---|---|
| `0x34e3f90`, `0x34e3fa8` | `w22=0x802a0116` |
| `0x34e3f94`, `0x34e3fac` | `w24=0x91ca0816` |
| `0x34e3fb4..0x34e3fc4` | `osal_rcv_msg_tmo(w22, &message, -1)`；真实 BL 目标 `0x165e940@plt` |
| `0x34e3fc8..0x34e3fd4` | `osal_get_msg_src(message)`，与 `0x91ca0816` 比较；非匹配消息也进入原 free |
| `0x34e406c..0x34e408c` | 取原 payload `+4` 的 condition ID，减 `0x11`，范围/使能表过滤，再读映射表 |
| `0x34e4090..0x34e40b4` | 分配 16B 原生模型事件：word0=`0x179`，word1=`0`，word2=映射 ID，byte12=`payload[8..11] != 0`；调用原事件发布函数 |
| `0x34e40b8..0x34e40c4` | `osal_free_msg(w22, message)`；BL `0x1660350@plt` 后回到同一接收循环 |

源码字符串 `void infra_wrapper_bb::detail::task_hdmi(void*)` 是函数定位证据。它是**线程入口签名**，不得据此当成 OSAL 队列回调。原循环不检查 receive 返回码即读 source；观察代码必须保留自己的“真实接收成功”守卫，不应照抄这种未验证读取。

### E-AP-launch：真实线程创建

`0x34e6730` 的 initialize 尾部在 `0x34e68c4` 设线程索引 `0x40`，`0x34e68cc/0x34e68d0` 载入 `0x34e3f7c`，参数为 0，`0x34e68d8` 调用 `0x36ec384`。后者进入 `0x36ec1c4`，将入口/参数保存在该线程描述符 `+8/+16`，最终 `0x36ec318` 调用 `osal_create_waitable_thread@plt(0x165dbd0)`。这是启动 task_hdmi 的证据，不是 `osal_reg_*` 的证据。静态可达不证明当前某次 VM 已执行 initialize。

### E-AP-map：24 次接收不等于 24 次模型发布

`0x4c670f0` 的 32B 使能表及 `0x4c67110` 的 32 个 u16 映射：

| condition ID | 原生模型参数 |
|---|---|
| `0x11..0x17` | `0x0f7b..0x0f81`（依次对应） |
| `0x21`, `0x22`, `0x23` | `0x0f82`, `0x0f83`, `0x0f84` |
| `0x30` | `0x005a` |
| `0` | 不发布模型事件，但仍由原循环 free |

既有两轮生产者顺序 `0,17,16,15,14,13,12,11,23,22,21,30`（十六进制）进入该循环时，每轮 12 次 receive/free、11 次原生模型事件；两轮不得去重。**22 次模型发布不是漏收 2 条**，但不能仅见发布次数就认定 24 条的原始 pointer/lease 都已释放。这里是由原代码得出的预期，不是新运行记录。

## OSAL 回调 ABI：已知和仍未证明的边界

**E-OSAL-ABI**：libosal_uipc `0x4d38` 是本地队列适配器：解锁 `ctx+56`，从 entry `+32/+40` 载入 callback/userarg，以 `x0=header+24, x1=userarg` 调用，随后重新加锁并固定返回 0。`0x5bd8` 与 `0x6be0` 分别保存 sync/async 注册的 callback/userarg，并在 entry `+16` 安装该适配器。libInfraAvbbc 的真实 mangled 导出签名进一步证实 `void (*)(void*,void*)` 返回 void。这里不应把外层适配器固定返回的 0 当成用户回调返回值。

但是，目标 `0x802a0116` 的 bit15=0，公共 registration/receive 走 `u_osal_*` 分支，不是 bit15=1、bit31=0 的本地适配器分支。`u_osal_reg_*` 把完整 ID、handle 输出地址、callback、argument 交给 ioctl。真正用户态内核队列 worker 是 `0x3260`：成功 ioctl 后 `0x32e8..0x32f0` 从返回的记录装载 callback、argument 和 message，再间接调用；并不走公共 `osal_rcv_msg_tmo`。

**纠正先前线索**：`0x2f40` 是 OSAL 诊断/统计输出回调，可见 `osal_get_uipc_stat`、`msgq_dump`、`bsem_dump` 等；它不是目标通知的 stream decoder。`0x2ec0` 在首次注册时安装的就是这个诊断回调。不能沿这条支线推导 HDMI 消费者。

**实际缺口**：未发现把某个 callback 注册到成功 0127 所选 SID 的原始绑定证据；已找到的原始目标恰好是阻塞消费者。因此“通用 ABI 已知”不满足“实际目标 callback delivery 已证实”的门槛。`libInfraAvbbc.rodata+0x16b740` 的 SID 命中及 `OsalRcvMsg` 的通用循环都不足以替代这条绑定。

REA/Kuna 的 `0x4d38` 反编译证据 ID：`ev_1fd6ef2f5c8ac1a2126fd15603a58d8664046c009fc9547ef6c2a15d760e9fc1`。Provider 是本机 Kuna 1.892；伪代码只作重建，关键结论均与原字节相核。首次 REA 调用因未配置 `REA_KUNA_COMMAND` 返回 `provider_unavailable`；改为该调用内 `REA_KUNA_COMMAND=/usr/bin/kuna` 后成功，未安装软件或修改配置。

## 对主会话的集成结论

现有 `native_hdmi_video_received` 在真实成功 receive 后调用 `full_hdmi_video_state_observe_receive(id, original_pointer, real_get_source(pointer), real_msg_size(pointer))`，公共/底层嵌套通过 TLS depth 避免重复；原 free 钩子仍负责同 TID、原 pointer/lease 的退休。libosal_uipc `0x7e08` 从 payload `-8` 读实际 size，`0x7e28` 从 `-12` 读 source；不能用调用者意图替代这些元数据。

1. **不需要为这个公开接收循环新增回调 shim**，也不能捕获整个 family 后把未知 callback 强转。注册 handle、错误码、取消注册、回调参数/返回值均不应受本次调查影响。
2. 若 W2 运行仍没有这 24 条接收，后续只需查 `0x34e6730` initialize / task 索引 `0x40` 是否真正启动、真实 0127 SID 是否与该任务一致、真实 send/receive 元数据；这是下一次主会话运行的诊断范围，不是本次已验证结果。
3. 必须保留 A owner 的 `24 condition + 2 UPM`、实际 receive、同线程成功原 free、pointer/lease 一致性与全部 fail-closed 条件。不能把原生模型发布、producer send 成功、provider cleanup 或泛 callback 返回 0 改写成 ready。UPM 由另一工作项处理，本次未扩展到 `k_psave_api`。

## Evidence → Finding → Path

| Finding | 严重性 | Evidence | 状态 / 置信度 |
|---|---|---|---|
| F1：公开目标条件消费者是阻塞 task_hdmi | n/a_re | E-AP-subscribe、E-AP-consumer、E-AP-launch；精确窗口见 JSON | 静态已核 / high |
| F2：条件 0 只释放，另 11 项每轮发布；不能去重 | n/a_re | E-AP-map、E-AP-consumer | 静态已核 / high |
| F3：通用 callback ABI 不能证明目标 callback 绑定 | n/a_re | E-OSAL-ABI、E-AP-consumer、E-imports/exports | 否定结论已入档；未知绑定保持 unknown |
| F4：既有成功 receive 观察点无需额外 callback 代码覆盖这条原始路径 | n/a_re | E-AP-consumer；只读核对当前 W2 包装代码 | 集成建议；当前新运行未测 |

**P1（callflow）**：initialize `34e6730` → task 创建 `34e68d8` → `task_hdmi 34e3f7c` → 成功真实 receive（W2 观察）→ source/ID 过滤 → 可选原生模型发布 → 同循环真实 free（A owner 退休）→ 下一次 receive。

**Timeline 摘要**：① 核验公开原件/导入导出；② 分清 OSAL 本地 trampoline、内核 worker 与无关诊断回调；③ 复用 appFw 语料并核对真实 0127/task/free 原字节；④ 核验模型映射、线程创建、元数据读取；⑤ 交付新 bytepins 代码及否定 mutation 自检，不动生产/VM。

## 独立复现

在本成果目录（`report/2026-10-17-qemu-native-camera/`）执行：

```sh
python3 report/hdmi-condition-consumer-byte-pins.py --self-test
# 独立公开资产可显式选 root；缺文件、私有/不同版本摘要均失败，不回退：
python3 report/hdmi-condition-consumer-byte-pins.py --root runtime/analysis/menu-root
B=runtime/analysis/menu-root/usr/lib
aarch64-linux-gnu-objdump -d --start-address=0x34e3f7c --stop-address=0x34e40c8 "$B/appFw.so"
aarch64-linux-gnu-objdump -d --start-address=0x34ecc80 --stop-address=0x34eccd8 "$B/appFw.so"
aarch64-linux-gnu-objdump -d --start-address=0x32cc --stop-address=0x3318 "$B/libosal_uipc.so"
aarch64-linux-gnu-objdump -T "$B/libInfraAvbbc.so" | c++filt | grep 'RegSyncCb'
```

通过结果：`HDMI_CONDITION_CONSUMER_BYTE_PINS_PASS`，3 个原件、22 个窗口、26 个否定检查；`condition_callback_binding_proven=false`、`ready_asserted=false`。自检只在内存副本中改动字节，没有写原件。

未进行 VM、真机或当前冻结构建的功能回归；仅该证据校验通过不能宣称 HDMI 第 11 条、UPM 释放或拍摄链完成。
