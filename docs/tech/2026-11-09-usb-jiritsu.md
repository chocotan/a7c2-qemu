# 原 Sony USB 设备端与本机 jiritsu 枚举

本轮目标是本机宿主实际枚举虚拟相机、完成真实 jiritsu 认证并经同一 USB 传输读回 guest 权限。所有运行仅在独立普通虚拟盘与隔离 QEMU 中；不接真机或真实 SD，不使用另一台虚拟电脑或预造 Sony 描述符。当前实际结果见后续记录；驱动注册、VBUS、描述符、宿主枚举、认证和 root 必须分别验收。

## 产品接线

此前产品的 USB/IP、端口归属和 jiritsu 消费者已有守卫，但默认 QEMU 只有 xHCI 网络设备，没有相机设备端 DWC3。现在以独立 `--sony-device --stage-only` 构建候选，包含实际 TRB/DMA／事件环的 DWC3 core、每运行 Unix endpoint bridge，以及有限 clock/reset/PHY/GPIO/VBUS 状态。默认已验 QEMU 二进制不被覆盖。

产品直接维护 `source/usb-device/` 的必要 core/bridge/platform 源与 `sony_usb_board.py` 的原 DT 资源。没有引入研究 launch、私有设置、完整研究快照或系统 dump。候选运行要求显式完成构建收据；源成员、生成源、二进制和持久盘构建摘要必须一致。endpoint 的 run/lease/专属 QMP 绑定只由本轮创建，实际 QMP peer 身份确认后才以0600发布私有 `usb-context.json`。

bridge 不含 Sony VID/PID、描述符或认证回复。它只能把原 guest 对实际 SETUP/DATA/STATUS TRB 的完成字节交给现有 USB/IP 服务。无 gadget 绑定或端点未准备时保持失败，不导出空设备。

宿主使用真实 Linux `vhci_hcd`／`usbip_core`。本轮先记录模块与虚拟 sysfs 属性原状态，再仅临时授权当前用户操作 `/sys/devices/platform/vhci_hcd.N/{attach,detach}`；不授权物理 USB 控制器。收尾必须核对自有端口实际释放，再恢复原权限，外来端口不动。jiritsu 消费者仍按真实 libusb 返回值、同运行／lease／controller／port、guest 描述符和代次核对每次打开与传输。

## 原用户态两条路径

普通相机模式保留原 AP 和原 USB 库。显式 USB 候选才允许按原 SHA 校验并装载原 `usb_portMonitor.ko` 和 `usbg_sen.ko`；其它未审模块继续拒绝。被动小观察器仅核原 ELF、入口机器码和 GOT，透传原调用及 errno，记录真实 openSvc／START／MSC入口，没有 native publication、空 ACK 或手动完成业务。

另一个显式测试模式复用原 `/sbin/init2::setup_senser`：原脚本在 `/setting/sen/smode` 为 `UU` 时启动原 `sen.elf`，随后仍启动 bootin。设置写入前保存原值或不存在状态并比较；运行结束在 USB 释放后恢复。每轮前像独立保存在虚拟内部 `/log/qemu`，异常时不宣称已恢复。sen 原 ELF 用完整摘要绑定，被动 wrapper 只增加日志，不替换 Senser 业务。

认证现在只要求原 PMCA 纯 Python 依赖，不再以无关研究写入脚本阻塞 `authenticate`。PMCA 版本为 `3824c398c0fad97da1c4d4cc219a9646f9c4583f`，本机依赖副本放受忽略的 `runtime/analysis/vendor/pmca-adamwuqwq/`；51份源码与原依赖逐字相同。版本读取／root部署仍分别保留原数据与恢复前置，不因认证依赖缩小而放宽。

## 实际失败与修复

