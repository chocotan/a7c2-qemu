# 虚拟 CP bring-up：远端发送器架构与 capture-only tap

> **当前更正**：`cp_emulation.c` 的 generic ACK / 帧通知原型已停用，运行入口拒绝
> `MENU_CP_EMULATION`。`0x1118` 是面板配置完成，`0x341a044` 是人脸登记业务；
> 下方追加历史记录关于“liveview 帧交付闭合”的结论作废。
> 请先读 [协议更正与原序列实验](PROTOCOL-CORRECTIONS.md)。独立 capture-only tap 仍仅是诊断。

本目录是虚拟 CP（co-processor）bring-up 的成果。当前为 **capture-only 诊断**，不是真实 CP，
不产生帧、不冒充 CP 在工作。

## 架构发现（main 已核，详见 ../imaging-pixel-contract/ICDT-REQUEST-COMPLETION.md）

AP→CP 队列消息（如成像队列 `0x92840747`）经 `osal_snd_msg` 远端路径路由：queue ID 若
bit31 置位且子系统位（0x70000000）非零，调用**远端发送器**。该发送器由
`osal_reg_public(fn)` 注册，真实属主是 `pcie-if.ko`（用 `pcidma_transfer_async` 把消息经
PCI DMA 送到 CP）。发送器签名 `sender(queue_id, message) → long`（x0=qid、x1=msg）。
发送器为 NULL 时内核打 `No snd_msg registered. Skip snd to 0x%x`——menu 运行里 0x747 即此黑洞。

## 两条 bring-up 路线

- **路线 A（完整）**：装载 `pcie-if.ko`+`pcieatu.ko`+`pci_ep_cp.ko`（需 PCIe/interchip 模型与
  虚拟 CP endpoint），让 pcie-if 注册发送器并建真实链路。工程量大。
- **路线 B（最小，本目录）**：自定义诊断模块调 `osal_reg_public(自研 sender)` 接管 CP 队列。
  合法普通 insmod（不 force vermagic），把黑洞变成可捕获的真实帧请求协议。

## sender-client/（capture-only tap）

`sony_virtual_cp_send.ko`（3872B，imports `{osal_reg_public, printk}`，resident）。注册自研远端
发送器，对每个远端 CP 队列发送打 `VIRTUAL_CP_SEND: n=<i> qid=<id> size=<n> b=<前24字节>` 到
内核日志（menu probe 的 console 捕获）。**它只捕获，不投递、不伪造响应**——AP 成像链可能在
等待回复时阻塞。这是为了先看清楚 AP 到底向 CP 要什么，再决定如何建模 CP 应答。

## 使用

```bash
cd report/virtual-cp/sender-client && bash build.sh   # 构建 + ABI 校验
cp sony_virtual_cp_send.ko ../../../runtime/analysis/menu-root/simulation/
cd ../../../runtime/analysis
MENU_VIRTUAL_CP_SENDER=1 bash run-menu-probe.sh       # 需 --load-ipc（run-menu-probe.sh 已含）
```

在 console.log 找 `VIRTUAL_CP_SENDER_MOD_OK`、`VIRTUAL_CP_SENDER_REGISTER: rc=0` 与
`VIRTUAL_CP_SEND` 行。`rc!=0` 表示另一模块已占用远端发送器（如 pcie-if.ko 已装载）。

## 关键 ABI 细节：osal_reg_public 要“函数指针的指针”

`osal_snd_msg` 读远端发送器是 `fn = **(slot)`（双重解引用，main 核 `ldr x2,[slot]; ldr x2,[x2]; blr x2`；pcie-if.ko 也传 `&sender_fn_slot` 而非裸函数）。所以 `osal_reg_public` 必须传**函数指针槽的地址**，不能传裸函数地址——传裸函数会被再解引用一次，把函数头 8 字节当指针跳进去（首轮 run-uje6bn1t 实测：UPM 发 0x8fc 队列时 `blr x2` 跳到垃圾地址 `0x17bfdd10083ff`，SP/PC 对齐异常崩溃）。本模块用静态槽 `sender_handle` 运行时填入函数地址、传 `&sender_handle`（避免 ld -r 的 .data 初始化重定位）。首轮崩溃属模型错误已修正，非环境问题。

## 2026-10-23 CP→AP 帧交付协议 + CP 仿真第一增量

### CP→AP 帧交付协议（subagent 8c38010a 逆向 + main 核原字节验证）

- **帧就绪接收处理器**：appFw `sub_34f34e8` 是成像队列分发线程，`osal_rcv_msg_tmo(0x92840747,&msg,-1)` 阻塞等待 + 校验源。消息 `{u16 cate@+0=0x200d, u16 sub-op@+2, payload@+4/+8}`。sub-op `0x1118`=帧完成、`0x1148`=缓冲释放（按 u32 handle）。
- **帧数据 = AP 拉取（PULL），CP 永不推**：appFw 经 `interchip_transfer_async`（libInfraInterchipDatatrans.so+0x990）打包 5×u64 到 0x30B 消息发 queue `0x02820746` → icdt.ko → `pcidma_transfer_async`。成像调用者 `sub_341a044` 拉两段（0x64000+0xd100）。
- **icdt.ko**：src/dst 描述符 8B `{u32 handle_lo(bit15=chip), u32 phys_hi}`，一端必须 bit15。

### CP 仿真第一增量（cp_emulation.ko，实跑验证 run-o47w2ia8）

- `cp_emulation.c`（sender-client/）：guest 内核模块，注册 sender（osal_reg_public 双解引用 ABI）+ 解析成像帧队列 + 应答。
- 实证：注册 rc=0 + 接收 186 条 AP→CP 消息 + 收到 4 条成像帧队列消息（0x92840747/op 0x200d/sub-op 0x0118/0x042b/0x0500/0x0159）+ **应答全部 4 条**（rc=0 到 AP 回复队列 0x81cf61xx）+ **成像链接受**（subscription_reply_failed=0，无 abort）。
- **接收+应答路径端到端打通**。

### 虚拟 CP 交付一帧的序列（协议基础齐备）

1. 产帧到 CP DMM 池缓冲（0x41e000000，每槽 0x80000；可用 cmos-source.c 产测试帧）
2. 应答 AP 的 op2a DMM 段查询（已实现 op2a，dmm-service.c）
3. 发帧就绪消息到 AP 队列 0x92840747：`{u16 0x200d, u16 sub-op, u32 handle@+8,...}`
4. **不推字节**——AP 自己经 ICDT/PCI DMA 拉取。保持字节可读直到缓冲释放（sub-op 0x1148）。

### 剩余增量（明确，有协议基础+可复用资产）
产帧（cmos-source.c）+ 帧就绪消息 + DMM 缓冲管理。未闭合：帧就绪 vs 完成的确切 sub-op；尺寸/格式字段位置（可能在流建立时定）。
