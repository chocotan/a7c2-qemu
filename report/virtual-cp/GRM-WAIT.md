# 输入未消费：GRM绘制等待的离线定位

**范围：仅本机ALLLANG QEMU。尚未恢复拍照，也没有证明重复输入导致阻塞。**

## 结论与下一步

`run-777jwuoo` 的TID441并未退出：同一线程在原
`GraphicsEngine::drawFramebuffer()` 路径等待GRM信号量 `0x02886043`。
这解释采样时它为何不能继续接收输入，但尚未定位谁持有该信号量、哪条回复未完成，
也不证明死锁或永久无法恢复。不能通过额外 `osal_sig_sem`、空ACK或跳过绘制来解锁。

下一次只读采样同时覆盖 `ExternalOSDIF`、`grm_result`、`grm_gpe`，对照原
`0x6003/0x6005` 回复处理及真实的headless像素消费/持久化记录。
`collect_passive` 上限由12改为16，并继续列出所有被上限排除的线程；不ptrace、
不SIGSTOP、不修改guest状态。主机采样回归组为13 passed，不代表guest功能通过。

## Evidence：原始运行与身份

相对运行目录为 `runtime/analysis/menu-runs/run-777jwuoo/`，其被动样本在
`ee-passive-74g2u0t0/`。采样前后syscall解析结果相同，非原子全线程快照。

| 证据 | SHA-256 / 内容 |
|---|---|
| 原 `libObj.so` | `c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc` |
| 原 `appFw.so` | `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b` |
| `thread-441-stack.txt` | `fa958506230c5f9337527ef1cd0f11ef8717e975459f0cfdd0c02013381fc78d` |
| `maps.txt` | `3f12fc6b1ae31c0fd0dda6a03439f256a59e1bba135e0cdf4d537785ddf8ee93` |
| 线程状态 | `Name=AppFw`, `State=S`, `TracerPid=0`, `wchan=osal_wai_sem_tmo` |
| syscall | ioctl 29，request `0xffffffff80000001`，SP `0x7f418d3680`，PC `0x7fb1948cbc` |
| wait参数 | 栈 `SP+0x20`：sem `0x02886043`；`SP+0x28`：timeout `0xffffffff` |

## Finding：帧链而非散落的代码指针

原 `libc ioctl+0xc`（ELF VA `0xc1cbc`）为不调整SP的syscall叶包装。
原 `libosal_uipc u_osal_wai_sem_tmo` 在ELF VA `0x37b0` 保存x29/x30并分配48B，
`0x37b8` 设置x29=SP，`0x37e0` 调ioctl。因此本样本可以从已记录SP恢复第一条帧记录，
而不是把任意栈字当返回地址。以下saved_fp均16B对齐、严格递增、在采样4096B内，
LR按同次maps解析为可执行映射；最后一跳超出样本即停止。

| frame record | saved_fp | LR / 对应原调用 |
|---|---|---|
| `0x7f418d3680` | `0x7f418d36b0` | `libosal_uipc+0x4a34`：`0x4a30` 调 `u_osal_wai_sem_tmo` |
| `0x7f418d36b0` | `0x7f418d3900` | `menu-observe+0x2b390`，我方观察器帧，不冒充原固件 |
| `0x7f418d3900` | `0x7f418d3960` | `libObj+0x1027ac`：`0x1027a8` 调 `osal_wai_sem_tmo` |
| `0x7f418d3960` | `0x7f418d3970` | `libObj+0xf8458`：`0xf8454` 调 `0xf7724` |
| `0x7f418d3970` | `0x7f418d3990` | `libObj+0xf8e0c`：`0xf8e08` 调 `0xf843c` |
| `0x7f418d3990` | `0x7f418d39a0` | `libObj+0x174e9c`：`0x174e98` 调 `0x1636f8` |
| `0x7f418d39a0` | `0x7f418d39e0` | `appFw+0x1798fcc`：`0x1798fc8` 调 `drawFramebuffer` |
| `0x7f418d39e0` | `0x7f418d3a10` | `appFw+0x179a440`：`0x179a43c` 调 `0x1798f24` |
| `0x7f418d3a10` | `0x7f418d3de0` | `appFw+0x1796ef4`，主循环调用者 |
| `0x7f418d3de0` | `0x7f418d4940` | `appFw+0x36ec1b0`；下一帧超出已保存范围，不再解读 |