| 运行 | 实际观察 | 保留结论 |
|---|---|---|
| v1 `run-0wnfc5ki` | 原 Sony DWC3 probe、原 monitor/Sen模块均rc0；原 `/proc/udm/fusb` VBUS读出0→1，内部latch仍`not started`；UDC `not attached`，无function | 原LCD未进入USB选择；无descriptor、host import、枚举或认证。正常设置／SD保存、19卷冻结、QMP0／无VM信号 |
| v2 `run-q9v3xr29` | 被动观察器核原USB库和AP入口后安装成功；未看到原openSvc／START／MSC业务调用 | 不能套用旧研究的20a3／BE／TCIN当前等待。描述符仍未ready；正常保存退出。负证据只覆盖已安装的原入口 |
| v3 `run-x76mmtwd` | 原init2确实按UU启动原sen；原USB PHY切换出现`__queue_work`警告，随后`u2phy_adjust`读取`0xf1080000`被有限模型拒绝，原内核进入异常监视器 | 无host import／认证。断开本轮虚拟线后保全12个实际RAM段及原盘，单次正常QMP退出，无VM信号；原UU设置未在guest恢复，失败盘原样留证 |

v3 RAM ELF为25,769,317,539 B，SHA256 `548af9026be1c09caf894d426113f0e212ce393e964e573ad4466f2302d6a011`。保全首轮误要求不存在USB owner记录，实际已有VBUS ON记录但没有import；按实际字段复核后另立变体。第一次dump段核收断言拒绝，首轮差异的瞬时原因未唯一确定；没有重抓RAM，随后按12个FlatView范围、ELF段边界、QMP完成字节和文件大小／mtime稳定期间的完整哈希核收。原SD保存false、设置恢复false不回填。

原GPL源码将两个问题分开：`core.c` 的gadget-only能力声明使原OTG初始化退成peripheral分支，未初始化DRD工作项，而原退出代码仍调用`dwc3_set_mode`排队。新功能合同允许原DRD的peripheral切换，host角色依旧明确拒绝。`cxd-phy.c`／`crphy_defs.h` 则给出两个USB2配置寄存器、共同及四lane共40个有限CR调参地址；模型保存实际写入和读回，核宽度、取值范围及clock/reset/SRAM前置，未知地址继续拒绝。它不执行PHY固件，不把功能值称为物理ASIC格式或历史。

## 验证分账

初次两工作线程集中检查：产品54项通过；USB宿主组因长checkout的临时Unix socket路径触发16项夹具失败。使用短私有临时路径后，35项通过、8项缺外部脚本的检查跳过、10子测试通过。原长路径失败保留，运行协议没有放宽路径守卫。

原Senser模式与认证依赖检查20项通过；增加PHY/角色修复后21项通过，均另有8skip/10sub，不相加重复节点。DWC3严格C11 `-Wall -Wextra -Werror -pedantic` 与ASan/UBSan两配置各执行相同11组状态、DMA、IRQ、取消和代次场景。PHY新增同源寄存器前置、真实值读回、未知地址／宽度／时钟关闭拒绝检查。它们是host证据，不提升原枚举或认证。

v1候选完整构建SHA `47f53c2a1916af1936d6276b13032e97a0c2e08da42e015e686933f46f0c3c04`；PHY／角色修复后的独立候选SHA `4cc728498af24488d41c1984f1ab3e6a997833e3fc87ffbf68a47daaa275fd0c`。已验默认QEMU保持SHA `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad`。

## 宿主真实识别与标准地址前置

PHY／角色修复后的v4 `run-q4v_jxxt` 已实际经过原 Senser `CREATE`、原 `0x4018e203` START ioctl rc0。bridge通过原EP0取得device/config原字节后，本机Linux7.2.9的VHCI下真实出现 `054c:0336`、`Sony USB Device`，路径 `/sys/devices/platform/vhci_hcd.0/usb12/12-1`，devnum2。原SETUP/DATA/STATUS DMA是描述符来源，没有内置Sony描述符。

首次attach即时读回早于内核完成异步状态转换；后续真实sysfs识别与首错误分别保留。控制器现在只写一次attach，随后有界等实际speed/devid身份匹配。新UsbControl对象没有旧Popen对象时，原server已成为同PID/starttime的zombie：其TCP和URB已按精确退休回执释放，父进程未回收不是server仍运行。现在只接纳原代次终态，能回收自己的子进程就实际waitpid，不发VM信号。断开后归档旧import身份并清除当前attachment，重复disconnect/OFF不会再次拿已清的socket字段校验旧代次。原首错误、半收尾状态前像和外部精确退休核收记录均保留。

