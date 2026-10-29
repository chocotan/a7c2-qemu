# 宿主磁盘支撑256GB虚拟SD（接入待验）

## 用户要求与实现选择

用户要求SD不驻guest内存，使用本地磁盘目录、固定256GB。本实验定义为
256,000,000,000B（十进制），宿主实验目录中的普通稀疏虚拟磁盘文件；不打开真实SD、
物理块设备或其他VM镜像。普通目录没有原FAT/扇区/机内格式化语义，故不能把目录
直接映射成“SD已可用”，应由原固件在虚拟盘内创建文件系统和写媒体。

10GiB tmpfs原型暂停，代码和失败证据保留；其512MiB实际数据上限不适用于新目标。
宿主支持256GB逻辑容量并不等于预分配256GB，实际宿主分配随原固件写入增长，
仍需空间检查/真实ENOSPC、原flush和退出持久化保护。

## 接入候选，不是已通过方案

原kernel配置没有virtio PCI/MMIO；已验证的基础UI使用隔离generic-xHCI虚拟总线，
原xhci、scsi_mod、sd_mod、usb-storage模块存在，优先调查QEMU文件支撑USB存储。
只接本地镜像，**不USB host passthrough**。原文件后端64位preadv/pwritev容量足够，
但块节点stat大小通常0，需先核原类型检查和限定设备的BLKGETSIZE64容量适配。
不全局伪造stat、不虚构ready/格式化支持，不只放宽文件大小限制就宣称接通。

原SD状态/flush/导出路线要按新介质真正验证；宿主镜像已有数据时不能在guest运行中
直接fsck或挂载写入。最终只有原flush、停止写入、退出/宿主落盘与只读复核齐备才
称安全保存。10GiB工具的全盘QMP导出不是256GB存储的必然方案，不能让新卡再走
内存全量拷贝。

## 原菜单格式化入口的静态锚点

只读调查已定位`appFw.so`原ELF VA（不是语料FUN名字上的+0x100000地址）：

| 页面/路径 | 已核内容 |
|---|---|
| `scr0076_001_controller` `20ace54/20acf84` | 媒体选择/状态检查后打开screen`15d` |
| screen`15d` | `scr0076_0010`确认页，工厂`1d22f28` |
| handler`20aad80` | cursor5返回，cursor6才进入限制检查/执行；main核原cmp指令 |
| `25eaa7c→25eaa14→25ea7fc` | 原`model_api::detail::media_format`，后开screen`29d` |
| `3375d24` | `sequence_media_format::exec_format`，与UI全部异步调度尚未闭合 |

main实读UTF-8原资源核验：`string_simplifiedchinese.uxc+15a0`为“格式化”，
`string_simplifiedchinese_horizontal.uxc+11884`为“执行格式化”。记录头mask`03ffffff`
分别得资源ID`0204e0e2/0200a804`。另外确认文案为快速格式化会删除全部数据。

“拍摄→媒体→格式化”仅是下一轮应逐页目视核验的顶层候选路径，尚未完整核菜单树，
不能误将底部工具箱认作已证入口。实际操作必须截图核对分类、媒体、目标插槽、
确认、进度与完成/错误；不直接调用上述API/强开screen替代用户菜单行为。

## 当前验收矩阵

- 宿主256GB镜像/虚拟USB连接：未验。
- guest识别容量/大偏移和末扇区读写：未验。
- 原菜单格式化/分区或FAT32重建/重挂载：未验。
- 非零剩余张数：未验（旧128MiB卡的原预算保留300MiB已静态核验）。
- 原JPEG/MP4写入和独立解码：未验。

### 独立256GB虚拟USB传输已通过

`b3f98f6ef` / `menu-runs/host-sd-helper-l4hxathd` 已完成helper-only原驱动实验，
不启动camera app、不调用原Fsys、不格式化。测试盘为独立
`host-sd/transport-check-ri410emt/card.img`，不修改准备好的空用户卡。

