# 原固件虚拟 SD：写入、导出和跨运行回载

本验证通过的范围是**原固件创建数据库/XML、保存完整卡镜像并在下一次运行重新消费**。尚未生成原固件照片或录像。

## 为什么原4MiB夹具不足

原 `Fsys_Write` 请求向 `A:/PRIVATE/DATABASE/DATABASE.BIN` 写入 `0x939000`（9,670,656）字节，4MiB卡返回 `0x80000082`。扩大为独立128MiB FAT16仿真卡后，原Fsys成功写满该文件，创建M4ROOT目录及XML，卡错误路径消失。4MiB镜像保留为独立队列/Fsys测试夹具，不再充当默认相机卡。

## 导出证据

`run-sorjzuqm` 中使用原 `Fsys_FlushVolume('A')`，返回0后写入带新序号的回复并 `SIGSTOP` 原驱动owner进程。宿主核实 `/proc/216/status` 为停止状态；没有将 `sync` 或静态模板复制当成Fsys刷新。

- 实际guest backing：`/image_mmca`，134,217,728字节。
- 刷新序号：`802269086685233`；drive65，即`A`；原返回0。
- 32个4MiB分块：guest原inode/长度/mtime/ctime稳定；每块guest FNV64与QMP读回匹配。
- 最终镜像SHA256：`b1af531c9d5e92d1aeaf53117aa0f120acbf7fbbeda8f039a8136420bf7071c2`。
- `fsck.fat -n` 返回0后原子发布 `run-sorjzuqm/SD/card.img`。
- 本次选定cpio中的 `simulation/sd-window-export` SHA256：`67130649b72c168f744a0411a2f558d3ebc6b0c79480f8a0b771d211c0c41331`。

从此真实镜像解析得到：

| 原固件文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `/PRIVATE/DATABASE/DATABASE.BIN` | 9670656 | `846cd5ac1440af2b3db24aac60fe10586feb88ff18712dabf13e7f2058a3639a` |
| `/PRIVATE/M4ROOT/MEDIAPRO.XML` | 406 | `bba75a99bc3896c45af2ee53770cfe9e3e0c2b0a27fe5f3bea88609c81fd33c5` |

镜像与逐块原始读回在私有run目录；公开成果提供工具、校验方法与摘要，不附Sony数据文件。

## 下一运行实际消费

`run-3c565fso` 将上一镜像作为普通虚拟文件seed，source与选定cpio的 `simulation/sd-card.fat` 摘要均为上述 `b1af...`。原固件日志依次记录：

```text
Mount /nondev/rm2 flags=0x300 result=0
Open A:/PRIVATE/DATABASE/DATABASE.BIN flags=0x3 result=0
Open A:/PRIVATE/M4ROOT/MEDIAPRO.XML flags=0x3 result=0
Seek XML offset=406 result=0
```

这次没有重新写入 `0x939000` 字节数据库。`sd-reload-proof.json` 记录选定cpio身份与既有文件打开结果。不是只把卡文件放进启动包却未被固件打开。

## 隔离与边界

SD窗口为 `[0x41e600000,0x41ea00000)`；原scanout是相邻的 `[0x41e100000,0x41e600000)`。二者实际访问范围不重叠。新增独立memrsv条目曾触发原kernel最多16项的保护，失败run `run-n1fafxxh` 未启动QEMU；修复为单条9MiB连续预留，保留原表上限与各子窗口边界，未扩大viewer映射或挪用显示像素当SD缓存。

源卡路径只接受普通文件；逐级无symlink目录FD和`O_NOFOLLOW`固定源inode，拒绝设备/FIFO，读前后核身份变化。刷新/冻结或传输失败将写`ok:false`，不覆盖未知旧卡，也不把旧成功报告留作本次成功。恢复原owner放在`finally`，避免导出错误让相机永久停住。

新版入口的续卡方式：

```bash
./start.sh --sd-image /path/to/previous-run/SD/card.img
```

## 最新连续ON/OFF与窗口关闭

