# 默认启动的蓝牙初始化依赖

此前 `./start.sh` 的默认自然启动未选择已有的虚拟 HCI 控制器。原蓝牙管理初始化失败后，原固件可以显示“系统出错”。此前实跑需要调用者手动设置 `A7C2_VIRTUAL_HCI=virtual-rom-v1`，因此那次通过不能算默认入口已经修好。

修复位于 `runtime/analysis/start-menu.py::profile_environment()`：产品自然启动默认明确选择已有 `virtual-rom-v1`。原 `startBTCore.sh` 请求、原 BSA、原 HCI 命令和控制器 backing 继续实际运行；没有修改系统错误页、蓝牙管理返回值或原相机设置。

这属于已有有限模型的产品默认接线，不提供物理射频、手机配对或完整蓝牙。底层独立 probe 和非自然旧菜单实验的默认值不变；其它实验仍须明确选择自己的配置。

要作禁用对照，可显式传入空值：

```bash
A7C2_VIRTUAL_HCI= ./start.sh
```

未知 HCI 名称在启动前拒绝。普通使用直接执行 `./start.sh` 即可，无需重新初始化原配置。

## 验证方法

核心回归以八组并发执行，包括新增默认选择、显式禁用与未知profile拒绝测试，以及已有原输入、完整帧、owner、原libc构建和HCI模型检查。

实际验证使用现有用户默认配置的独立副本，启动前逐文件核对，验证后再次确认原配置未变。测试创建自己的 Xvfb，不操作用户桌面，直接执行产品 `start.sh`，从环境中删除 `A7C2_VIRTUAL_HCI`，再核本轮 runtime manifest 实际选择的控制器。

首设逐页检查原文案像素和当前原screen，按键以真实GTK 50ms按下/释放投递并核原App32消费边。原Home菜单为 `0x2ca`；首轮测试脚本只认旧列表页而超时，后续关闭还误用了显示号，原失败记录保留。修复验收脚本后，只补必要的同代码端到端验证，不把脚本失败回填为通过。

最终同代码验证 `run-1cnmhiiy` 返回0：调用者环境没有 HCI 变量，实际manifest为 `virtual-rom-v1`；九步原首设后原HUD、Home菜单 `0x2ca/44` 和MENU返回原HUD均有原PNG与原事件。没有出现 `0x30c` 系统错误页，原配置未重置且验证前后摘要不变。主会话已直接看图复核菜单和返回画面。

原QMP quit确认、owner rc0、signals=[]、launcher rc0及32×4MiB卡跨通道摘要、整卡读回、fsck0均通过。发布前另八组检查全部rc0，受限host为 **325 passed / 34 skipped / 92 subtests passed**，跳过项保持原显示/资产边界。详细分账见[默认启动收据](../../validation/default-startup-20261108.json)。普通使用无需补环境变量或清配置。

短时HUD与菜单通过不代表长期电源/唤醒已经恢复。此前有原 `pre_power_off` / `0x309` 黑帧和恢复缺口，保持独立记录；本次默认蓝牙接线不能提升完整硬件启动、取景、拍摄或USB认证能力。