这里存在两个尾调用：`libObj+0x1636f8` 从函数表 `+0x78` 间接跳转；
`0xf7724` 加载对象 `+0x48` 的信号量对象后尾跳 `0x102798`。
尾调用不新增帧，不能因帧链缺这两行就否定它们；最终目标仍以原字节和已保存LR交叉核对。

## Path：原释放条件与尚未证明的部分

原 `libObj+0xf8df0` 先调用 `0xf843c`；后者经 `0xf7724` 获取
ExternalOSDIF对象 `+0x48` 的信号量，再进入其后续操作。`0x102798` 是带原
`Util/Semaphore.cpp`/`grm::Semaphore::lock()`诊断字符串的无限等待包装。

原 `ExternalOSDIF::handleExternalMsg`（`0xf78ec`）按消息头选择：

- `0x6003 → 0xf7790`；
- `0x6005 → 0xf789c`。

两条处理分支均检查同一类 `object+0x48` 信号量，必要时调用原unlock
`0x1027d8`，并调用/清除 `object+0x50` 的回调。静态分支不证明本run已收到
消息或执行unlock；该对象的运行身份及阻塞另一侧仍需捕获。
`headless-osd.c` 只在完整请求匹配、真实像素快照持久化及原消息释放成功后回送
相应回复；现不能跳过这些条件补发ACK。

### 晚加载LIRO的独占风险

本run先有 `OSD_HEADLESS_STARTUP_QUEUE`/`OSD_HEADLESS_STARTED`，随后原appFw在
`151.406245` 开始加载 `liro.ko`，`152.792614` 初始化返回0，后续线程列表出现
`liro-kliro_147`。因此headless的启动时无LIRO检查不是持续独占证明。
已有 `analysis/qemu-boot-research/liro-osd/verify-evidence.py` 重新执行通过：
原av-cam的task147描述、激活指令与其三个OSD端点接收循环存在。该静态报告中的
原接收入口为raw `0x2ebac4`，按 `1002` 的body+8转向84d/84e；真实传输还依赖
DMM、`0x9281074e`对端和interchip回调，不能用一个模块名判断这些步骤已完成。

这是**第二消费者可能晚加入**的明确风险，不是本run消息被其取走的直接证据。
线程名存在也不证明task147已激活或正在接收。下一次需核对内核task147的等待位置
及相关队列状态，不能直接禁用整个LIRO（它也承载成像链），更不能补ACK碰运气。

重复原始事件 `0x66` 另有合法自动重复机制：word3为`prev_status`，word5为`repeat`，
word6为`from_type`。原repeat计数在 `0x7fffffff` 饱和，没有已证的 `0x58` 特殊退出。
原appFw转换还会在缺少initial-press状态时把repeat转换为无事件标记
`0x20000001`。因此“88个repeat之后不收键”仅是时间顺序，不能归因于custom-key回调。

原件复核使用窄窗口，例如在成果目录下：

```bash
N=runtime/analysis
aarch64-linux-gnu-objdump -d --start-address=0xf843c --stop-address=0xf8480 "$N/menu-root/usr/lib/libObj.so"
aarch64-linux-gnu-objdump -d --start-address=0x102798 --stop-address=0x1027d8 "$N/menu-root/usr/lib/libObj.so"
aarch64-linux-gnu-objdump -d --start-address=0x1798fa8 --stop-address=0x1798fe0 "$N/menu-root/usr/lib/appFw.so"
```

公开代码包不携带上述原固件及私有运行产物；复核需要已授权的本机ALLLANG资产。

## 后续原运行：run-0kfp8qri

该run清单确认 `natural_imaging_profile=true`、SMP2、RC和未压缩YC均已实际启用。
原 `FRAME_SEM_WAIT_ENTER call=4` 等待 `0x02886043`，只有前三次wait返回；原screen
仍只到 `0x308/0x12d`。主会话实际查看 `gtk-before.png` 为全黑，不能当语言页。
中文字体导航检查失败，快门未执行，因此Still/JPEG没有得到有效测试。

