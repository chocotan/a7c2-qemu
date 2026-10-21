# 启动流程 06 · 输入链：按键与拨轮到原固件消费者

本篇讲进入首设/拍摄页面后，GTK 窗口上的点击如何变成原固件消费掉的输入：
三套键码 → 两条注入前端 → 事件序列 → 队列与串口 → 以新画面确认结果。
对应索引第 8、9 步。

变量见[索引](README.md)。结论引自既有报告，本次只读源码，没有发按键或跑 QEMU。

## 1. 三套键码：raw、UIBIZ、业务事件

宿主只声明一份表：`menu_live.py::KEY_DEFINITIONS`（控件名、raw code、status、
MODE 位置、可用性说明）。真正注入 guest 的是 **raw 码**，不是 UIBIZ 枚举。

原固件内部再做一次换算：appFw 的 `0x17951c0` 查哈希表 `0x5f64120`，
把消息第一字从 raw 改写成 canonical（UIBIZ），其余字段不动。
这张表由只读数据初始化为 **1120 对 {raw, canonical}**。

校准过的基础映射（全部为十六进制）：

| 控件 | 注入 raw | UIBIZ |
| --- | --- | --- |
| UP / DOWN | `0x3` / `0x30` | `0x2` / `0x6` |
| LEFT / RIGHT | `0x15` / `0x1af` | `0x4` / `0x16` |
| MENU / ENTER | `0x1ab` / `0x1ac` | `0x13` / `0x14` |
| DELETE（C2 共用） | `0x1f8` | `0x23` |
| REC / FN / AF-ON | `0x1f0` / `0x7095` / `0x0f000004` | `0x1c` / `0x8d` / `0x2d7` |
| 半按 / 全按 | `0x1f1` / `0xa7` | `0x1d` / `0xf` |
| 前/后/控制拨轮 | `0x1000001c` / `0x10000013` / `0x1000001d` | `0x2f5` / `0x2ef` / `0x2f6` |
| MODE 拨盘 / 三档开关 | `0x7025` / `0x71c9` | `0x2a` / `0x1c5` |

踩过的坑：

- 旧 MENU 值 `0x14000102` 被原表映到别处——收到消息也不开菜单；
  从动作表抄 REC 的 `0x1c` 当 raw 注入同样发错键。
- 表里有三个重复 raw（如 `0xa7→0xf/0x10`），唯一 raw 只有 **1117 个**；
  原插入逻辑**保留首项**，用普通 dict（后者覆盖前者）会把全按错解成 `0x10`。

## 2. 两条注入前端：App32 与 Infra20

`inject-key.c` 用原 OSAL API 分配消息、设 source、发送。两条路不同：

| | App32（默认） | Infra20（A/B 对照） |
| --- | --- | --- |
| queue / source | `0x005503e0` / `0x005503e0` | `0x807a0020` / `0x92840747` |
| 消息长度 | 32B（8 个 u32） | 20B（5 个 u32） |
| 布局 | `+0 key, +4 sub, +8 status, +0x10 ex, +0x18 from` | 顺序 `{key,sub,status,ex,from}` |
| 经过的原逻辑 | 直接进 App 队列 | 先经 libObj 链更新键缓存再转 App |

注意：Infra 接收器只读前 16B 后强制 `from=1`，第五 word 不决定最终 from。
App32 绕过了部分原缓存/repeat 处理——两条路终点都进 app，不等于等效；
App32 的成功不能证明物理键缓存、重复或省电唤醒行为。

发送返回 0 只证明**消息已提交**，不证明消费，更不证明画面变化。

## 3. 事件序列：短按、拨轮增量、档位位置是三样东西

`key_command()` 按控件类型生成不同序列：

| 事件类型 | 序列 |
| --- | --- |
| 短按（方向/ENTER/MENU/DELETE/C1/半按/全按/REC） | `1` → guest `sleep 0.05` → `0`，两次返回码都记 |
| 拨轮增量 | 单发一条：左 `0xfffffc00`（−1024），右 `0x400`（+1024），**不补释放** |
| MODE 位置 | 单发标签对应的合法 status（见下节） |
| 照片/录像/S&Q 三档 | 单发 `1`/`2`/`3` |

踩过的坑：长按 1 秒会触发原固件连发，不算单击；给拨轮也发 `1/0`
会制造多余动作；给 MODE 发普通键序列可能进原 assert。
半按不保持、全按不自动先半按——都是"点按触点"，各自功能另验。

## 4. MODE 拨盘：标签和原枚举要逐项对

MODE 的位置表（`KEY_DEFINITIONS['MODE']['positions']`）：

| 标签 | P | A | S | M | AUTO | MR1 | MR2 | MR3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 单发 status | 3 | 5 | 4 | 6 | 1 | 7 | 19 | 20 |

