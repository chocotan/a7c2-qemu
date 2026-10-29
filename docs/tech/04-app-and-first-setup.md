# 启动流程 04 · 原应用启动：从 bootin 到拍摄主界面

本篇覆盖索引第 7–8 步：`bootin.elf` 拉起原启动链、无配置时的原厂首设、
以及如何判定"拍摄主界面已到达"。
变量约定见[索引](README.md)。**2026-10-29：既有默认 HUD/MENU 短时通过，不代表最新功能 profile 已完成首启。** `run-qqu0q5oe` 的24步语言选择真正消费 LCD，但温度模态被误标为 shooting，系统错误早于 S2。下面的首设判据已按新修复更新；75 tests /139 subtests与4个调用方通过，现已纳入5568/7057完整回归、构建和双ABI，仍待原生复验。完整时间线见[当前进度](2026-10-29-current-progress.md)。本次文档整理未重跑实验。

## 1. 启动管理器拉起原应用链

自然启动 profile 使用原启动管理器：

```text
LD_PRELOAD=<观测器与媒体配置> /usr/bin/bootin.elf 'target=qemu ' dmode=3 &
```

bootin 按原启动链拉起各服务进程与 IM 主程序（研究探针 profile 则直接跑
`im.elf target=qemu`，属受控入口，不能当自然冷启动证据）。
观测器在旁只读记录 `CREATE_SCREEN_ARGS`、OSD 提交与输入队列。

完成标志：屏幕创建记录开始出现，headless OSD 产出第一帧。

注意：`dmode=3` 只是原开发模式参数，不是硬件仿真开关；
`change_mode.sh` 在参数判断前就可能写文件，不能当无副作用检查用。

## 2. 首设分支的进入条件

无已保存配置代数（或用户在 UI 点"销毁并重新初始化"）时，原固件进入首设。
已核的原判断逻辑（appFw 原字节）：

- getter 读模型日期状态（4B）与 force 状态（1B）；
- `process_power_on` 按 `(!force && status!=2) || special` 选择首设入口 `0x347`；
- 另有一条特殊启动条件分支，不能省略。

注意：首设完成状态的持久化**至今未闭合**——四份已核 Backup 文件中相关字段
均为 1，但完成真实首设后模型 force 仍保持 1、日期状态为 0，
不支持"完成后置位"的推断。当前每次无恢复输入的启动都会重走首设。
详见证据入口的 first-setup-frontier。

## 3. 首设的实际操作与新就绪判据

限定回归入口仍是 `check-natural-gtk-input.py --firstboot`。新修复保留真实 press/release；每次导航等待本次原 LCD 变化，再以连续新截图确认稳定，不把 host submission/idle 当固件消费。

1. **语言列表**：最多40步 DOWN，逐步等原 LCD 稳定，并核原 GB18030 字体与实际简中高亮。`run-to9olvu1` 只等 host 而失败；修后 `run-qqu0q5oe` 在第24步通过实际画面判据，旧失败不回填。
2. **手机设置页**：按原页面要求用 DELETE 继续，不能用盲 ENTER 代替。
3. **区域/日期、reader 与温度提示**：按原屏幕内容导航；reader/温度确认需实际选中下方取消并等待模态退出。日期仍由原日期服务处理，不直接改 AP 设置。
4. **拍摄 readiness**：必须同时核当前 HUD 内容、当前 controller 和教程收尾，再等 LCD 稳定。已核本固件路径包括当前 `id=0/count565`、前序 `0x343` 及 J-FINE/14M/AF-S HUD；这些是本固件的联合内容判据，**单个 `0x343` 创建记录不够**。
5. **系统错误**：看到原 SystemError/`0x30c` 即拒绝后续快门。qqu 的错误先于 S2，尚未唯一定位首 producer，不能将其归因于快门。

上述完整首启修复是组件/调用方验证，不是新 VM 成功证据；最新功能版本的主界面长期稳定性仍待验。

## 4. 到达之后能做什么（当前边界）

以下是既有默认 profile 的限定历史证据，不是最新 qqu 首启通过：

- HUD/MENU 由原按键调出（C1、半按、全按、REC 等八键限定回归）；
- 模式拨盘 P/A/S/M/AUTO 与 MR1/MR2/MR3 的原 HUD 限定证据；
- 虚拟 SD 的读写、热插拔与关机导出；
- 语言/日期格式两项配置的跨进程恢复（有限 SID）。

仍未通过的：

- **取景区域仍黑**：CMOS 实时图像没有恢复（见 [11-imaging-frontier](11-imaging-frontier.md)）；
- REC 的媒体选择/容量链仍在反查（见 [10-media-frontier](10-media-frontier.md)）；
- 照片、录像、真实合焦均未通过；
- 首设完成状态不持久化，无恢复输入时每次启动重走首设。

## 5. 画面如何到达操作者

guest 内 headless OSD 导出 → 宿主解码为 640×480 PNG → GTK LCD 画布。
UI 只显示本次 VM 经校验的帧；VM 停止或出错时保留上一帧并明确标注"旧画面"。
细节见 [05-display](05-display.md)。

## 证据入口

- [当前首启、后台等待与后续组件边界](2026-10-29-current-progress.md)。
- [进度摘要与最新负例](../../validation/2026-10-29-progress.json)。
- 本包 [首设回归驱动](../../runtime/analysis/check-natural-gtk-input.py)、
  [键定义与验收目录](../../runtime/analysis/menu_live.py)。
- [本包验收记录](../../validation/README.md)，包含有限设置恢复与既有 HUD/MENU 的历史结果。

## 如果你在做别的机型

屏幕 ID、首设页序、字体预加载顺序都是本固件具体的，必须重新观测。
可复用的是"以原屏幕创建记录+实际画面为导航判据、不用固定延时"的首设驱动方法，
以及"到达拍摄页面"与"能够拍摄"分开验收的纪律。
