# 启动流程 04 · 原应用启动：从 bootin 到拍摄主界面

本篇覆盖索引第 7–8 步：`bootin.elf` 拉起原启动链、无配置时的原厂首设、
以及如何判定"拍摄主界面已到达"。
变量约定见[索引](README.md)；本文整理历史实际运行，本次未重跑。

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

## 3. 首设的实际操作序列（已验证路径）

以简中首设的限定回归（`check-natural-gtk-input.py --firstboot`）为准，
每步都以原 LCD 画面或原日志为判据，不靠固定延时：

1. **语言列表**：按 DOWN 导航；console 出现 GB18030 字体预加载记录
   （`RESOURCE_OPEN ... MYingHeiC-GB18030-SJ_wIcon.ltt`，首次在阿拉伯语高亮时）
   后再两下 DOWN 到简体中文，ENTER 确认。
   完成标志：原固件消费了字体、画面切换，而不是"发送了 N 次键"。
2. **"在相机上设置"页**：该页原文明示用 DELETE 继续；按 DELETE。
3. **后续页面**（区域/日期等，屏幕 ID 0x431、0x1c6 等）：按屏幕创建记录与
   实际画面内容决定 DOWN/ENTER；日期格式选择走原日期服务
   （`udate.ko` 已在第 6 步就绪，取原默认 2023-01-01 并读回合法日期）。
4. **拍摄主界面**：console 出现 `CREATE_SCREEN_ARGS ... id=0x343`
   （拍摄 controller）即判定到达；再稳定一段时间采 `shooting-after-setup` 帧。

完成标志：拍摄 controller 创建 + 本次 VM 的已校验 LCD 帧。
30 次手动点击内未到达则判失败，不无限重试。

## 4. 到达之后能做什么（当前边界）

已进入拍摄页面后已验证的：

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

- [首设条件与未闭合状态](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/first-setup-frontier.md)。
- [九项功能验收](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/nine-feature-acceptance.md)。
- 本包 [首设回归驱动](../../runtime/analysis/check-natural-gtk-input.py)、
  [键定义与验收目录](../../runtime/analysis/menu_live.py)。
- [本包验收记录](../../validation/README.md)。

## 如果你在做别的机型

屏幕 ID、首设页序、字体预加载顺序都是本固件具体的，必须重新观测。
可复用的是"以原屏幕创建记录+实际画面为导航判据、不用固定延时"的首设驱动方法，
以及"到达拍摄页面"与"能够拍摄"分开验收的纪律。
