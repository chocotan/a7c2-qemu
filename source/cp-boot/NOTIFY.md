# AP↔CP GPIO 通知线功能模型

`virtual-ap-cp-gpio-lines-v1` 是显式、默认关闭的功能 profile。它接入两侧GPIO17/18的完整0x1000B窗口，保存32位DATA/SET/CLR，并把一侧GPIO18的输出状态发送给另一侧的输入寄存器。未连接、输出未驱动、输入未使能或协议错误时拒绝RDATA；不返回常量ready，不生成PCIe完成或UIPC回复。

目前AP侧在独立 `virt` 板上接入两个GIC输出；CP侧仅接寄存器和线状态，**CP IRQ尚未接线**。本功能不进入默认产品窗口，不改变原GPIO18单端切片。

## 线路与来源

| 通道 | 功能连接 | 依据/限定 |
| --- | --- | --- |
| 0，AP→CP | AP18/9 → CP17/2 | 原AP/CP的软件通道及轮询端；跨芯片配对为本profile定义，未测Sony物理布线 |
| 0，CP→AP | CP18/3 → AP17/4 | 同上；原AP IRQ92对应GPIO17/4 |
| 1，CP→AP | CP18/2 → AP17/3 | 原AP IRQ91对应GPIO17/3 |
| 1，AP→CP | AP18/8输出可传输 | CP16/2尚未建模，访问仍拒绝；不计为完整通道通过 |

初始寄存器采用已声明虚拟reset0，再应用已核BK4 REG数据：CP18沿用旧六写；CP17、AP17和AP18分别采用对应候选记录的七、八、七写。完整初值是功能定义，不证明物理reset字、原NOR执行或真实记录选择。未连接的其它输入位在本功能profile中定义为0；有接线的输入必须收到对端有效快照。

AP的物理地址由原内核通道表和同版本公开头共同核对；原Image的 `gpiopin_to_irq` 原字节确认GPIO17 bit≤23映射IRQ88+bit，原UDIF将IRQ92/91映射GIC SPI60/59。这里不把AP规则套给CP。

纯状态机复用 `gpio18.c/h`。本端reset重建本端寄存器，保留仍连接的对端线路；源端仅在DIR=输出、PORTSEL=GPIO时声明该通道驱动。RDATA18、未知寄存器、非法端口、错误尺寸和未对齐访问拒绝。

## 传输

每个实例仅使用专属本机Unix socket字符设备 `notify-peer`。固定16字节小端帧为 `magic/seq/known/levels` 四个u32；magic分别为APG1/CPG1，必须收到相反角色，seq从0严格递增，不允许回绕。known/levels仅有两个通道位，未知驱动位不能携带电平。

接收器保存不完整帧；整帧通过才更新线状态。坏角色、坏序号、非法掩码、未驱动电平或短发送使接收输入失效；重连重新握手。硬件reset不重置连接上的帧序号。AP IRQ只由有效对端电平驱动并受本端方向/输入使能约束，断连时撤销；没有额外ACK。

不支持VMState/双端RAM恢复。本profile须先建立双端设备和传输的恢复合同，才能纳入产品RAM快照。

## 构建和检查

`stage-notify.py` 只接受旧GPIO18 stage已固定身份的私有CP诊断源码及固定 `virt.c`，保存三个板级原文件到 `cp-notify-before/`。它不是对任意vanilla QEMU的完整CP板移植。

```sh
python3 source/cp-boot/stage-notify.py /path/to/pinned-cp-qemu
ninja -C /path/to/pinned-cp-qemu/build-cp -j2 qemu-system-aarch64
```

运行还要求 `cp-notify-build.json` 将binary摘要、stage摘要和profile绑定；`check-notify-qemu.py` 逐文件检查stage输出及继承源。显式环境为 `QEMU_AP_CP_GPIO_LINES=virtual-ap-cp-gpio-lines-v1`、`QEMU_AP_CP_GPIO_SIDE=ap|cp`，并提供 `-chardev socket,id=notify-peer,...`。与旧 `QEMU_CP_GPIO18_PROFILE` 互斥。`none` 支持独立两侧寄存器，`virt` 只允许AP侧并连接GIC。

```sh
mkdir -p runtime/tmp/notify
TMPDIR="$PWD/runtime/tmp/notify" python3 -B -m pytest -q -p no:cacheprovider \
  --basetemp "$PWD/runtime/tmp/notify/pytest" \
  source/cp-boot/test_notify.py source/cp-boot/test_notify_stage.py
python3 source/cp-boot/check-notify-qemu.py \
  --binary /path/to/pinned-cp-qemu/build-cp/qemu-system-aarch64 \
  --out "$PWD/runtime/tmp/notify/new-case"
```

实际qtest验证双端SET/CLR、AP实际GIC92/91 pending、本端reset保留对端输入、断连拒绝及分片/角色/序号/掩码负例。qtest本身会丢弃MemTxResult，因此拒绝结论同时核设备错误日志，不能把qtest返回0当作有效输入。

实际原CP调查使用显式 `--notify-functional-peer`：对端为另一个QEMU寄存器模型，**没有原AP软件**。原CP完整镜像和启动参数保持不变；消费结果按原CP实际读写另记，不能提升为原AP↔原CP、PCIe更新、完整启动或成片通过。最终收据见[CP专题](../../report/2026-11-11-cp-boot-progress/README.md)。