原guest驱动枚举块节点后实际容量ioctl返回256000000000B、500000000扇区、512B逻辑扇区；
在offset0、4294967808、255999999488各写不同512B图案，逐项真实fsync=0、guest读回相同。
正常QMP退出确认后，host从原租约fd再次pread三处与独立预期图案全部匹配。
结果`guest_raw_io_verified=true`、`owned_vm_exited=true`、`host_after_exit_readback_verified=true`。
这证明本机文件支撑块传输和本轮退出后数据存在，不等同原Fsys flush/掉电持久化或拍摄。

`host_sd_profile.py`复用既有隔离xHCI profile，磁盘直接挂root USB端口；仅将已锁定普通
文件fd用bwrap `--bind-fd`暴露成`/sd/card.img`，没有目录共享或USB host直通。
普通`/proc/<hostpid>/fd`源挂载在该sandbox中被拒，实际`--bind-fd`方式已独立实测通过。
磁盘使用raw/writeback（不屏蔽flush），真正进入原Fsys仍需选定块设备容量桥和实际fsync。

原 `mcmn_drv_dummy_open` 的stat调用main核为`28c00→50508`，尾跳原`__fxstat64`，返回LR为
`28c04`；同步default_flush导出函数`24c20`确为`mov w0,0; ret`且有GLOB_DAT重定位。
后续适配必须只处理选定虚拟盘、保持原类型/状态，不能把其成功返回当作已落盘。

### 原Fsys块容量与flush适配（运行验证中）

`host-block-sd.c`默认不启用；显式`A7C2_HOST_BLOCK_SD=1`时，将`/dev/sda`与bind后的
`/image_mmca`作为块节点核对dev/inode/rdev、真实容量256000000000和逻辑扇区512。
仅原MediaCommon stat返回地址`dummy_open基址+28c04`且fd身份匹配时，把实际
`BLKGETSIZE64`结果用于st_size；其他fd/stat字段原样透传。不是任意fstat修补。

原default_flush的符号重定位可拦截；适配读取原ctx+98的实际fd并核对同一块节点，
原flush通过后才执行真实`fsync(fd)`，错误返回原系统错误域，不吞失败。
不设置容量覆盖、OMIT_WRITE、格式化能力或ready位。
`bfb112553`：8项host测试及原glibc链接通过（后续新增断言另行回归），仍不算guest原Fsys验收。

下一运行`b44c39cc3`仅在独立新建的256GB诊断盘上由host生成FAT32**测试fixture**，
验证原Fsys普通QTEST文件的挂载、读写、FlushVolume/真实fsync和卸载，再正常退出，
host fsck并独立提取比对测试字节。该步骤绝不能称为“机内格式化成功”；准备给原中文
菜单格式化的`host-sd/card.img`保持空白，且任何测试文件都不是照片/录像。

### 原Fsys首次挂载失败，不能把raw传输扩大为Fsys通过

`b44c39cc3` / `host-sd-helper-5jd3sk_e`先通过11tests+23subtests及构建；
运行原Fsys Init=0，限定块适配器已实际打印BOUND与CAPACITY=256000000000B，
随后原Mount(`/dev/mmca`,flags0)返回`80000000`，测试以10退出；VM正常QMP关闭。
未进入QTEST写入/FlushVolume，不能宣称原同步flush已通过。
原BPB为FAT32，512B扇区、64扇区/cluster，卷总499999941扇区（小于介质500000000），
这只是记录，不直接归因为SDXC/exFAT策略或分区缺失。

后续仅增加选定设备preadv64/pwritev64被动观察：最多24条、每条只读首iov最多64B，
原返回值/errno不变，不向数据缓冲写入，也不改格式/ready/能力字段。
`b08f38efb`运行同一诊断，用新的独立fixture保留原失败；另有只读调查查挂载解析/状态。
失败的guest串口输出也写failed-partial文件，不能只留宿主异常文本。

