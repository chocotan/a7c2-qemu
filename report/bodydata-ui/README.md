# 默认 BODYDATA → 新版单窗口验收

`run-9cxkhduu` 从本成果目录直接执行 **`./start.sh`，无`--bodydata`或`--cache`**：自动找到`incoming/bodydata/BODYDATA.DAT`，在默认`runtime/bodydata-cache/`创建全新stage，真实`CXD90057_k8`解密并识别model`20030014`、version2.01、region0；完成官方输入/已有runtime/中文资源校验后打开新版窗口。

这次只有一个可见GTK窗口，QEMU使用none后端；默认停原语言首设，没有自动写语言/日期/首设标志。真实XTest Down使日本语→Français，Up再回日本语：窗口橙条中心y`423→486→423`；原640×480显示帧同时核对。主会话亲自看图后将独立proof标为通过。键盘输入可在自动LCD刷新期间进入后端已有有界队列。

![初始原语言页](language-before.png)
![实际Down后原语言页](language-down.png)
![新版单窗口、实际Up后](ui-after-up.png)

关闭窗口走原`Fsys_FlushVolume`成功→停止owner→逐块读回→整卡SHA/fsck→保存，完成后VM和窗口退出；`SD/card.img` SHA256为`61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`。不是把初始化模板复制当作保存。

更早的`run-4hr8kugf`已通过指定已验证cache的同一路径；`ui.png`保留其Down画面，截图时Up的下一帧仍在途。最新验收增加窗口实际高亮内容等待，`ui-after-up.png`才是Up完成后的画面。其它超时、窗口标题误配、并发Xdisplay/资产锁和冻结源漏脚本失败未改写为成功。

本验收不覆盖完整首设后主界面稳定性、全部按键/三个拨盘、镜头/CMOS/AF、原固件拍照录像。它证明的是用户给官方包后真实启动新版窗口、基本输入/显示及保存后关闭。