v4认证尚未开始，隔离`python -I`看不到本机Crypto；v5 `run-3r9oaw0q`枚举及断开保存已通过，但同隔离环境又发现PyUSB安装只在用户site。两个原依赖从本机现有安装准备到受忽略的host-python目录，实际`.py/.so`内容进入跨进程来源绑定。完整原认证库在相同`-I`模式已成功导入317个绑定文件，不接设备；缺依赖失败不改写成认证成功。

v6 `run-0jdjqd7q` 已稳定识别到同控制器devnum4并获得仅该自有虚拟节点的临时访问权限，但原认证未开始。宿主原dmesg明确 `can't set config #1, error -32`；用户态只取得`USBError: Entity not found`。因此这里只认证设备识别，不称已配置可认证设备。

根因合同来自现有GPL VHCI `vhci_urb_enqueue`：SET_ADDRESS在VHCI本地返回并`goto no_need_xmit`。本后端先reset原gadget，导致原DWC3处于DEFAULT；原`dwc3_ep0_set_config`在DEFAULT明确返回`-EINVAL`并STALL。现已在共享USB/IP import路径追加真实标准EP0 SET_ADDRESS，后端地址取自该虚拟远端的metadata.devnum，与宿主本地地址独立；必须实际consume原SETUP/STATUS并返回status0/actual0/无payload才能允许import。没有直接写guest状态或强制SET_CONFIGURATION；STALL、畸形数据及超时不记成功，原取消／退休守卫保持。

相关两线程回归44通过／8显式跳过／10子测试；PHY／DMA未变，不重复编译。v4经原精确退休证据收尾后真实恢复UU设置、SD／设置保存、19卷冻结及QMP0；v5/v6同样正常保存退出。原枚举流水的整体失败与后续正常收尾分别保存。

## v7 原配置通过与非ISO更新命令

`run-ngkbhthy` 的原EP0 SET_ADDRESS实际status0/actual0后，宿主真实sysfs读回 `bConfigurationValue=1`、`bNumInterfaces=1`，interface0为classff并宣告4个endpoint。这比v4-v6的未配置识别进一步，原配置STALL已被内容型证据解除。

认证进入真实数据通道后，原sen线程触发 `dwc3_send_gadget_ep_cmd` 写物理`0xf10cc84c`、值`0x50007`；核心原先在所有命令无CMDACT时拒绝，返回-22被MMIO callback传播成external abort。原GPL `gadget.c::dwc3_send_gadget_ep_cmd`明确：非ISO的UPDATETRANSFER是No Response命令，必须清CMDACT和CMDIOC。新核心只为已配置、非控制、非ISO且IOC为0的UPDATE允许此格式，随后仍核active与原resource5，不自动分配、完成或产生payload。其它无CMDACT命令和错误资源保持拒绝。

v7认证整体false，原GenericUsbException和Stop身份超时保留。原import在实际取消与端口detach后retired，preload从未部署，虚拟线已断开；异常监视器后不发Linux命令。RAM25,769,317,539B／SHA256 `e7a27085ea3f92d6815be1544d4c606d3624c1cdc79608327dd2cf3f655ad325`已与12个真实RAM范围匹配，随后正常QMP退出。原设置恢复／SD保存仍false，不能借前轮正常保存回填。

新命令正反边与未变11组DMA完整状态场景在strict和ASan/UBSan配置通过。原固件、GPL driver和默认产品QEMU未修改，第三个独立候选及fresh原认证验收另立结果。

## v8 七步认证成功与v9原Start对照

第三个独立候选已完整构建，SHA256为 `0f327c0811fed6b6c6cbb85e68a093b2322a3a376aee35adfd15de70173285bb`，默认QEMU与前两个候选均保留。v8 `run-9wyoq0mn` 的原 `0x50007` UPDATE_TRANSFER已实际rc0，真实PMCA／PyUSB经VHCI和原Senser返回七个交换：`1→8、3→4、1→8、3→4、1→8、3→4、5→6`，每次response.data为512B，最后成功字节为1。因此这轮 `authentication_verified=true` 有原内容型证据。