`b08f38efb` / `host-sd-helper-9d3updq1`复现Mount`80000000`，已正常退出。
原selectedfd4的6次preadv64均读offset0、count1、512B，返回512；首64B与host BPB一致。
没有观测到后续FAT/根目录读取或任何pwritev64。故目前已证能读到原引导数据，
不能归因“USB读不到盘”。成功读记录中的errno1020/22为保留值，不能将errno独立
当作失败码；原调用是否失败以返回值为准。下一检查在VBR/MBR识别、容量/类型策略
和挂载状态判据，不改返回值或强行宣布FAT已挂载。

只读调查已交付：原`pdm_mbr_check_master_boot_record@5b114`支持有效VBR无MBR表，
`pdm_part_get_permission@5ba58`有分区0整盘回退。当前已核BPB/FSInfo/备份字段符合
所查静态校验，尚无证据支持“256GB强制exFAT”或“少59扇区必拒”作为根因。
`80000000`可由Attach多阶段或PrFILE缓存/配置等路径收敛；`Fsys_Init=0`也不证明
内部全部初始化成功。下一测`b9ccc8673`仅透传观察原导出
`fsysDepLog_PrFILE2_PDM@4c668`，记录stage/error/detail；stage0/1/2/3分别指磁盘打开、
分区打开、permission、分区信息。observer原参数/返回/errno有独立ASan/UBSan自检，
不改磁盘布局或mount flags，不能根据静态候选提前报告根因。

`b9ccc8673` / `host-sd-helper-gf7j2m5j`仍Mount失败，正常退出，PDM observer无记录。
main进一步核`PrFILE_Attach`失败分支`3dd74→PLT22ab0→GOT b5ea8`，确指
`fsysDepLog_PrFILE2_PDM`；因此无记录本身不能算“Attach全部成功”或“必是符号绕过”。
下一测`b63a4b2e9`转为保留原`fsysDepTrace_Printf`的文本及六个原始参数，
使用AArch64尾跳透传：保存恢复x0..x8/LR、q0..q7、NZCV与原stack位置，不重新调用
一个改变参数的printf替代原日志；C观察只读最多192B格式字符串，errno恢复。
这些日志只用来找原始错误，不改变mount策略或原介质布局。

`b63a4b2e9` / `host-sd-helper-17n2yrm8`终于取得原trace，阶段界限已明确：

1. 原MCmn报告totalSector`1dcd6500`（500000000）、pageSize`200`。
2. `PrFILE_Attach`选择Partition0，原返回0；此前没有PDM错误记录与Attach成功相容，
   不能再把本run写作分区识别失败。
3. 原`PrFILE_Mount`调用磁盘插入通知，并请求`600000`（6MiB）buffer，实际heap分配成功。
4. 原`pf_mount`对drive A开始，重复读取LBA0后，`pf_mount. errnum = %d`的原参数为2。
5. 原PrFILE Mount返回`80000000`，Detach返回0；VM正常退出。

因此当前焦点在pf_mount内部而不是Attach或内存分配。原完整trace的格式字符串和raw
参数保留在`original-fsys.txt.failed-partial`。尚未取得该轮原`pf2_inerrnum`返回数值，
不能擅自把error2命名为某种具体错误；正用窄窗口原反编译解释测得路径。

`b220f810f` / `host-sd-helper-zmkva7u1`进一步透传记录原本就会执行的错误查询，
取得`pf2_errnum=2`、`pf2_inerrnum=1`，Attach依然0，最终Mount`80000000`，正常退出。
没有额外查询或清除原错误状态；原getter参数/返回/errno透传有独立测试。
该组运行前12项host测试通过，但整体guest实验仍失败，不能改写成挂载通过。
原窄反编译链`83414→81794→81178→80e70→PFDRV_mount@57d48`已定位，
后者的原始分支仍在解释中，不提前把内部1命名为某错误类别。

