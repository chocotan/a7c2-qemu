# 启动条件是否导致当前存储卡错误：对照与待证项

这是用户提出的因果假设，不应先排除。当前仅证明原UI显示“无法读取存储卡”，
尚未抓到选中的具体caution ID或原Fsys失败返回，不能把错误页直接归因为虚拟SD格式。
本研究不盲改boot type、不直接启用未知初始化ABI、不加载真实MMIO驱动、不写物理盘。

**后续纠正：group311/31e与b1c..b3d是语言可用性列表，不是存储错误predicate。**
其中b1d输入1与选中b1d不能用来证明SD或挂载故障。本文下面保留的筛选地址只解释启动语言页；
真实存储错误出现在后续dlg_dbl021，须另取dialog消息ID/生产者。

## 已核启动条件

| 条件 | 当前证据 | 能否排除 |
|---|---|---|
| `dmode=3` | 原bootin.elf内帮助文字：0 kernel only、1 Global Infra、2 LIRO、3 APP default | 它是默认APP阶段，并非证据所称异常启动模式；完整consumer影响仍应沿原代码核对 |
| app mode | 当前没有传adj/usbj；原help注明normal为default | 未显式选择调整/USB充电模式，不等于所有loader字段已正确 |
| `QEMU_BOOT_TYPE=1` | seed-power-on写Backup0051004a，缺省mode2/eecap1/bis1，逐word读回 | 这是显式实验loader描述，不能仅凭合法范围宣称与真机冷启动完全一致；原UPM consumer正核查 |
| 自动MENU | frame返回后发送ON/OFF，可能与boot完成交错 | 尚不能排除，已启动相同observer/cpio取消MENU的单变量对照 |
| `target=qemu`与IMDB过滤 | 固定派生libIMDB清除10个服务的初始化mask | 不是只过滤USB；包含媒体电源管理，必须核查因果关系 |

原bootin帮助字符串直接取自native原件file offsets3b01..3d3b，无运行或改写该二进制：

```text
<debug_mode> : 0: kenrnel only
             : 1: Global Infra
             : 2: LIRO
             : 3: APP. default.
<app_argv>  : adj -- adjust mode
             : usbj -- USB charge mode
             : normal -- notmal boot. default.
```

## 原启动语言列表，不用它诊断mount

原scr0039_boot在ELF209f0a0..124调用`1b6b224(311)`，非零时选择screen12d。
311映射31e，原组含34个caution，IDs b1c..b3d。
scr0099的20bc7cc将选中项解析为实际caution ID，并通过getter2863b5c写model39e。
当前还没有证明当前ID等于单独命名的mount错误234/235，不可跨过这一链接。

主会话已独立反汇编getter并加入原进程只读采集：

| 字段 | getter ELFVA | 原model数据ELFVA |
|---|---|---|
| caution group399 | 2863a94 | 7e68b50 |
| selected caution39e | 2863b5c | 7e68bc8 |
| group selector输入 | 286b5b4 | 7e72080 |
| 首项b1c predicate输入 | 2881f1c | 7ecc6c8 |
| 第二项b1d predicate输入 | 2881f44 | 7ecc6e0 |

地址均为appFw ELFVA，由该run实际bias换算；没有写这些model或直接调用caution selector。
未知selected ID之前，最后两项仅是原表前两项的输入，不假定当前选中了它们。

## 具体启动过滤候选

native `prepare-assets.py::SKIP`包含10项：
libUsbBusPower、libInfraUsbCmn、libsensapi、libUsbControl、libBusPower、libHotplug、
libInfraCrypt、**libInfraMediaPwrMgr**、libNetServiceTethering、libTetheringResource。
BusPower/Crypt后来已由显式路径恢复相应原API，但媒体电源初始化目前没有相同恢复证据。
因此它是环境差异候选，不是已证明根因；直接load库也不等于正确执行原初始化。
追加调查已核native资产/固定inventory无此库，也无相关导出，不能仅重新打开mask恢复不存在的provider。
原IMDB203e8记录名字`InfraMediaPwrMgr_init`，原im.elf405f5c加载/dlsym，40602c不准备参数调用，
证明caller期望void(void)初始化，而非需要NULL context；这不证明缺失provider的具体实现。
若以后恢复，必须先得到native范围内合规的原provider并验证身份，沿原im.elf初始化及act/inact生命周期执行。
目前不创建占位库、不强行设媒体ready，也没有证据将此缺失项与显示的存储dialog连为同因。

## 当前最小对照

无MENU实验沿用同一已构建observer/cpio（SKIP_REBUILD=1），所有服务、boot type1、dmode3保持一致，
仅unset MENU_INJECT_KEY；新增diagnostic只读caution ID和相关输入。
需要核对两轮selected image SHA、compiled observer SHA及实际启动参数，避免源码不同混成单变量实验。
对照已返回：baseline=`run-cxj7qh2s`，无MENU=`run-sjspmvwk`，原cpio和observer摘要及记录profile一致，
无MENU时没有KEY_INJECT记录，实际启动命令和power-on record相同，RGBA逐字节一致。
因此自动MENU不是该错误图像出现的必要条件；不据此排除其它启动环境差异。
无MENU读到group311、selected b1d、selector1、b1c/b1d输入均1；这些解释语言页，不是SD故障证据。
原UPM分支核查和真实dlg_dbl021消息/producer采集继续，boot-record正确性尚未证明。

对照验证器2测试/4负例已通过：更换镜像、observer、boot type或混入按键记录，均不能形成有效单变量结论。
正式`startup-menu-comparison-proof.json`确认相同原图RGBA摘要与相同记录配置，
但sd_or_mount_failure_proven、boot_record_correctness_proven、shooting_main_screen_verified均false。

UPM定点结果已领取：原setup确实读0051004a/128B，从record+4复制字段；原默认函数把同一mode字段设2。
主会话独立核objdump存储指令，这支持seed的mode2来源，不证明type/eecap/bis等全部实验描述正确。
原额外0051000f还存在覆盖分支，未找到本函数直接触发SD错误的证据；详见
`startup-caution-controls/UPM-RECORD.md`，保留boot_record_correctness_proven=false。
