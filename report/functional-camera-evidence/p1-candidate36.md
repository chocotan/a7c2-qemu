# P1 第三十六跑：实际 EE 禁止源与 HDMI/UPM 调试器接线

本轮确认：快门前后的 13 个 exclusion driver 中，只有 EE 的 `0x7b/current=0x1294` 命中禁止条件，禁止计数为 1。修复主机没有启动 HDMI/UPM 原生消费观察器的接线缺口后，两笔原 UPM 消息均实际处理并释放，all13 前置检查通过，functional-camera broker 首次在这条完整配置下实际 attach。原 AP 随后继续到新的 `PID_SET_KEY_CLEAR/0x406a`，其发送返回 `-1020` 并触发原 Imaging:3109 断言。**EE 完成、快门、JPEG 与写卡仍未通过，`capture_verified=false`。**

本轮仅为用户授权的隔离 QEMU 实验与产品代码修复，不连接或写入真实设备，不修改 AP 的 EE、exclusion、镜头或拍摄判断，不继续委派。报告 flavor=null。任务范围、原始收据、恢复前像及复现脚本位于项目 `scratch/a7c2-capture-p1-runtime-20261115-candidate36/README.md`。

## 原程序状态与实际禁止源

只读辅助程序一次打开 `/proc/<AP>/mem`，读取 135 个字段，包括全部 13 行 24B exclusion 状态、EE current、32B shadow 和 48B accessor 表。首跑 `a211` 快门前、快门后和结束时，`capture_inhibit=1`、计数=1；19 条静态规则中仅 `ee_status=EE_NOT_RUNNING` 对应规则命中。focus、zoom、日期、镜头、网络及其他候选均未命中。初始快照尚未初始化 exclusion，不把零行解释成已完成的状态。

EE 当前值 `0x7e67700` 为 0，shadow 仍为 0；运行时派发表读回确认 current setter/getter 为原 `0x276b148/0x276b154`。新增三个只读探针分别覆盖 `0x338d998` 的原 wrapper 写入口、`0x339fc60`（原 `0x339fc70` 写 1 调用之前）和 `0x339fc84`（原 `0x339fc78` 提交之后）。编译后逐字节核对原指令重放；中途探针保存临时 GPR、NZCV 与全部 SIMD 寄存器，x16 仅用于原调用点允许破坏的跳转暂存。探针由已有 `MENU_CAPTURE_INHIBIT_TRACE=1` 控制，不写模型值。

首跑未观察到 EE 尾部写入记录。其被动 Common 线程记录包含 `0x339d998` 等栈候选，但没有完成帧链回溯，收据明确为 `unwound_stack=false/current_blocker_proven=false`，不能单独声称已经定位精确阻塞栈。两个被观测的转场尾部都远晚于 HDMI 连接配置，当前修复优先处理有直接握手证据的前置缺口，没有修改这些 AP 分支。

## 已实现并实际验证的主机修复

原运行器 `_watch` 只等待 functional-camera mailbox，而 HDMI 视频连接先发布 `FULL_HDMI_UPM_MAILBOX_INIT` 并等待主机为原 UPM 消费链提供收据。已有 candidate35 日志记录了 `arming-timeout-or-status`；当前路径没有启动任何 `hdmi-upm-watch`。

产品现在从完整的原 observer 公告绑定 AP pid、物理页、nonce 与实际模块 `.text` 地址，复用 `hdmi_upm_watch`。它保留原模块 SHA、断点原字节、owner/进程祖先、虚拟机输出挂载、Unix socket、实际 QEMU 完整摘要、原生 UIPC 接收/处理/free、专用 receipt 页读回及 detach 验证。QEMU 准入仅补充现有 functional-camera runner 已验收的精确 b369 摘要，未放宽 scope 构建的旧守卫。

运行器持有观察器到两笔 native lifetime 完成，要求其正常 detach 后，才向 functional-camera broker 交接同一个调试器。退出时若观察器未确认清理，则拒绝关闭 VM 并保留 owner/磁盘租约。新增测试覆盖公告完整性/owner 改变、只启动一次、两笔完成与 detach、提前退出不得记完成、未 detach 不得关闭 VM、已有 camera debugger 不得被接管；另增精确 QEMU 摘要变更拒绝测试。

重试 `d85f` 实际结果：