清理阶段原flush/STOP超时，报告记录cancel已arm但没有flush回复；VM按保护逻辑保留，
不是导出成功。运行锁仍属于本run的原probe。新的op28模块安装以非阻塞锁忙75退出，
没有改变其资产。接下来仅采集GRM/LIRO等待与媒体globals在整卡摘要前后的状态；
不人为释放信号量、不强杀、不与新VM重叠。恢复证据不满足则继续保留并报告阻塞。

### 保留VM已完成清理

`recovery-card-sha.txt` 的原openssl输出使用 `SHA2-256(...)`，首轮恢复脚本只匹配
`SHA256(...)` 导致未判通过；该失败JSON保持不动。后续离线严格解析两条完整摘要，
确认guest `file-media-config.so` 与本run资产摘要一致，整卡SHA为种子
`61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`。
摘要前后媒体owner、mounted/retired drive、inflight、busy、cancel、async write均0，
配置调用1，故该run满足“未挂载、未写入的可丢弃虚拟卡”恢复条件。

`bac2a5c5d` 已完成正常SIGINT/finally退出原probe，随后仅清理其host GTK和私有Xvfb；
退出、运行锁释放均确认，没有SIGKILL或终止其他实例。结果保存于本run
`recovery-pristine-card-proof.json`。**原flush未成功、card未导出，照片/录像未生成**。
测试20分钟超时后host GUI仍保留且定时截图，造成长时间运行表象；不能再把这种
cleanup保留状态描述为正在等待拍摄实验结果。

额外运行证据：`recovery-liro-osd.txt` 的task147内核栈停在KVA
`0xffffffc0012eb654` 的receive路径；AP `ExternalOSDIF`也等receive，AppFw等GRM。
这些是等待位置，不单独证明谁抢走了哪个OSD消息；下一轮先解析原指令与等待SID，
不盲重跑长时间中文导航。

### 基线复验成功，语言功能没有失效

用户要求重新截图后，`bf81bee11` / `run-wu6ypman` 复用此前成功的基础GTK配置，
明确不加入YC/RC/SMP2组合，再次完成简体中文、每页首设、教程退出和原拍摄HUD。
主会话实际查看两张新截图；语言选择像素SHA `b51c4da5c04e7e1fb7f7ea1026cb18a52d126147aca2f9a1aa7201360d803fb7`，
HUD像素SHA `8718e2251bd284e3c75c91bde990f55cbb417b881b7b254c14f7ae3095944242`，与之前基线一致。
这两个是像素摘要，不是重新保存PNG容器的文件摘要。
`gtk-input-proof.json` 记录 `automation_completed=true`、`shooting_screen_created=true`，
无cleanup错误/保留资源，运行锁释放。任务正常退出，中央预览仍黑，尚未拍照。
因此实验组合的黑屏与GRM等待不应表述为“中文失效”。

## task147等待的具体协议：不是可以空ACK的控制查询

只读代理已完成此项调查，main以窄窗口复核av-cam `2eb458..490/2eb5f8..678`，
以及CP Thumb `47198c..19e6` 原字节。av-cam下文用raw，KVA基址仍为`0xffffffc001000000`；
CP用raw，运行VA为raw+`0x108000`。

task147原接收公共更新后，`1003/1005`分支调用`SetTransferDate@2eac74`；
返回0的分支`2eb48c→2eb5f8`创建动态回复队列D，向`9281074e`发送8B的`2001`，
再`2eb650`永久等D。`2eb654`是该receive返回后的指令，不是初始化入口本身。
原CP `osdTrans`接收循环`aed10a`服务`9281074e`；分支`47198c..19e2`
取得实际槽描述，分配32B回复`7001`并发回D，其中`+8=Handle`、`+10=Addr(u64)`、
`+18=Size`。av-cam随后原样取这三项，再进入interchip transfer；没有真实缓冲描述
不能靠空回复解除等待。其后才是传输完成event、`2002`、AP `6003/6005`。

headless软件路径并不实现该CP槽服务。两条路径使用同一公共OSD更新队列是静态事实，
但没有逐消息记录证明哪个消费者取走了失败帧，仍不能断言“抢消息”。基础成功run同样
加载了liro，单凭模块存在不能解释差异。后续应比较基线task147栈与失败栈，必要时
只观测kernel原send/receive参数/D/实际7001，不能额外receive消费消息。