`bb6539538` / `host-sd-helper-7bvhg4jd`保持同一错误组合、正常退出，未记录非零
PDM转换。缺记录不是可认定PDM全成功的证据，需确认覆盖。后续`bcf73e03c`
改为也记录前24条零转换，并在原`PFDRV_mount`和`PFCACHE_AllocateDataPage`原调用
返回边界透传记录。每次仍只调用一次原函数，不读写volume/cache输出对象，
参数/64位sector/结果/errno有ASan/UBSan自检；只为区分卷驱动与cache分配阶段，
不修改原错误或状态，也未让格式化任务通过。

`bcf73e03c` / `host-sd-helper-ledq4o4e`已完成（14项host测试通过，整体Mount仍失败，
VM正常退出），原阶段记录如下：

| 原返回边界 | 实测结果 |
|---|---|
| `PFCACHE_AllocateDataPage` caller`572f4` | 0 |
| PDM转换 caller`57324` | PDM0→PF0，证明观察确命中 |
| `PFCACHE_AllocateDataPage` caller`57da0` | 0 |
| PDM转换 caller`57ff8/58514` | 全0 |
| `PFDRV_mount` caller`80f54` | 0 |
| PDM转换 caller`80f70`（callback）、`810ac`（cleanup） | 全0 |
| 原错误查询 | 仍外层2/内部1 |

所以本run的卷驱动挂载、页分配与已观测PDM调用均成功，不能继续标作这些步骤失败。
已进入下一步`PFCACHE_InitCaches@5ea40`的原路径核对，缓存初始化返回尚未运行测量。
cache阶段observer透传自检14项通过；尚未让相机格式化/读写测试通过。

`b06679faa` / `host-sd-helper-ip5866gv`已直接测得
`PFCACHE_InitCaches caller=80f94 result=1`，其前PFDRV_mount=0、callback的PDM转换=0，
最终仍外层2/内部1，正常退出。故该run首个已测非零阶段为缓存初始化。
原函数`5ea40`先建cache pool，再调用`PFDRV_get_padding_buffer@5860c`；后者经
`pdm_part_get_padding_buffer@5cd24 → pdm_disk_get_padding_buffer@5a428`，原控制号
`40048007`、16B输出，读取ptr/size。MediaCommon已有原`mcmn_buf_getforpadding@191d0`
及`mcmn_buf_init@18efc`，优先核对正常原初始化，不编造padding成功或跳过cache。
padding具体返回和allocator配置尚待闭合，未提前认定这一子步骤就是已证根因。

原allocator初始化反编译已齐：`mcmn_buf_init`读取ALLLANG Backup的`fa002a/fa005f`
主区地址/长度和`fa021b/fa021c`次区地址/长度，以原`mcmn_mmap_do_mmap`映射，
选择原128KiB或2MiB padding空间。此前helper-only模块列表没有加载/播种Backup；
该差异必须先消除，不能把精简诊断的缺初始化误判成256GB/FAT32不支持。
`b80e6c7bb`复用正常启动原Backup/stream初始化（ALLLANG摘要核验，Backup_save=0），
只增加这一依赖组，旁观原`mcmn_buf_getforpadding`返回、ptr、size及cache原返回。
没有改四个Backup布局值、padding返回、ready或挂载策略；实际能否修复仍待该run证据。

### 原Backup依赖恢复有效，但严格fsck仍失败

`b80e6c7bb` / `host-sd-helper-f7p7202d`实证：原ALLLANG Backup/stream初始化后，
`mcmn_buf_getforpadding=0`给真实2MiB映射，cache init=0、Mount=0、GetFreeSpace=0；
空闲255937380352B。原Mkdir/Open/Write4096/Flush/Close/Read/FlushVolume/Unmount全部0，
选定块设备真实fsync多次成功。VM正常退出。

