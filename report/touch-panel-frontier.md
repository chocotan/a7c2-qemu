# UDATE之后：touch-panel启动前沿

## 范围与结论

本报告记录 `run-bh0ryvgh` 在 kernel UDATE round-trip 完成后暴露的下一条候选启动等待。
它不是拍照、触摸硬件、CP liveview 或 group0 完成证明。初版只做原始字节和运行时证据整理；
后续已加入默认关闭的虚拟配置模型，VM结果另行记录，不改变硬件未验证结论。

**已证实**原固件向 `0x92840747` 发出了 `200d:0146` 请求，且未观察到对应的 `0x1146` 回复。
**尚未证实**该请求的后续 `F02F` 状态落地、硬件触摸效果或它一定是 group0 current 的唯一原因。

## 运行时证据

`runtime/analysis/menu-runs/run-bh0ryvgh/console.log:2616`：

```text
OBS FULL_AUDIO_INPUT tid=374 destination=0x92840747 source=0x81cf61c9 bytes=10 raw=0d2046010a0001800100
```

`FULL_AUDIO_INPUT` 是共享 `0x92840747` 观察点的旧标签，不应把这条命令误称为音频；其命令
字段明确是 `0x0146`。同轮没有对应的 `0x1146` reply。该请求出现在 UDATE 的
`UDATE_K_DONE` 之后。

被动 `ee-passive-4w6j930v` 的 Common 内核栈为 `osal_rcv_msg_tmo`，候选用户栈字包括
`0x34e5788 → 0x34e8b68 → 0x34c6184 → 0x3470458`。这些字没有正式 unwind；它们是
与原调用链相互印证的候选，不是已认证的 frame chain 或 group0 current 读数。
原 sequence 名称表另有静态映射 `0xbe=sequence_set_touch_panel`，两种证据不混用。

## AP 原请求与等待

原 `appFw.so` SHA256 为
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
`0x34e8b00` 的窄反汇编确认：

```text
+0  u16  0x200d
+2  u16  0x0146
+4  u16  0x000a       (10 bytes)
+6  u16  0x8001
+8  u16  (*input == 1) (low byte is 0/1, high byte zero)
```

`0x34e8b1c:790053bf` 清零最后一个 halfword，`0x34e8b40:3900a3a0` 只在输入为1时写
低字节。`0x34e8b64:97fff272` 调用 `0x34e552c(0x92840747, request, 10, response, 12)`；
`0x34e5780:12800002` 选择无限等待。返回后复制12B、释放回复并销毁 scoped queue。
`0x34e8b68` 读取回复 `+8`，再由 `0x34e349c` 转换原始 BB 状态。

调用链为：

```text
0x3470328 (sequence_set_touch_panel::run)
  -> 0x34c6158
  -> 0x34e8b00
  -> 0x34e552c
  -> osal_rcv_msg_tmo
```

## CP 原回复与后续路径

原 `cpapp-b.bin` SHA256 为
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。
以下地址为 CP 运行 VA，原始文件偏移为 VA 减 `0x108000`。

`0x69c8a2` 的完成构造器在 `0x69c8c0` 以原字节 `41 f2 46 10` 装入 `0x1146`，
在 `0x69c8e2:0395` 写状态，并经 `0x1c78e0` 按原交易路由回复。回复形状为：

```text
0d 20 46 11 0c 00 01 80 <status:u32LE>
```

因此 outer reply 是 `0x1146`、12B，不是把请求简单原样返回。AP 的 `convert_bb_err_code`
目前核对到：`0/0x00590000 → 0`，`0x00590001 → 0x6e`，`0xffffffff → 0x6d`。
裸0会被上层接受，但它本身不证明设备已经应用设置。

静态下游还存在：

```text
0x1c42f8 -> 0x1b920c (SendVDF_SetTouchPanel)
  -> 0x9059000e, 12B: 01 20 21 03 0c 00 01 00 <enable> 00 00 00
  -> 0x6ca950: enable <= 1, internal 0x1321
  -> 0x6ca98c: 2001:F02F
```

