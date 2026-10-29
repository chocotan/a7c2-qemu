# QEMU 原厂固件启动：两处环境缺口修复与当前阻塞定性

日期：2026-10-18
范围：本机隔离 QEMU 中的 appFw（Sony A7C II / ILCE-7CM2）冷启动链路。
本文只记录**实测成立**的内容；未闭合项单列，不当成已完成。

根因研究的逐步推导记录在
`analysis/qemu-boot-research/main-screen-entry/REPORT.md`（§4.11–§4.21），
运行代码在 `runtime/analysis/`（`menu-observe.c` + `qemu-menu-probe.py`）。

---

## 1. 结论摘要

| 项 | 状态 |
|---|---|
| 授权链断言（`lib_assert.cpp:46`，`run_i` 内 `0x305b99c`） | **已修复**（实测断言消失） |
| `iCrypt_HasPublicKey` 未定义导致进程 `_exit` | **已修复**（实测不再出现） |
| 冷启动到**拍摄主界面** | **未达成**：固件停在启动屏 `0x308`（28 项） |
| 真实阻塞性质 | 已定性：**appFw 依赖的对端 endpoint 在本机不存在**（`-1020`） |

## 2. 修复一：`0x90280964` 时间服务不再谎报成功

### 2.1 现象与根因

`libInfraOptionInstall.so` 的 `OPTION_INSTALLER_MAIN_THREAD` 永久阻塞：

```
OptionInstaller::TimeManagement::initialize_time_manager   (库内 0x162a0)
  └ osal_snd_msg(0x90280964, msg)          → 返回 0（我们"发成功"）
  └ osal_rcv_msg_tmo(0x8277096f, -1)       → 永久等待一个永不到来的回复
```

Kuna 反编译 `0x162a0` 得到的真实契约（两轮，reply `byte+2 == 0`；
第 1 轮还要 `u32+4 == 1`，第 2 轮还要 `(byte+4 & 0xc1) == 0xc1`；两轮的成功值都在 `u32+8`，
且 `off_time + total_time = 当前时间`）。

**关键分支**（之前被忽略）：`osal_snd_msg` 返回非零时，固件走自己的 `read_from_backup`
降级路径并继续；只有"发送成功但无人应答"才会死等。
本机没有应答 `0x90280964` 的对端，而我们的 osal 却返回成功 → 固件合理地进入等待分支。

### 2.2 处理

`MENU_CP_TIME_SERVICE=1`：对 `0x90280964` 不转发，返回 `-1021`（无此目的地），
把控制权交回固件自身的降级路径。**不伪造应答、不填 ACK。**

### 2.3 实测