| 边界 | 证据与结果 |
| --- | --- |
| 原 UPM 接收及释放 | `hdmi-upm-watch-events.jsonl`，22 个事件、2 笔收据，lease=4/5，完整原 native free 证据 |
| 专用页传输 | 两笔 `mailbox_deliveries` 均有完整 record SHA，第二笔原状态值为 2、有效传输值为 3，仍按已有模型合同处理 |
| 调试器交接 | `armed=true`、`detached=true`，无 error/detach_error；coordinator cleanup 全部确认 |
| all13 | 实际 `accepted=1`，video/OSD/audio 均 AP_consumed=1，OSD 16 槽每槽双 owner/双 open |
| functional camera | 实际 mailbox 公告、broker attach，3006 对应 op1/op2、VDF0138 对应 op1 的原 AP RPC 已执行 |
| 后续业务 | 原 AP 触发新的 Imaging:3109；快门与写卡未执行到 |

## 新前沿：PID_SET_KEY_CLEAR

新失败的直接原发送证据为：

```text
P18_OSAL_RESULT tid=372 destination=0x90040193 source=0x80020002
  type=5 opcode=0x406a bytes=12 rc=-1020 errno=1020
  raw=05006a402600008000000000
```

随后原 AP 输出 `infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109` 并经 `lib_assert.cpp:46` 报系统错误。原构造函数语料在 `analysis/appfw-decompile/corpus/parts/7/0x003530000.c:7253`，构造 12B `0x406a0005`，向 `0x90040193` 发送且回复参数全零；原命名注册为 `PID_SET_KEY_CLEAR`。同一时刻 VDF `0x0138` 的功能桥请求返回成功，来自不同线程，不把它误认成断言来源。

下一消费者应核对 CP 的 PID key-clear 后端、key 位图/状态及所有权合同，然后补齐对应接收服务，不能只将 `-1020` 改成 0。本轮未扩展这一新命令，也未执行第三次运行。

## 构建、验证与边界

observer、原 preload 集合、CPIO 与生产 derive 已重建，CPIO 文件集合及权限保持一致，唯一内容变化为 `simulation/menu-observe.so`。首跑和修复后的重试使用同一完整摘要的 observer/CPIO；重试只改变主机接线，避免将镜像变化混入比较。

- 编译后的三处 trampoline 均与原 ELF 指令逐字节一致，关键寄存器保存经反汇编核对。
- 135 字段辅助程序自检与缺记录拒绝通过；既有 gate parser 10 项通过。
- 两组、两个线程宿主验证：新增协调器 5 项、既有 runner 69 项、watcher 411 项通过。
- runner 大组仍有 15 项既有失败（含两个子测试），在本任务修改前保存的 runner 上逐项复现，名称与原因相同：旧 `qemu-menu-probe` AST 夹具 `StopIteration` 及 `guard_live_owner` 夹具未定义。全组不记为绿；原输出、修改前对照和失败清单完整保留。
- 两轮业务结果均记失败。`a211` 为 broker 未 attach 超时；`d85f` 为新的原 AP 断言。两轮均正常 QMP quit、QEMU rc0、`signals_sent=[]`，磁盘租约保留到进程退出。
- 未执行真实 CP 固件、原 Sony loader/WBI 恢复或物理硬件验证；没有得到 `capture_inhibit=0`、`0x4038`、JPEG、写卡或 JPEG_ONLY_PASS。

## 证据与恢复

| Evidence | Finding | 下一条验证路径 |
| --- | --- | --- |
| `runtime-1/fast-gates-*.raw/json`、`analysis-runtime-1.json`、静态 19 规则 | EE 是该时点唯一实际禁止源 | 原转场完成后同时核 EE current/shadow 与 exclusion selector |
| `source-probe-check.json`、`integration/compiled-probe-check.json` | 观测保持原指令及 ABI | 下一轮保留相同探针与正确镜像绑定 |
| 两轮 console、重试 watcher 22 事件/2 收据/coordinator | HDMI/UPM 主机接线缺口已越过 | 在下一命令修复后复验不回退、broker 不早抢调试器 |
| 重试 `P18_OSAL_RESULT`、原 Imaging:3109、命令构造语料 | 新前沿为 406a/PID key-clear | 原 CP 语义与独立接收/释放服务 |
| `baseline.stdout`、`runner-r2.stdout`、`validation.json` | 新增测试通过，15 项旧失败未增加 | 主会话单独修复旧夹具；保持本轮失败原件 |

恢复前像在任务 `restore/`，均保存了本任务修改前父会话的已有更改。当前生产 derive 及构建摘要见 `integration/integration-result.json`；原始失败日志、异常现场、版本化收据均保留，不覆盖旧结论。空间与资源最终核收见同任务 `storage.json`，未执行回收；下一消费者是主会话证据核收及 PID 命令调查。