宿主独立7z提取`QTEST/PROBE.BIN`的4096B与预期逐字节相同，SHA
`c5d2097fa1cd94e31b5aeb3e30ddad3b49194826436c11fdf91f27090e8f9e9a`。
但原任务整体失败：`fsck.fat -n`返回1，唯一报告是FSInfo空闲簇hint仍7810589，
而FAT实际7810587（新目录和测试文件占两个cluster），明确Leaving filesystem unchanged。
没有宿主修复。此处可以接受“原Fsys文件字节已落宿主”，**不能接受整个文件系统验收通过**。

旧runner在post-validation check=True时未将fsck stdout写报告便抛错，已修为先保存
fsck结果、继续独立文件读回，最终ok仍严格取fsck==0；旧失败输出不改，另存
`recovery-post-validation.json`记录分层结果。后续查原FSInfo写入策略/正常关机与原
formatter初值，不用host fsck repair或validator放宽把失败变通过。

### 宿主卡接入中文界面（实现中，尚未运行验收）

自然启动新增显式`A7C2_HOST_SD=256gb`，与RAM稀疏卡/种子卡/成像组合/hotplug隔离。
控制器持有原host card lease并重复fd到40以上，贯穿shell/Python/bwrap继承；不把
宿主目录暴露给guest，只bind已固定的256GB单文件fd。原USB/SCSI识别后的`/dev/sda`
bind到原dummy后端使用的`/image_mmca`，仅加载前述限定callsite的容量/fsync适配器。
原ALLLANG Backup初始化沿用自然启动，不编辑四个内存布局值。

保存边界复用原Fsys flush/owner STOP/CONT生命周期，随后只读内容检查之前先做
真实guest block fsync，再host pinned-fd fsync；不经过guest RAM导出256GB。
`host_sd_snapshot.py`分块散列已分配extent，并显式说明sparse manifest摘要**不是**
256GB逻辑内容全量SHA256。当前此诊断snapshot最多读4GiB数据/65536个extent，超过
会明确拒绝而非截断；它不是磁盘容量或guest可写容量的缩减。host fsck只读fd、`-n`，
失败保持ok=false；不修复、不冒充JPEG/录像验收。尚未支持机内格式化可能产生的
分区或exFAT检查，届时须按实际布局扩展严格检查。

host-backed VM清理特设只发TERM/正常finally/QMP quit，不在timeout后SIGKILL；若
进程组仍存活则保留lease和错误。`host-sd-probe sync`仅容量校验+fsync，无pwrite；
原transport写测试改为必须显式`raw-test`，不再允许无参数误触。新增ASan/UBSan
控制流和host快照拒绝路径测试；最终测试结果和UI实跑待后续记录。

独立生命周期评审`476785bb`（已交付）发现P1：无instance的默认控制器在旧leader
已退出但子进程仍持卡时，start未检查retained host context，重启获取lock失败后会
在无新process的finally释放旧context。已在start重置任何状态之前拒绝残留context/
cleanup_error，并让status.can_start同步反映；不得通过新启动清理旧租约。
新增`test_host_sd_lifecycle.py`四项通过：退出leader/存活group场景的状态和真实flock
保持、重复租约拒绝、group未退出拒绝释放、确认退出才释放fd，以及timeout只TERM
绝不KILL。这是受控进程状态桩+真实文件锁测试，不冒充真实VM退出实验。

首轮UI组`ba81d3cfb`在收集阶段因旧菜单测试参数名request被pytest保留而失败，
仅将参数改为payload，原负面用例不删，完整组已原样重跑。不得把收集错误计为pass。

重跑`beeb7b9ed`：70 passed + 2 subtests，含host probe/snapshot/容量桥/lease/
profile/原控制器/稀疏卡/有序菜单请求；Python编译、shell语法、git diff --check、
`analysis/sync_repo_scripts.sh --check`均通过。此完整组不包含后来单独通过的4项
lease生命周期回归，不将不同组相加冒充单次覆盖。`bd0c261f1`在独占运行锁内
重新构建原ABI helper/adapter和ALLLANG initramfs并核嵌入摘要；构建不启动VM，
不触碰用户卡，完成后仍需中文UI实际接卡与原格式化结果。