随后旧消费者额外执行HASP产品信息读取及Stop Senser。原 `gcore_setup` 在 `usbg_sen.ko+0x20` 解引用NULL，后继业务失败。当前证据不能唯一分辨HASP与Stop中哪一步导致该异常，不能写成已确定的端点模型拒绝；本轮没有MMIO拒绝。整轮仍FAIL，root／version未验。实际import已retired、虚拟线OFF，原RAM 25,769,317,539B／SHA256 `85f35bd452ab0484c3bff17696ae24da753d22ae23f79ad68fc50eea9465c5b7` 按12个实际RAM范围保全并完整读回，随后正常QMP退出，没有给VM发信号。原UU恢复／SD保存false保持。

认证入口现收窄到认证动作：已有0336服务依旧执行原PMCA Start Senser初始化及七步交换，关闭自己的libusb句柄后保留服务模式，由拥有连接的控制器正常detach／OFF并恢复UU设置；不再额外读取HASP或调用Stop Senser。其它version/root动作保留其原数据、模式与恢复前置。

v9 `run-k4rx383x` 是省略Start的否定对照：已枚举0336不等于已完成认证初始化，第一个包没有得到回复，无认证交换可记录。该FAIL和当时host夹具PASS分别保留，未改写。v9无内核异常，实际USB断开、UU恢复、设置／SD保存、19卷冻结、QMP0和盘租约释放均完成。修复后host回归要求Start确实一次、原七步完整、没有HASP／Stop且句柄释放，27通过／8显式跳过／10子测试；重复节点不累加。后续全新产品CLI综合验收另立结果。

## v10 产品CLI与完整正常收尾通过

最终新实例 `run-x8ejj3k4` 直接执行产品 `tools/jiritsu-authenticate.py --run <run>`，CLI rc0，`phase=complete`。独立宿主只读观察实际确认 `054c:0336`、configuration1、interface0 classff、四个Bulk端点 `02、04、81、83`；64B完整device/config描述符SHA256为 `ef1ffcc7e475ab63cdbd2e2722f7be6ac8fbe37c1ec48d15b194e83ee9a822c8`。原EP0 SET_ADDRESS仍为status0/actual0。

原Start初始化后，七步返回仍为 `8、4、8、4、8、4、6`，最后成功字节1。没有HASP请求、Stop Senser或root载荷。关闭本次libusb句柄后实际disconnect完成，原guest读回 `PRODUCT_USB_SENSER_ORIGINAL_MODE_RESTORED`，当次设置导出／SD保存／flush生命周期通过，19卷原freeze_bdev冻结完成，QMP rc0、owner／peer退出、租约释放。30份运行源码在全程无漂移。这轮单独PASS，不借用前轮认证或保存。

全部自有VHCI端口空闲后，按原inode823187／823186恢复attach/detach的root:root与0200权限，再卸载本轮装载的vhci_hcd／usbip_core，状态与开始前一致。没有物理USB操作或给VM发送信号；历史失败盘、RAM及日志全部保留。公开收据为 [usb-jiritsu-20261109.json](../../validation/usb-jiritsu-20261109.json)。

## v11–v18 version/root 失败与收窄

后续每轮失败均保留，不用v10认证成功回填：v11的私有助手误用小型owner JSON上限读取63,132B认证收据，未发post-auth请求；改用独立0600／O_NOFOLLOW／1MiB有界读取。v12的原`GET_FILE2`返回`0x10000004`，原`libJiritsu.so`反汇编证明其先挂载`/dev/nflasha6`到`/tmp/jiritsu`；显式服务模式现在只在目录缺失时创建真实空目录，并在USB释放、来源及vfat类型核实后恢复前像。v13 `run-xpr2pz_x` 由此读回19B版本`32014_05.2025101101`，但原终端第二组Bulk端点写入超时，root仍为false。