`check-sd-console-cycle.py` 已用原固件写过的`b1af...`卡，在**同一个VM对象**连续完成两次ON/OFF：`run-c_nkzggu`、`run-rzwvzkey`。每次选定cpio seed摘要与上一张保存卡相同；原Fsys成功打开数据库/XML、没有重建；OFF走原刷新、停止、32块读回、fsck0，输出仍为`b1af...`；原输入卡摘要保持不变。第二次ON的manifest source路径为第一次本次保存卡，验证了`card_seed`实际使用，而非只设置了host字段。

```bash
cd runtime/analysis
python3 check-sd-console-cycle.py --seed /path/to/camera-written/SD/card.img
```

新版单窗 `run-9cxkhduu` 的实际WM关闭事件也已自动保存后退出，见 [默认入口/窗口验收](bodydata-ui/README.md)。仅停在初始语言页的空卡SHA`61b905...`尚未创建数据库，这是正常范围；一次误用该空卡做“必须打开DB”实验按真实失败保留，未计持久化失败或成功。内容检查使用完成过首设的卡，不混淆二者。

原相机热插拔、照片/录像、任意大容量几何、物理SD均不在本次通过范围。

## 待补异常边界（独立review后重开）

以上真实内容型验证保留。独立评审发现的两个P1已集成修复：host export RPC保存期间无硬截止等待（UI关闭等待到期只报未完成并保留）；per-seq原子reply/cancel/cancelled握手使host先取消再核回复、guest先发布回复再核取消，晚flush不会在host漏恢复后无条件STOP。有成功回复时等待真实T或guest取消确认，CONT后确认已离T；任何清理失败强制最终整体报告false，单独保留数据验证结果。

新主机69项测试、41子测试通过，涵盖C侧交错/IO失败、实际shell进程状态恢复和最终报告。新真实guest`run-cp5r_g49`、`run-ugaur9k1`又在同VM对象完成两次ON/OFF：旧数据库/XML被原Fsys打开且未重建，selected/source/save均为`b1af...`，输入不变，`SD/export.json`的`flush_lifecycle`明确为`ok:true/status:resumed`。新版窗口长测`run-miw820mp`手动保存及关闭也成功恢复owner，所得实际卡SHA为`3ff1f515ee52e39be0702c6965e261721a9f2db14ce5990662bf7f2ebb91b735`；UI晚发黑屏另行调查，不将其计作稳定拍摄界面。

真实guest尚未注入迟到flush故障；正常STOP/CONT已执行，异常交错由主机C/shell测试覆盖。后续复审又找出父端fault抢断导出、取消确认写失败后无重试、最终报告ENOSPC遗早期成功、窗口close吞进程清理错误四项；不能据前述正常运行把这些边界算通过。

本轮已实现：导出RPC期间不响应会杀VM的取消/monitor中断；有SD的会话在固件异常后保留为`faulted`，拒绝相机键/快照但保留可信SD保存和关闭；数据刚发布时整体报告仍false，owner恢复完成才发布true，最终报告失败仍保留已写卡摘要用于重试；owned进程清理失败明确报告并保留其句柄，重试只清理该进程，未清理时禁止新ON。guest取消确认失败保存原seq，独立100ms管理线程只重试确认，不读新请求、不调用Fsys/STOP；原flush仍在原模型线程，旧tombstone保留，失败日志有界。

最新收口回归为**80 passed、46 subtests**；C侧19个ASan/UBSan场景、实际shell状态恢复、socket故障、执行实际SDK closure的旧序号重试、最终报告失败和owned进程清理均在其中。另有24项GTK/XTest验证界面与故障态隔离。所有已知评审问题已修；这不等于真实guest异常注入通过。

当前`file-media-config.c`相同摘要又经`run-n2pgxkys→run-cxvxzuhu`在同VM两次ON/OFF验证：旧数据库/XML被原Fsys打开、未重建；源/选定cpio/保存卡均为`b1af...`；每次32块、fsck0、`card_published:true`及`flush_lifecycle.status:resumed`，原输入卡未变。独立确认线程的非空绑定和实际创建日志在`run-phyxlklp`可见；此前日志没镜像到console不能作“线程没运行”的证据。

因此本成果的普通虚拟SD保存/回载/关闭/同窗再ON已通过限定验收。真实guest的迟到flush、ENOSPC和确认写失败尚未注入，异常交错由host实际C/shell测试覆盖；硬崩溃时未保存RAM的恢复、热插拔、任意容量几何及原照片/录像不在此完成范围。