`bd0c261f1`构建/嵌入摘要核验已通过。实际UI `bca55c3c5` / `run-8ohf5w3t`
启动了host256GBprofile，无YC/RC/SMP2；原USB ioctl报告500000000x512B、真实
block fsync0，原容量callsite报告256000000000B。空卡原PFDRV_mount返回7。
主会话打开实际`gtk-shooting-after-setup.png`和`gtk-menu-stable.png`后确认，它们
都被原中文“无法使用存储卡。格式化？”弹窗覆盖，默认选取消；不能据文件名或
CREATE_SCREEN/controller存在宣称本run实际HUD/menu已呈现。
另存`host-card-visual-review.json`明确该区别。现在沿原格式化提示逐页普通键操作，
不直接调API，不给空卡主机格式化；后续原format返回与host严格只读验收仍待证据。

### 原FSInfo策略调查已回收并核字节（不再作为运行中调查）

`48154656`结果已从其持久输出中回收（运行句柄已清理，不能继续称其运行中）。
主会话已核对同SHA原Fsys ELF的窄指令窗口：

- formatter `4af0c..4af20`确实把FSInfo空闲计数`+1e8..1eb`写FFFFFFFF，
  `4af24/4af30`写NextFree=2；`4af54`与`4af98`经原写回方法写主/副FSInfo。
- `PFFAT_RefreshFSINFO@6f658`读取volume+f644的bit2，清零则直接返回0；
  分配链`71eac..71ec8`还要求FAT32、同字段bit1置位才调用刷新。
- 调查指出原挂载`sub_81178`会清该低三位；`PFVOL_setupfsi@83668`是另一个
  独立策略入口。全局配置20000与挂载卷40000不等于这个策略字段。
- 普通cache flush/volume sync/unmount不保证生成本就被策略跳过的FSInfo写入。
  因此原真实fsync成功并不能使陈旧计数自行正确；完整关机是否另启策略仍未知。

这解释了为什么host mkfs给定精确初值的fixture写两簇后会留下旧hint；不改现有
输出为FFFFFFFF，不调用setupfsi改业务状态求pass，也不预言原UI对256GB会选FAT32。
若真正原格式化产生未知freecount，严格checker结果仍按实际保留，不降低标准。

本run手工step1 UP实际被AppFw队列n79/80接收，但`gtk-format-step-01-up.png`
全黑，之前已创建309/count0；step2普通MENU后仍黑。当前没有发送ENTER，也未
确认格式化。后续尝试一次真实GTK半按键唤醒（只半按，无全按），以新图核验，
不把“已排队/ACK”当成恢复。黑屏成因尚未证实，不能直接称自动关机。

半按新图`gtk-wake-half.png`仍黑。窄调查`db787a11`已交付，未确定309语义，仅给
两处候选（不是仍在运行）；主会话读完整邻域后确认`analysis/appfw-decompile/
corpus/parts/14/0x001b20000.c`中真实ELF`1b23e58`函数含原字符串
`[Master][Shutdown] factor:%08x type:%08x next_reboot:%08x`，在原事件100003c
分支按factor选择309等目标。该旧反编译FUN名比ELF addr高100000，按header addr
归一，不能把FUN名字直接当实际地址。本run是否由该路径、哪种factor进入仍需原日志。

只读安全检查`readonly-card-state.json`的两次真实媒体状态均unmounted、async/io/
busy/cancel0，host256GB仍allocated0、SEEK_DATA=ENXIO、mtime/ctime不变。
原严格脚本因previous_flush非零而保持shutdown_authorized=false；独立核对原console
发现该序号1286641781792781对应drive0/rc=-1021的失败flush，属于已处理请求标记，
不是写盘或pending。原false文件保留；另`pristine-shutdown-assessment.json`核相同
序号原返回且无inflight/pending后，仅授权正常QMP退出，不授权强杀，不声称导出/
格式化成功。进一步QMP只读blockstats和原ulog环取证在正常退出前进行。

