# 10GiB稀疏虚拟卡：原格式化待验

> **路线已暂停**：用户随后要求SD不放guest内存，改为本地磁盘目录支撑的固定256GB卡。
> 下文保留10GiB tmpfs实验及回归证据，不再将其作为目标存储交付。
> 新目标是宿主实验目录内256,000,000,000B稀疏虚拟磁盘文件，由QEMU虚拟USB存储连接，
> 不是普通目录文件API冒充SD，也不直通物理盘。新后端尚未接通，原格式化待验证。

## 目标与边界

用户要求10GB卡和原机内格式化；本实验采用明确的10GiB逻辑尺寸
（10,737,418,240B，20,971,520个512B扇区）。只运行本机隔离guest，不接物理盘/真实SD。
旧128MiB控制卡与既有成功/失败运行不替换。1GiB候选已被新要求取代，不启动其对照。

原文件后端`libInfraMediaCommon.so`使用64位stat大小和preadv64/pwritev64偏移。
相比新增块设备驱动/容量桥接，先保留这条原通道，以tmpfs稀疏**普通文件**提供容量，
而不是将10GiB种子塞进initramfs再cp两遍。初始不写MBR、BPB或FAT；它们应由原
Fsys formatter经原中文菜单生成。原formatter有FAT32分支，但菜单能否进入、设备能力
是否满足、实际格式化完成仍需运行验收，不改SUPPORT_FORMAT或伪造完成。

## 实施

- 默认关闭：`A7C2_SD_SPARSE=10g-empty`；仅在原RM文件后端/observer/raw-initramfs下允许，
  与已有seed/hotplug互斥。原≤2GiB输入校验及默认BPB检查保持原样。
- 新helper `sd-sparse.c`只接受`create/map`，路径固定，不接受用户路径或物理设备。
  专用tmpfs限512MiB实际分配，O_EXCL创建10GiB逻辑文件，验证初始st_blocks=0；
  再bind到`/image_mmca`。创建或挂载失败没有ready标记，禁止启动im。
- RM该显式profile只验固定普通文件inode/长度/可读性，允许未格式化或分区式内容；
  不再把“有介质”错误绑定到“已有合法FAT”。容量字段改为64位。
  启动摘要明确标为边界采样，不宣称完整文件摘要。
- 原flush/owner STOP/恢复屏障不变；屏障内用SEEK_DATA/SEEK_HOLE枚举数据，最多512MiB、
  4096个记录，每窗口≤4MiB。宿主严格核序、边界、inode/时间身份与前后相同map；
  EINVAL/不支持洞区、变化、超限全部拒绝，不用“猜是零”代替读回。
- 宿主候选先ftruncate逻辑尺寸，仅按核验窗口pwrite；洞只来自guest内核证明。
  保留窗口FNV/QMP读回、全逻辑字节SHA256、fsync、只读fsck及原子发布。
  当前空间预检仍保守要求约20GiB空闲，即使实际稀疏分配远小于此。

## 尚未通过的项目

1. 当前guest内核的tmpfs洞区行为及10GiB跨2/4GiB、末扇区读写。
2. 原中文菜单能否对未格式化介质调用原formatter，以及实际返回/目录重建。
3. 如果原格式化生成MBR分区式布局，当前整盘`fsck.fat -n`会拒绝而不发布；
   必须补齐分区范围的独立检查，不能把整盘失败改成通过。
4. 同run核验容量/可拍张数/实际JPEG和录像。扩大逻辑卡不证明任何拍摄链已通过。

**这是低内存、可导出到宿主的逻辑卡，不是10GiB实际可写RAM承诺。**
实际数据最多512MiB；超出会真实ENOSPC，不能冒充完整10GiB持久块设备。
若后续录像/长时间拍摄需要写满逻辑容量，再升级为文件支撑块设备；该升级仍需64位
块容量查询、原flush和持久化验证，不能把块节点st_size=0强行当卡容量。

## 验证纪律

host ASan/UBSan、真实稀疏文件大偏移和FAT32传输测试只验证工具，不算guest格式化。
最终需记录实际菜单截图、原请求/返回、格式化前后分配/MemAvailable、原重新挂载，
宿主只读检查与完整逻辑摘要；未齐之前状态保持“原格式化待验”。

### 已取得的host证据

- `b69b55ff0`：实际10GiB稀疏文件跨2/4GiB和末字节读写/范围覆盖自检通过，
  helper临时链接原glibc2.25成功，未据此声称guest通过。
- `b3ca2753c`：71pass+27subtests，RM因st_size/uint64有符号比较Werror失败；保留失败，
  随后改为先拒负值再显式uint64转换，没有移除Werror。
- `b5e1783ea`：81pass+50subtests，包括真实10GiB FAT32稀疏导出、全逻辑SHA比对、
  默认RM拒绝大镜像与显式10gprofile接受空白、错误map与原flush恢复回归；脚本同步通过。
- host tmpfs额外实测10GiB逻辑文件写三个大偏移只分配12KiB；guest tmpfs内核行为未验。
- 当前helper构建7288B，原libc ABI交叉链接通过；尚无原菜单格式化返回或新卡HUD证据。
