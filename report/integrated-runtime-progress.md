# 集成运行链进展（尚未完成全部相机功能）

## 用户最终目标

官方 BODYDATA 放入指定目录后自动解包启动；`overwrite/` 按 guest 相对路径覆盖派生系统；新版单窗口 UI；全部按键/三拨盘、镜头/CMOS/AF、原固件拍照录像、虚拟 SD 和指定输出目录逐项验证。不得以显示控件、主机截图/录屏或独立生成文件替代原固件消费与产物证据。

## 已接入的入口

在本成果目录下默认使用 `incoming/bodydata/BODYDATA.DAT`，运行：

```bash
python3 runtime/analysis/bodydata-launch.py
```

当前仅支持已核 ILCE-7CM2 **2.01 ALLLANG**。包保持只读，缓存以包 SHA256 命名；实际选中的包即使遇到已有 runtime 也必须重新通过输入摘要检查。目录里有多个包时拒绝猜测。未知版本不会靠改 pin 假装支持。

```bash
python3 runtime/analysis/bodydata-launch.py --bodydata /path/BODYDATA.DAT --prepare-only
python3 runtime/analysis/bodydata-launch.py --overwrite-dir /path/overwrite
```

覆盖示例 `overwrite/usr/lib/appFw.so` 对应 guest `/usr/lib/appFw.so`。默认目录为本成果下的 `overwrite/`；不修改官方包与基础资产，而生成本次运行的独立 newc。无文件名白名单，仍拒绝路径逃逸、symlink 源/祖先、特殊文件和不安全目录替换。每项 old/new SHA、最终镜像 SHA 均记录；库实际变更时 `original_libraries_unchanged=false`。任意实质代码修改与固定 VA 探针的兼容性仍需用户实验，不由文件替换成功推导。

## 内容型证据

| 项目 | 当前证据 | 尚不能推广为 |
| --- | --- | --- |
| BODYDATA 自动解密/导入 | 原包 SHA `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`，真实解密、2.01 识别，缓存约2.2GB/144项，生产 prepare-only 完整通过 | 任意版本支持、完整硬件仿真 |
| 中文字体 | 官方 `0800_appli/tmp/images` 的 Big5/GB18030 与原 appli.sum CRC一致，guest SHA256读回正确；实际简中首设和阅读器“以后设置”画面 | 清除首设/地区标志 |
| GUI 模型 | 最初 public `9088076b` 无接收造成原消息未释放；后续取消六类限制，GMDL0003保留全部结构合法的原始内联包、读回、原free，无业务ACK | 原 CP 模型版本/订阅/合成已实现 |
| SD 容量 | 原 `DATABASE.BIN` 请求 `0x939000` 字节，在4MiB卡回`80000082`；128MiB FAT16上原 Fsys写满9670656字节并创建M4ROOT/MEDIAPRO.XML | SD跨运行导出/回载已完成 |
| 原主界面/MENU | `run-fzacelas` 逐步中文首设后真实出现 J-FINE/14M/AF-S 主界面及中文菜单 | 稳定运行通过：晚发系统错误仍在查 |
| 新版单窗UI | `run-z5js_38f` 实际GTK ON/DOWN/UP/OFF，正确原LCD高亮、1个可见窗口；13项host交互测试；显示来自QMP ramfb真实帧 | 快门/REC/三轮等固件语义全通过 |
| overwrite | `run-ea3o4d7s` 替换仅加未执行ELF尾标记的appFw及新etc文件，selected新SHA、custom标签及真实初始画面通过，官方原文件摘要未变 | 任意功能补丁已验证 |

## 当前晚发系统错误

128MiB 已解决数据库写入失败，但独立等待后仍出现原 screen `0x30c`。实际帧栈回到 `1e78dbc` 的切屏队列；只读采样事件type3，`+8/+c=0100012e`。原event字符串为 `MODEL_SYSTEM_ERROR`；唯一已核立即数发送分支 `appFw VA 2dbf3f8..2dbf458` 在 `2dbf424` 构造事件，经 `24cb2d4` 发送，并记录 `INFRA_NOTIFY_BLUETOOTH_ERROR`。与是否点击MENU无关，不得清这个错误或屏蔽事件。

`libBTUtils` 的原 `BTBlog::errorPlace` 透传记录已定位实际分支：ResourceBluetooth的501行只是原ALLLANG保留地址`FF FF FF FF FF FE`警告，该1000请求最终仍回0；不能将最早日志当成失败。真正命中的是Core `startBcmBsaServerCommon` 的730行：等待 `/tmp_bt/bt-daemon-socket` 探测耗尽返回-1。原 `startBTCore.sh` 需要UART上的BSA控制器。正在实现显式有状态HCI候选供原BSA运行，不创建空socket、不屏蔽原ERROR；尚未证明合法disabled路线。

## 仍在接线/调查

- 原 Fsys_FlushVolume → guest进程冻结 →4MiB预留RAM窗口/QMP分块 →逐块FNV+全SHA+只读fsck →run/SD/card.img 已真实通过；下一run原Fsys直接打开既有数据库/XML、未重建。完整摘要与边界见 [原固件SD持久化证据](native-sd-persistence.md)。新UI自动保存关闭和同VM连续ON/OFF已过；新取消握手69项主机测试和新真实两次ON/OFF亦过，异常控制流独立复审中。
- 物理键配置来自 Backup `007a0001`，业务事件不能直接充当App输入码。额外按键与三轮映射尚在核；禁用控件不是功能完成。
- LensCommunicator已有12/20B查询，但原CP `4084d8`的10B镜头数据语义尚未闭合；固定曝光目前仅为虚拟配置元数据。
- 原 CMOS 输入、AF、capture、encoder及实际照片/录像文件尚未完成。数据库/XML等由原固件创建的文件，不是拍照录像产物。

运行中证据保留在 `runtime/analysis/menu-runs/`，每轮冻结C源码与选定cpio身份。候选主界面对象创建或按键发送0不会自动标为验收成功；实际失败图和旧失败JSON保留。