直接第二QMP连接取证`b0ce79a74`在握手readline超时，未发任何QMP命令；原runner
持有其既有连接，不能凭该错误认定guest崩溃。失败保留，改经已核验串口只读
`/dev/mem`原ulog DRAM窗口、grep关机原文；不抢原QMP连接，不读GIC/MMIO。

还修正host退出的另一层风险：即使不显式KILL，未验证保存时父Python退出也会
触发bwrap die-with-parent。`host_sd_guard.py`在无成功保存边界时保留父进程并
阻塞wait VM真实退出，不轮询、不发quit/TERM；控制器异常/清理重试也拒绝TERM
未保存的活owner。新组`ba7d9c048`：79 passed + 2 subtests，Python编译、diff、
旧成果脚本同步通过；覆盖retained owner保护、lease、只读snapshot和控制器。
这不是本run已经正常关闭的证据，正常退出必须另存实际结果。

串口原日志已取得（`black-screen-shutdown-serial.txt`）：
`[Master][Shutdown] factor:00000011 type:00000002 next_reboot:00000002`。
主会话直接解析同SHA原appFw ELF：原UPM映射表`57fce58`，第17行ELF`57fcf68`
四字为`11,8,4c9dd0d,0`，字符串`4c9dd0d`确为`OFF_BY_APO1`；相邻行为
OFF_BY_KEY/LANC/UPDATE/APO2/CEC_STB/MEDIA_THERMAL。现在可以称本run为原APO1
自动关机导致黑屏，不再仅凭309猜测；不能由此宣称已有正常唤醒或APO键活动链。

`b85aa2529`重新读取未挂载/无IO/无pending和host全洞后，尝试通知原runner SIGINT
使其用已持有QMP连接走正常finally，需以实际退出/lease释放报告为准，不强杀。

下一次原格式化UI增设显式`--format-prompt-reviewed`，仅在新拍的640x480 RGB像素
SHA与主会话已目视核验的原中文取消弹窗完全相同时，立即一次普通UP并截图；确认
页外字节不变且上方“确定”原按钮橙色选中/下方取消黑色后才一次ENTER。黑屏、旧
取消状态、不同页面/几何均拒绝，不直接调内部API。这是按实际页面判定操作，
不是盲固定按键次数；目的是不让人工回合延迟先触发APO，不禁APO或改Backup。
第二页仍需真实截图/原format返回/独立文件系统结果，不宣称送ENTER即已格式化。

### 本地空盘准备已通过（不是guest接入）

`bff38a876`：`test_host_sd.py`四项通过。新建`runtime/analysis/host-sd/card.img`
逻辑256000000000B、初始实际分配0B，准备收据`prepared.json`明确
`guest_attached=false`、`formatted_by_camera=false`，未宣称完整内容摘要已核。
`host_sd.card_lease()`使用O_NOFOLLOW/O_EXCL、普通文件/单硬链接/固定容量/inode校验，
独占锁持有期间拒绝第二使用者，原有错误尺寸文件拒绝且不截断修复；测试包含跨4GiB
及末字节宿主持久读写。真正VM启动必须重新获取并持续持有租约，准备命令的锁已释放。
运行目录排除公开仓库，不把256GB镜像或本机inode/路径收据提交为源码。

暂停路线的`bd79beac0`实际guest已创建10GiB零分配tmpfs文件且空map通过；之后
BusyBox dd不支持`conv=notrunc`使大偏移测试失败，未启动相机、未格式化。
常规SIGINT没使runner退出；首次QMP因UNIX绝对路径过长未发命令，后续
`b852d153f`以原运行目录下短相对socket正常QMP quit成功，无残留owned进程。
原失败proof保持失败；此收尾不构成256GB方案的验证结果。