踩过的坑：原名字数组顺序是 P/A/S/M/AUTO/…，曾按 0 起始绑定，
结果请求 A 显示 P、请求 P 显示 AUTO——"慢一档"错位。原参数 `0x1c75`
的显式枚举是 AUTO0/P1/A2/S3/M4，修复是逐项绑定 AUTO1/P3/A5/S4/M6，
**不是整张表 +1**。P/A/S/M/AUTO/MR1/MR2/MR3 都有逐张原 LCD 的限定证据；
但模式标识变化不证明真实曝光或完整参数回载。

## 5. GTK → 队列 → 串口 → guest

1. **GTK 侧**：按钮点击/键盘快捷键/滚轮/外圈拖动都归一成控件 symbol；
   150ms 节流；拖动满 15° 才发一条控制轮事件，不按角度连发。
   `reason()` 先检查：VM 是否 running、registry 是否提供该控件、
   有没有正在关闭/重初始化。unknown 键不能发；`EXPOSURE_COMP` 没有码，
   不能偷偷绑成 DOWN。
2. **队列**：`VM.enqueue()` 校验命令字段集合，队列上限 8，
   满了明确报错。SD 介质变化未收敛时暂停机身输入（快照/导出除外）。
3. **串口**：`serial_command()` 每条命令带随机完成标记
   `MENU_DIAG_COMMAND_DONE_<随机>:<rc>`，只认本次完整标记；
   超时后进入失步状态，拒绝后续普通命令，防止事务交错。
4. **guest 注入**：`inject-key` 打印 `INJECT_KEY_SEND ... result=...`。

UI 反馈写得很清楚："已排队；实际响应以固件新画面为准"——
回包精确匹配后才记"输入已提交"。

## 6. 确认：以原消费者和新画面为准

"已提交"不够。限定回归（`check-natural-gtk-input.py`）用真实
xdotool 点击 + 等待 input 事件 + 采集已校验 LCD 帧来确认：

- MODE 八档：各有原 HUD 画面证据（MR2/P、MR3/P 等）；
- 后拨轮在 P 档把曝光补偿 0.0 → −0.3 → 0.0（仅限该上下文）；
- C1/半按/全按/REC 的 1/0 都被原 App 线程消费，有对应原图
  （C1 限制提示、REC 的"插槽2无卡"对话框等）。

**边界**：半按 ≠ 合焦，AF-S 图标 ≠ AF 完成，全按/REC 被消费 ≠ 照片/录像完成。
首设回归脚本最终保留 `ok=false`、`full_camera_capture_implemented=false`——
自动化跑完不升级为相机功能完成。

踩过的坑——日期确定键断言：旧路径按确定后
`get_date_time_by_changing_current_area` 在 `appFw+0x2524f98` 断言。
不是按键协议错了，是日期服务没初始化：原 model 读服务 `0x0090013d`，
命令2返回零日期。
修复是 `seed-date-clock` 在已核未初始化状态下走原 BY_BOOT=4 初始化，
取原默认 2023-01-01 并确认时钟推进；失败就阻止 app 启动。
修复后原 123 步重放通过。不证明时区/夏令时或跨 VM 时钟持久化。

## 7. 异常之后：停输入，保留现场

`FirmwareMonitor` 增量扫 console.log（保留跨块尾部），命中
`Entering exception monitor.` / `Exception>` 立即抛 `FirmwareFault`：
VM 进入 faulted、标记旧画面、禁用机身控件，只允许 SD 导出/关闭。

踩过的坑：以前只在单条命令输出里找异常，两次点击之间的原断言被漏掉，
后续输入把 90 秒超时和"队列已满"顶到前面，掩盖了第一原因。

```bash
# 执行目录：$PKG；只读定位前端、原消息与异常监视实现
cd "$PKG"
rg -n 'FirmwareMonitor|Exception>|pending' runtime/analysis/menu_live.py
rg -n '807a0020|app|status' runtime/analysis/inject-key.c
```

## 证据入口

- [原映射、重复 raw 与 Infra20 合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/control-lens-exposure-frontiers.md)
- [MODE 标签修正与原图](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/mode-snapshot-order.md)
- [日期断言与监视器 §10–11](../../../a7c2-re/report/2026-10-17-qemu-native-camera/BOOT-TROUBLESHOOTING.md)
- [当前机身控件进度](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/remaining-body-controls.md)

## 如果你在做别的机型

raw/canonical/业务事件三张表、Infra20 布局都要重核。可复用的是：
用已知导航键反校映射方向、尊重重复键的首项语义、区分短按/增量/位置、
把"输入已提交"和"业务验收"分开。先闭合"按一次、原消费一次、
画面合理变化"的小循环，再扩按键集合。