`0x6ca962` 的原字节支持 `0x1321`，`0x6ca9aa` 起的原字节支持 `0x2001`/`0xF02F`。
这些证明协议路径存在，不证明 F02F 后端状态已恢复。现有 VDF/audio 配置模型只能复用
传输和 ownership 模式，不能套用一个通用成功 ACK。

## 实现门槛与下一步

在实现任何 bounded touch-panel 服务前，必须闭合：

1. F02F 的完整字段、目的地、回复和状态转换；
2. outer `0x1146` status 与实际下游结果的对应关系，及不支持/失败形状的 delegated 行为；
3. requested 与 applied 的区分、真实状态/readback、原请求/动态 waiter/reply/free 各一次的所有权；
4. entry/worker 证据，避免把名称表或 raw stack 字直接当成 group0 current；
5. 非法 enable、重复完成、并发、分配/发送/释放失败的负例。

在这些未知项闭合前，不写裸0成功回复、不改 EE/sequence/current 字段、不宣称触摸硬件或
自然拍摄恢复。后续若只做观测，也必须保持原字节检查、有限次数和默认关闭。

## 已接入的 bounded 虚拟配置模型（待VM验收）

实现文件为 `runtime/analysis/device-models/touch-panel-device.c/.h`，profile为
`A7C2_TOUCH_PANEL=virtual-config-v1`，默认关闭，并要求同一自然启动的CP3007+UDATE路径。
它不是原CP执行，也不是F02F总线仿真。

模型只接管合法0/1的10B `200d:0146`。它执行实际的虚拟Accessor缓存写入和readback，构造
已核对的F02F body与TP控制 `{u32 3,u32(enable==1)}`，然后才发出原形状的12B `0x1146`
回复，正常outer raw status为 `0x00590000`。这对应原VDF/内部结果，不是硬件applied结果。
虚拟Accessor gate明确为0；原gate运行时值、F02F envelope/transport和TP控制结果仍未验证。
非法enable、错误尺寸/标志/source、并发、资源失败和重复指针均不产生正常完成；不模拟原非法
输入的副作用，也不以delegated名义发成功回复。

回复有独立lease；request/reply分配、发送、释放、重复地址、并发和失败重试均经过mock。
`control_result_verified=0`、`f02f_transport_verified=0`、`original_cp_executed=0`、
`hardware_touch_verified=0`始终保留。主机ASan/UBSan **2项+10子测试**通过，observer/profile
组合回归 **13项+31子测试**通过；这些不是QEMU验收。

VM必须分别看到 `FULL_TOUCH_PANEL_REQUEST/DEVPANEL/REPLY_QUEUED/COMMIT/REPLY_FREE`、无fault、
后续原sequence/clock/mode证据，以及原Fsys导出/host提交和清理。只有这些实际记录齐备，才能说
该虚拟配置依赖被消费；即使全部齐备，也仍不等于触摸硬件、EE、liveview或拍摄恢复。

构建 `bafed73dc` 与rootfs repack `bd0d23538` 均exit0；正式observer C/SO为
`5ffab5f7442625473cbfb14c85c097ca1723c2e38a7996160fe565eadb5832c0` /
`de4dabdc5e292b85da2517819b75d75eaee08fc870c1777ee5e2ac73c7524813`，initramfs为
`e3a3da137735211f2232d707f28836e857e7ccb542d8c6c0f2af1f16997d22e6`。
`INITRAMFS_TOUCH_IDENTITY_PASS`逐项验证包内observer和UDATE模块，且完整相关回归为
**29项+37子测试**、CP背景组 **3项+18子测试**。这些是构建/主机证据，不是VM证明。

### 观测缺口（当前run复核中）

