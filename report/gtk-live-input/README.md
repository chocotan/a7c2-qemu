# 自然首设 GTK 实际按键验收

结论：**本次自然首设的鼠标 DOWN、键盘 UP、鼠标 ENTER 已通过。** 等待60秒后再次进行 DOWN/UP，原 LCD 高亮仍正常移动；确认后进入原辅助功能页。没有自动走完首设，没有修改语言/错误/首设标志。

## 复现

在 `runtime/analysis/` 中运行：

```bash
python3 check-natural-gtk-input.py
```

脚本自行创建私有 Xvfb，调用真实 `menu-native.py --display gtk --natural-boot` 入口，使用 xdotool 真实鼠标点击 GTK companion 面板、在 QEMU 窗口发送键盘事件，并用 F12 请求原快照。测试只读取控件几何，没有 mock VM、直接调用按钮回调或强制切换固件页面。结束只关闭自己的 launcher、VM 和 Xvfb。

交互使用入口：

```bash
python3 menu-native.py --natural-boot --display gtk
```

自然 profile 不设置 `MENU_INJECT_KEY=auto-firstboot`。方向键导航、Enter 确认；当前未验证的按键与拨轮仍受各自限制。

## 本次证据

本地运行目录：`runtime/analysis/menu-runs/run-l4we7h7v/`。`gtk-input-proof.json` 为自动化当轮结果；主会话随后逐张核对实际画面，并将六张 QEMU 窗口截图中的 LCD 区域 `(0,76,640,556)` 与对应640×480原快照逐字节比对，六项完全相同。这项窗口比对是后续独立检查，没有追溯算入原脚本的断言。

| 操作 | 实际原画面 | 已提交并读回的模型数 |
| --- | --- | ---: |
| 初始 | 日本语高亮 | 753 |
| 面板鼠标 DOWN | Français 高亮 | 851 |
| QEMU窗口键盘 UP | 回到日本语 | 941 |
| 等待60秒，再鼠标 DOWN | Français 高亮 | 4034 |
| 再键盘 UP | 回到日本语 | 4122 |
| 面板鼠标 ENTER | 原辅助功能设置提示 | 4217 |

![初始语言页](before.png)
![60秒后的鼠标下键](late-mouse-down.png)
![60秒后的键盘上键](late-keyboard-up.png)
![鼠标确认后原页面推进](mouse-enter.png)

原来失败运行中观测到的489次发送不能直接当作队列 pending 数。本次最后状态有4217份真实模型提交、完整860字节容器校验、guest 持久文件读回和原消息释放；原 AP 模型字节保留，输入 FNV64 `e45054b418261e91` 与此前独立捕获的748字节原消息一致。

构建身份：

```text
observer SHA256 44d81888e22884bd3ed9c20d7e48b21653862299a0ac945635662b5d936b5da1
sources SHA256  ae3629d1b3fa0949c8a815a49f19f28301076e9e0f4bdb4adb0e419e7d562287
原 appFw SHA256 2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b
选定 cpio inject-key SHA256 78f1927a9a55dd7fecdf81e109e18e6d618d3711fde885f191be85daf479939a
选定 cpio gui-model-export SHA256 d1ef62cd795d09fdc707e6c07fb8be6630ef67e56364bf739726c9574a5e0ee9
最终模型容器 SHA256 5b6c89cf3974478dde29df7fb7b06efaa8fe2f9ebaf30b284b19f9a290b98fbc
```

## 修复与边界

- `virtual-six-v1` 是显式启用的有限进程内模型状态存储。它处理原 CP 公开转发目的地 `0x9088076b`，校验六类内联模型、保存并实际读回状态、释放原消息，不发送业务 ACK。
- 自然启动恢复使用独立 `inject-key --app` 完整32字节按下/松开消息；实验单槽邮箱不再是默认通道。
- 固定 F4、1/125 秒、ISO100 目前是虚拟配置元数据，**原固件曝光查询尚未接通**。完整 CP 版本/订阅/合成、实时取景、拍照录像及 SD 跨运行持久化不在本次通过范围。
- 只验收了上述首设页面和指定按键，不推广为全部页面、全部按键或完整相机仿真。

上一轮 `run-c7mako8s` 在第一张截图的模型导出阶段失败：guest BusyBox 没有 base64，报告保留 `ok:false`。修复使用有界专用 `gui-model-export`，增加其选定 cpio 身份检查和完整容器 FNV64；没有把该失败改成成功。

回归：native host 单测45 passed、21 skipped、102 subtests；21项为未指定历史运行/可选libfdt的检查，未算通过。另有控制台11项、UI controls7项通过；原项目约定回归244 passed、1 skipped、58 subtests，脚本同步检查通过。导出器修复后重新运行 native host 单测及原 HOSD fixture 完整性测试，均通过。
