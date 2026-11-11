# CP GPIO18：显式功能输出 latch

此目录提供 `virtual-gpio18-loader-state-v1` 的小型寄存器核心和 QEMU adapter，供**独立 CP 启动研究**使用，默认关闭。普通产品窗口与默认 QEMU 不受影响。

模型按同 SoC Sony OSS 的 `regs-gpio.h` 实现四组 32 位 DATA/SET/CLR：DIR、INEN、PORTSEL、WDATA。虚拟 reset 定义为 0，再应用原 BK4 record ed000 的 `f9014a` 六条寄存器脚本，得到 DIR=f、INEN=f、PORTSEL=e、WDATA=2。原脚本只确定写入位；完整复位字和未写位是本功能模型约定，**物理兼容性未验证，也不证明原 NOR 已执行**。

WDATA 由原 CP 的写入保持；未实现的 RDATA、IRQ、pull、保留地址、未对齐和错误尺寸访问拒绝，不返回伪输入、link/ready 或 UIPC ACK。

## 测试

在产品根目录运行，测试材料写本项目目录：

```sh
mkdir -p runtime/tmp/cp-gpio18
TMPDIR="$PWD/runtime/tmp/cp-gpio18" python3 -B -m pytest -q -p no:cacheprovider \
  --basetemp "$PWD/runtime/tmp/cp-gpio18/pytest" \
  source/cp-boot/test_gpio18.py source/cp-boot/test_stage.py
```

C 核心测试严格编译并启用 ASan/UBSan；不依赖原固件或私有镜像。

## 私有 CP 板接线

`stage.py` 只接受内置两个完整 SHA 的既有私有 CP 诊断板源码，不能直接当成 vanilla QEMU 的完整板移植。它保存原两文件到 `cp-gpio18-before/`，追加三份小源码，写 `cp-gpio18-stage.json`；重复调用必须全部摘要相同，未知基准或漂移拒绝。

```sh
python3 source/cp-boot/stage.py /path/to/private-cp-qemu-source
ninja -C /path/to/private-cp-qemu-source/build-cp -j2 qemu-system-aarch64
```

仅当环境变量 `QEMU_CP_GPIO18_PROFILE=virtual-gpio18-loader-state-v1` 时接入 `0xf102f000` 的 0x100B 窗口；未知 profile 直接拒绝，未设置时不创建设备。

实际验收、原始 CP 身份、输入来源与剩余阻塞见[CP 启动专题](../../report/2026-11-11-cp-boot-progress/README.md)。不能把核心单测或一次GPIO写入提升为原接收任务、AP↔CP、固件更新或成片通过。

源码按 GPL-2.0-or-later 授权。