`run-cytsrdps` 的manifest和initramfs已确认绑定新observer，profile admission也通过；但
`FULL_TOUCH_PANEL_` 尚未加入 `menu-observe.c` 的console mirror白名单，且自然profile把
`/tmp/menu-load.log` 链到 `/dev/null`。因此console中的 `FULL_TOUCH_PANEL_*` 零命中不能证明
模型未执行，也不能把Common的futex idle直接解释成reply已消费。该run已按无SD写入的限定
前提正常SIGINT收尾，host未变、未用SIGKILL，保留为观测不足而非协议结论。
随后已把 `FULL_TOUCH_PANEL_` 加入console mirror并加入回归断言。镜像build/repack
`bd914e318` exit0，observer C/SO为 `688aa84ade9662b4024badb2b3106e22606500698af0f6233ec48645fcb5891a` /
`a374e51f7081866b11ec4bcb0e1c0a25015f1bdf8d39d98275865c3ced3dda9c`，initramfs为
`cf669db158e265bdfdebf16141dae4ce33a83ab43ea0b4ac75ec76603de5b3f4`；包内身份检查通过。
复测前不把 `run-cytsrdps` 写成协议通过或失败。

## `run-wywe37t6`：虚拟配置已消费，但不是拍照验收

镜像修复后的 `b599e067e/run-wywe37t6` 直接记录了完整的
`FULL_TOUCH_PANEL_REQUEST → CONFIG → REPLY_QUEUED → DEVPANEL → COMMIT → REPLY_FREE`：
请求为 `0d2046010a0001800100`，outer reply 为 `0d2046110c00018000005900`，
F02F body 为 `01202ff00c00010001000000`，目的地 `0x90590819`；虚拟 cache/readback、
request free 和 reply free 均成功，UDATE 也完成。该结果只证明 bounded virtual configuration
和消息 ownership，不证明原 CP、F02F transport、TP control、硬件触摸或硬件 ready。

本轮没有自然快门、mode-transition `run()`、EE 或 JPEG/MP4；`SD/export.json` 保留原始
`ok=false`。首截图失败点为 `/simulation/gui-model-export` 返回1，尚无已提交的 GUI model
快照；它不能单独证明原固件停在同一位置。已保存 `touch-panel-evaluation.json`，并按
原 SD 未挂载/未写入/未提交、host 仅有不变 `INPUT.BIN` 的限定证据正常 SIGINT 清理，
未使用 SIGKILL。完整 CP3007→UDATE→touch 路径因此保留为 A/B 诊断，不再作为拍照前置。

`menu_live.py` 随后增加了一个受限 harness 分支：只有明确不存在
`/tmp/gui-model-state.bin` 时，才写入 `available=false/publication_verified=false` 并继续真实
LCD 快照；文件存在时仍必须原样导出并严格解码，传输/固件错误不被吞掉。
`test_live_transport_retention.py` 覆盖缺失和存在两种情形，主机回归为 **10项+10子测试**。
这只是辅助证据通道修复，不是 GUI model、EE 或拍照成功。首次重试 `bd0169bfd` 因漏设底层
`MENU_INPUT_ROUTE_TRACE=1` 在参数解析阶段退出，`b6908d4e6` 又因外层调用缺少
`MENU_RM_FILE=1` 退出；两次均未启动 VM、未写 SD。已确认正确结构是 GTK 脚本→
`menu_control.py` profile→QEMU，预检通过后的 `bf9e65b71` 才进入真实基线，不强制
UDATE/touch，直接检查原 Still/MPR/Fsys 和 host JPEG 写回。

后续 `b689f92bd/run-9f_qv6a2` 再次实测 UDATE 与 touch 全部虚拟协议/释放步骤；但真实 LCD
仍全黑，未进入语言页、未执行自然快门，CP3006 仍 delegated，EE/JPEG 均未恢复。原始 SD
export 为 `ok=false`，没有原 mount/write/flush/commit，host 仅未变 INPUT；已正常 SIGINT 并最终
释放所有 owned PID/主锁，未用 SIGKILL。该结果进一步确认 touch 虚拟配置可被消费，但仍不证明
F02F transport、TP control、硬件触摸、原 group0 完成或拍照。详见 `startup-photo-evaluation.json`。
