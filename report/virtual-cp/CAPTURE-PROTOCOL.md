# 虚拟 CP 捕获：首批真实 AP→CP 协议数据（run-70tlxzdb）

capture tap 修正后完全工作：**无崩溃，140 条远端 CP 队列发送被捕获**。这是首次把 AP→CP
消息流量从 `No snd_msg registered` 黑洞变成可见协议。均为静态分析无法得到的运行时数据。

## 队列分布（140 条）

| qid | 条数 | size | 内容/判读 |
|---|---|---|---|
| `0x92b4086f` | 102 | 1504 | op `0x2300`/`0x2304`（首条 0x2304 带 `004b0001,000a0000,00000100`，其余全 0x2300 空载）。大型**周期性**通道（约 30s 一条）。 |
| `0x9092083f` | 19 | 8/20/36/40 | op `0x92xx`（0x9254/0x9255/0x9256/0x9253）。带 `ffffffff` 填充。 |
| `0x92a208fc` | 4 | 96 | 96B 消息，`00000003/00000004` + 指针值。 |
| **`0x92840747`** | 4 | 10/22 | **成像队列（原黑洞）**：op `0x200d`（frame），code `0x0118/0x042b/0x0500/0x0159`。 |
| **`0x90030001`** | 3 | 12 | **AF/镜头 SID**：op `0x402a/0x40b8/0x40af`，type 5。 |
| 其它（0x9101085c/0x92a007ec/0x916c0738/0x90280964/0x92f00962/0x90040193/0x928708f7） | 各1-2 | 4-56 | 配置/状态。 |

## 成像队列 0x92840747 的 4 条（帧/配置路径）

```
n=25 size=22: 0118200d 80010016 00000103 ...   op 0x200d code 0x0118, 值 0x103
n=33 size=10: 042b200d 8001000a 77770000 ...   op 0x200d code 0x042b
n=34 size=10: 0500200d 8001000a 00000001 ...   op 0x200d code 0x0500
n=45 size=10: 0159200d 8001000a 77770007 ...   op 0x200d code 0x0159
```

op `0x200d` 正是 menu-observe.c 里 BB_CONFIG_REQUEST 的 frame 号（display_info/yuv_layout/plane_config 服务的同一协议族）。**这印证成像队列走的是 BB config 协议**——之前 menu-observe 已为用户态部分建模（0x200d/0x16a、0x200d/0x14c、0x200d/0x147、0x200d/0x161 等），但这些 kernel 侧发送此前黑洞。

## 意义与边界

- **capture tap 是理解 CP 协议的第一手运行时数据**：成像队列、AF SID、大周期通道的真实消息现在可见。
- **capture-only 仍是 tap，不是 CP**：发送被接受（osal_reg_public sender 返回 0）但无真实 CP 处理/应答，AP 成像链在等回复处仍可能阻塞。本 run 相机继续运行到 3218s（n=139），说明多数发送是 fire-and-forget 或 AP 容忍无应答。
- **下一步**：逐条解码成像 0x200d 与 0x92b4086f 的语义，确定 CP 应答格式，才能把 tap 升级为真实 CP 应答模型。

## 复现

```bash
cd report/virtual-cp/sender-client && bash build.sh
cp sony_virtual_cp_send.ko ../../../runtime/analysis/menu-root/simulation/
cd ../../../runtime/analysis && MENU_VIRTUAL_CP_SENDER=1 bash run-menu-probe.sh
grep -a VIRTUAL_CP_SEND: menu-runs/<run>/console.log
```

## CP→AP帧交付方向：静态逼近极限（本轮，诚实否定）

代理（kimi，`scratch/cp-frame-delivery-kimi/`）追CP→AP帧交付，turn上限收尾，仅一跳经反汇编核实：CP回复发送器`0x4b6a70`（raw 0x3aea70）读回复{type@+0,cmd@+2,token@+4,status@+8}，经`0xbec024`发到queue`0x90030001`（bit31=远端=AP）——但**这是cmd3003控制回复，非帧通知**。四个任务问题（CP→AP帧就绪消息、DMM句柄交接、生产触发、CP→AP数据路径）**全部未闭合**：未找到发dest`0x80020002`/op`0x200d`的帧通知发送器，未追到DMM handle/offset交接字段，未追到生产触发，CP侧op2a server/push-pull DMA未追。

**战略含义**：CP→AP帧生产路径深埋在cpapp-b.bin，纯静态分析已到递减回报点（多个agent连续撞间接/运行时寻址障碍）。**帧交付协议的闭合需要运行时手段**：虚拟CP跑起来后watch CP侧DMA/队列，或在成像会话激活时抓真实帧消息。这强化了"虚拟CP成像会话bring-up是必要路径"的判断——静态能钉的协议骨架已钉，剩下的要靠运行时。