```
OBS CP_TIME_SERVICE n=1 opcode=1 reply_queue=0x8277096f -> -1021 (no Darwin endpoint)
OBS OPT_READY frame base=0x7f609d8000 ready@0x44084=1     ← 修复前 4 轮均为 0
ASSERT_CALLER 计数 1 → 0 ；"Assertion `false' failed" 文本消失 ；未进入 exception monitor
```

## 3. 修复二：`libInfraCrypt.so` 未定义符号

### 3.1 现象

```
OBS APPLOG   83 B  sequence_boot::run
/usr/bin/im.elf: symbol lookup error: /usr/lib/appFw.so: undefined symbol: iCrypt_HasPublicKey
```

`symbol lookup error` 是致命的：动态链接器直接 `_exit`，**guest 的异常监视器不介入**。
因此"没进 exception monitor"不能当"进程健康"的证据，必须看进程是否存在
（收尾诊断里 `THREADS_PID=` 为空即进程已不在）。

### 3.2 归属（Kuna 取证）

| 查询 | 结果 |
|---|---|
| `search_procedures("iCrypt")` | `iCrypt_HasPublicKey` @ `0x165f390`（PLT 桩） |
| `xrefs(0x165f390)` | 唯一调用点 `0x35107dc` |
| `xrefs(0x35107c4)` | 被 `0x34dcad0` 引用（注册表 → 间接调用） |

`0x35107c4` 是模型 getter 包装：`cset w0,eq` → 返回 `(iCrypt_HasPublicKey()==0) ? 1 : 0`（"是否没有公钥"）。

符号定义在固件自带的 `libInfraCrypt.so`，但 **appFw 与 im.elf 的 `DT_NEEDED` 都不含它**。

### 3.3 处理

`MENU_CRYPT_LIB=1`：在 appFw 导入前 `dlopen("libInfraCrypt.so", RTLD_LAZY|RTLD_GLOBAL)`。
用 `LAZY` 而非 `NOW`：`RTLD_NOW` 会因依赖链 `libInfraCrypt → libInfraSKD →
osal_unreg_msg_queue_cb` 中对端尚未就绪而整体失败（实测报错原文即此），
而 appFw 真正需要的函数符号由该库自己定义。

### 3.4 实测

```
OBS CRYPT_LIB libInfraCrypt.so=ok
"symbol lookup error" / "undefined symbol" 出现次数：0（修复前每轮必现）
```

## 4. 回归：两个修复不破坏已验证的菜单基线

基线 env（取自 `start-menu.py`）+ 两个修复（`run-wmq6nam4`）：

| 指标 | 结果 |
|---|---|
| `CRYPT_LIB` | ok |
| `ready@0x44084` | 1 |
| `Assertion 'false' failed` | 0 次 |
| `headless-osd-pixels-rgba4444-software.png` 去重颜色 | **218**（640×480，真实内容） |

对照：基线单跑（`run-817r0blc`）= 247 色；裸调探针 = 1 色（**配置差异**，见下节）。

## 5. 一个必须记住的基线陷阱

`start-menu.py` 的 `profile_environment()` 会**剥离调用者环境里所有 `MENU_*`/`QEMU_*`/`SONY_*`**，
并注入自己的开关集（`MENU_APPLY_MENU`、`MENU_OPEN_SET=0x308`、`MENU_FRAME_OBSERVE`、
`MENU_SOFTWARE_LZ77`、`MENU_GPE_RGBA4444`、`MENU_DATE_SERVICE` …）。

因此：**裸调 `run-menu-probe.sh` 得到的 1 色空白画面，是配置差异，不是固件行为**；
比较绘制结果必须同一基线。此前一度按裸调结果推断"固件不绘制"，该结论已作废。

## 6. 当前阻塞：缺对端 endpoint（已定性，未解决）

### 6.1 `-1020` 的确切语义

`libosal_uipc.so` 的 `__osal_snd_sync_msg`（`0x61e8`）里 `-1020` 只有一条产生路径：

```
6364: ubfiz x0, x5, #3, #15      ; 用 (id & 0x7fff) 索引处理端表
6370: ldr   x21, [x0, #16]       ; 取该 id 的 handler
6374: cbnz  x21, 6274            ; 命中 → 发送
6378: bl    0x5100               ; 未命中 → 尝试 attach
6384: cbnz  x0, 6274
6388: mov   w22, #0xfffffc04     ; 仍无 → -1020
```

⇒ `-1020` = **目的 id 没有注册接收端**。
注意 `osal_snd_sync_msg` 的第一个参数是复合值，**路由 id 只取低 15 位**（`ands w5,w0,#0x7fff`），
把 raw 值当 SID 打印会得到像指针的数（`0x12282f6` 等），那是读数错误。

### 6.2 实测缺失清单

| 通道 | 现象 | 目的地 |
|---|---|---|
| 异步 `osal_snd_msg` | 内核 `Skip snd to 0x…`（一轮 103 次） | `0x83f`×52、`0x1`×19、`0x86f`×11、`0x8fc`×6、`0x747`×4、`0x193`×3、`0x85c`×2、`0x962`/`0x8f7`/`0x7ec`/`0x738`/`0x5c5` 各 1 |
| 同步 `osal_snd_sync_msg` | 返回 `-1020` | id `0x2f6`、`0x4bb`、`0x192`、`0x9e0`（长度 16/16/16/**328**） |

`0x9e0` 的归属（字符串取证）：`call_sync_api`、`infra_wrapper_veric::detail::{anonymous}`、
`DefInfraVericLiveStreaming`、`subscribe_streaming_error_notify_event` ⇒ **直播/推流**模块。
其发送点为 `0x35a5d38`（raw `0x032489e0`、328 字节、体首字 `0x2000000N` 按命令分派，6 个调用点）。

对端确实不存在：线程快照里 199 个线程全部属于 **pid 200（im.elf）**，没有独立 CP 进程；
CP 二进制虽已 staged 在 `runtime/analysis/menu-root/cp/`，但**没有被启动**。

### 6.3 屏幕语义（避免误判进度）

| 屏 id | 含义 | 本机是否到达 |
|---|---|---|
| `0x308` | 启动屏（28 项） | **到达**（冷启动自然建立） |
| `0x346` | 菜单 controller | 仅受控入口（`MENU_APPLY_MENU`）到达 |
| `0x2ca` | 菜单屏（44 项） | 仅受控入口到达 |

冷启动自然路径下：建立 `0x308`、画 1 帧、**画面 1 色（空白）**、无断言。
受控入口下：`0x308 → 0x346 → 0x2ca`，画面 218–287 色（有内容）。

⇒ **拍摄主界面仍未达成**，且不能把"受控打开屏幕"当成"冷启动恢复"。

## 7. 复现命令

两个修复默认关闭（不改变已验证基线）：

```bash
cd final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis
MENU_HEADLESS_OSD=1 MENU_SOFTWARE_LZ77=1 MENU_GPE_RGBA4444=1 \
MENU_FRAME_OBSERVE=1 MENU_OSD_OBSERVE=1 MENU_CTOR_CENSUS=1 MENU_MODE_SENTINELS=1 \
MENU_SETTLE_SECONDS=25 QEMU_BOOT_TYPE=1 MENU_DATE_SERVICE=1 \
MENU_CP_TIME_SERVICE=1 MENU_CRYPT_LIB=1 \
bash run-menu-probe.sh
```

观察点：`CP_TIME_SERVICE`、`CRYPT_LIB`、`OPT_READY ... ready@0x44084=1`、无 `Assertion`。

## 8. 未闭合（如实列出）

1. 拍摄主界面：需要补齐 appFw 依赖的对端 endpoint（6.2 清单），或启动虚拟 CP 进程。
2. `0x9e0`（veric）失败是否**本应被容忍**尚未判定：需确认真机是否总有该对端，
   或本机缺少某个前置可用性状态才走到致命分支。**不允许**以"让它返回成功"了结。
3. 同一 SID `0x90280964` 还有 `opcode 3` 的第三种时间操作，调用方与语义未定位。
4. 本次两个修复是否应并入默认基线：需要先取得"默认关/默认开"两侧的完整对照，
   再决定是否修改 `start-menu.py` 的已验证开关集。