v14暴露了研究`usb_service_probe`路径劫持，未部署；version/root现只绑定产品本地四份协议文件与固定worker，不扫描研究目录。v15证明同一USB会话不能先authenticate再启动第二个root消费者；第二次认证失败并伴随原Sen异常，25,769,317,539B RAM已保全。v16去掉额外HASP前仍因该请求超时，现version/root直接读取版本。v17/v18的70,912B上传均在写后超时，恢复认证也失败；v17后来出现来源未唯一证明的launcher137，v18则因驱动只保留owner而未退出GTK，造成约半小时无进展等待。v18恢复后出现原异常，磁盘和日志保留，但完整RAM未抓到，这是明确证据缺口。

这些结果只证明旧路径失败，不证明通用大OUT或bounce TRB模型已经修复。新增的有界TRB诊断候选完整构建SHA为`2e1e562ae77c9930478acd8697cc3a0df5798425f2359b52a6a35af573ea12f3`，默认QEMU仍未替换。

## v19 小worker、Uid/Gid与中和实际通过

为避开70,912B上传边界，worker以同一审计C源码、原严格C11参数以及`-Wl,-z,max-page-size=4096 -Wl,--strip-all`重新构建为10,328B，独立SHA256为`063248441ad61ecf55c495f986831560e2383b8d3feb52da631d77571781d10c`；六项host行为测试通过。旧70,912B产物、摘要和失败记录保留，新产物不冒充旧文件，也不借host测试宣称guest成功。

全新实例`run-s3tz4z6p`直接执行产品`tools/jiritsu-authenticate.py --action root --run <run>`，同一消费者完成原Start、七步认证和19B版本读取。10,328B载荷经原`GET_FILE2`读回且SHA一致，单次DEBUG后worker实际执行；身份命令退出码0，实际输出为`Uid: 0 0 0 0`与`Gid: 0 0 0 0`四列全零。随后清理命令退出码0，删除本次上传文件并停止worker。

中和分两步均有内容证据：worker解除preload后读回512个换行；最终恢复通道再读回512个空格，SHA256 `e449eaf70850b3535de8c39146533eec81cab7ce154bdae59affa8b14963e1ae`，`preload_recovery_required=false`。随后USB断开、原smode恢复、设置与虚拟SD保存、flush恢复、19卷冻结、QMP rc0、owner/peer退出和租约释放全部通过；37份运行源码无漂移。公开收据已更新为`ORIGINAL_USB_HOST_CONFIGURED_AUTHENTICATION7_VERSION_ROOT_NEUTRAL_SAVE_EXIT_PASS`。

旧失败run的恢复锁存没有清除或跨轮回填。其VHCI端口已在各自VM退出后释放，第二轮attach/detach权限按inode839108／839107恢复root:root/0200，vhci_hcd／usbip_core恢复为开始前未加载。两个旧USB server仍因未证实的import/中和状态保持为无VM、无端口的休眠残留PID704033／973090；未用SIGKILL或伪造锁存清理它们。

## 产品复现入口

先按主README完成官方包导入和默认QEMU构建。认证的隔离子进程需要产品本地依赖，用户显式准备；launcher不下载或安装软件：

```bash
python3 -m pip install --target runtime/analysis/vendor/host-python 'pycryptodomex>=3.10' 'pyusb>=1.2,<2'
git clone https://github.com/adamwuqwq/Sony-PMCA-RE.git runtime/analysis/vendor/pmca-adamwuqwq
git -C runtime/analysis/vendor/pmca-adamwuqwq checkout 3824c398c0fad97da1c4d4cc219a9646f9c4583f
```

宿主还需发行版libusb与vhci_hcd，且当前用户获准访问本次虚拟controller的attach/detach及实际枚举后的虚拟USB节点；权限准备必须限定精确VHCI祖先与本轮端口。本轮权限只临时设置并已恢复，产品CLI不自动提权。产品新增USB候选保持独立：

```bash
./build-qemu.sh --stage-only --sony-device
```

输出的 `STAGED_QEMU_BINARY` 相邻构建根中包含 `usb-device-build.json`。该收据由真实构建生成，运行器会再次核对源码和binary，不接受用旧收据换pin。设备端仍为显式候选，启动示例：

```bash
A7C2_SONY_USB_DEVICE=virtual-functional-sony-usb-device-v1 \
A7C2_USB_DEVICE_BUILD=/absolute/product/source/build/qemu-XXXXXX/usb-device-build.json \
A7C2_USB_SENSER=original-init2-v1 \
./start.sh
```

只在持有专属虚拟内部盘、宿主虚拟VHCI端口可用时使用原服务模式。窗口“连接电脑”负责本轮真实VBUS、原描述符探测、host attach；正常OFF先释放USB、恢复原smode，再保存设置与SD。原设备被宿主识别且配置完成后，独立认证入口从私有context读取lease，无需把secret放进命令行：

```bash
python3 tools/jiritsu-authenticate.py --action authenticate \
  --run /absolute/product/runtime/analysis/menu-runs/run-XXXXXXXX
```

PMCA依赖为读者本地clone的 `runtime/analysis/vendor/pmca-adamwuqwq`，固定提交见上文；不将第三方仓库或生成Crypto/PyUSB副本放入本次公开源码。`python -I`子进程直接使用已准备的产品host-python依赖，并在执行前重新核对实际源码／扩展摘要。该认证入口不接受物理USB路径，不执行root载荷或写固件。`--action version`只读版本；`--action root`在同一消费者中继续执行上述已审worker与身份读取。不要在同一连接上串联两个消费者。root只用于本机虚拟相机，必须使用产品固定的10,328B载荷并满足中和读回；恢复未确认时CLI返回非零。worker源码、构建参数和摘要见`tools/jiritsu/README.md`。

## 2026-11-10 大 OUT 与持久文件周期

真实 VHCI/libusb 已消费 70,931B 线请求（70,912B 内容加 19B 命令头）。此前 bridge 返回 `-95` 的直接原因是 host URB `flags=0x40000`，即 Linux `URB_DMA_MAP_SG`。bridge 现在只剥离 `0x00ff0000` 这组 HCD DMA/setup 映射元数据；`SHORT_NOT_OK`、`ZERO_PACKET` 保留，ISO/未知高位仍拒绝，guest DWC3 校验未放宽。修复后实际结果为 `status=0 actual=70931`，guest 写后读回 70,912B，全文 SHA-256 为 `7b26726960a3dea5751a3805b392ad623bfdba26c606c6d3c94da1a74c0bcf47`。

同一完整实际周期还完成：93B 文件经同一 USB root worker 写入并读回；同盘新冷启动再次读回相同摘要；恢复 52B 原文件并读回；显式 UI 确认后只复位 nflasha2，事务保留原分区前像、验证其它盘字节不变，并再次确认恢复原固件文件。四次原 AP run 均正常 QMP quit、返回码 0、无 VM signal，每次停止均冻结 19 个内部卷。公开收据为 `validation/usb-large-out-file-cycle-20261110.json`。

此轮还定位并修复了持久 `/tmp` 的固定 `.part` 跨冷启动冲突：旧故障为 `open errno=17`。快照写入改用 PID 加原子 ticket 的唯一临时 inode，撞名只跳过，不删除旧证据；全文读回与原子 rename 保持。该修复已直接复用含旧 `.part` 的故障盘通过原 AP 启动。

## 剩余边界

原 host 枚举、配置1／4端点、七步认证、19B版本、worker Uid/Gid 四列全零、preload 中和、通用 70,912B OUT、持久文件与 p2 复位周期已通过。普通 AP 菜单 MSC 是另一条验收路线；本条 Senser 结果不提升普通菜单路由。bounce TRB 的其它边界、完整 BODYDATA 安装、拍摄写卡和物理 ASIC 兼容性仍未完成；`capture_verified=false`、`full_boot_verified=false`。旧 v5–v12 失败 run、外层诊断截断、`-95` 与 EEXIST 原始记录均保留，未回填为成功。
