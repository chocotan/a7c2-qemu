# Imola MCU固件：MIPS静态bank与实际结果发布

公开VCD固件包含可读的MIPS风格小端启动和运行代码。MIPS32默认工具不能解释部分字，MIPS64可将它们解码为LDL/SDL，但实际GPR位宽和语义仍未证明，见[独立ISA核查](../imola-ipsx-isa/README.md)。已定位MCU真实结果环复制/cache/sync及producer-index MMIO发布。尚未执行该固件，不能宣称MCU已仿真启动或已经产生编码字节。

本目录提供最小的原件认证、多bank静态地址读取和独占导出工具；没有新依赖、VM、网络、物理设备或private/full数据。原始10.9MB固件不随代码分发，使用公开ALLLANG提取的`runtime/analysis/menu-root/usr/codec/vcd_firmware_imola2.bin`。

## 原件和静态视图

原件长度a6d8cc=10934476，SHA-256为15e75a9732e2f9904ada1c919c631dac0da57e605ce3daa4c6fb2ebe98982b5b。`file`曾将其误识别为字体，架构判断以原CP0和启动指令为依据。

| 显式bank | raw半开区间 | 链接地址/交接 |
|---|---|---|
| rom0 | 0..8cc | 9fc00000/BFC别名，跳80009300 |
| ram0 | 9000..714000 | VA=80000000+raw，入口80009300 |
| ram1 | 714000..8bf000 | 同上，入口80714300 |
| ram2 | 8bf000..a6a000 | 同上，入口808bf300 |
| rom1 | a6a000..a6a8cc | 独立eSOL-eBinder-B启动块，跳80714300 |
| rom2 | a6d000..a6d8cc | 独立eSOL-eBinder-B启动块，跳808bf300 |

8cc..9000和a6a8cc..a6d000为文件零padding，不自动映射成运行态RAM。三份ROM共享相同虚拟别名，必须显式选择bank。外部loader实际copy/DMA长度仍未证明；这些是静态链接区间，不是guest内存快照。

ROM raw0为MIPS branch到40；40的实际指令是MFC0。启动建立gp=9fc088c8、sp=bfc018cc，用mask dfffffff从BFC切换到9FC别名。三份ROM的LUI/ADDIU/JALR在原字节中明确给出各RAM入口，RAM入口又有对应startup和内部绝对调用。CP0编号25的vendor语义未证，不将其武断命名为标准EBase。

## 复现与边界验证

```sh
python3 -m pytest -q report/imola-mcu-firmware-contract/test_image.py
mkdir -p runtime/analysis/scratch/imola-static
python3 report/imola-mcu-firmware-contract/image.py \
  runtime/analysis/menu-root/usr/codec/vcd_firmware_imola2.bin \
  ram0 runtime/analysis/scratch/imola-static/ram0.bin
kuna decompile-all runtime/analysis/scratch/imola-static/ram0.bin \
  --raw-image --target MIPS:LE:32:default --base 0x80009000 \
  --addr 0x8017dda8 --option rawdiscover off --max-fn-seconds 8 --no-vars
```

导出必须写一个不存在的新文件，不能覆盖原件或其他产物；导出后逐字节读回。`image.py`先核完整原件长度和SHA，再映射已列bank。未知bank、越界、零/负尺寸、未经证明的RAM别名均拒绝。`read_window`只接受来自`load_image`的不可变已认证bytes，输出为静态文件窗口，绝不读取真实物理地址。

**19项检查通过**：全部12 source pins/5448B、实际MIPS三处handoff、八通道MMIO表与最终SW、六bank起止和ROM别名/歧义、未知/越界拒绝、修改/截短原件拒绝、独占导出及读回。临时文件只在pytest目录，无固件执行。

Kuna的MIPS32分析target和`--option rawdiscover off`已验证可恢复部分局部函数；未知字仍可能截断该目标的控制流。MIPS64在canonical RAM1基址也成功恢复控制函数，解码接受本身不是CPU型号/语义或可运行性证明；伪代码仍需原指令/延迟槽核对。

## 真实MCU结果复制和发布

8017d608从结果包首字节选mailbox group c，控制对象C保存base C+34+c*14、capacity C+38+c*14、end C+3c+c*14、next-write C+40+c*14。原代码：

1. copy80字节结果到cur。
2. 对cur和cur+40执行cache1a，然后sync。
3. cur+=80，到末端则回绕base。
4. 仅当软件通知条件允许时，8017dda8计算最后已写槽index，保存u16[C+24+2*c]，并在**8017defc**向`bf044060+4*c`写`20000000|index`。

index=`(((cur==base ? capacity : cur-base)>>7)-1)&ffff`。通知受interrupt mode、结果类型mask和组状态合并；不能每copy一次就无条件拉IRQ。capacity与ARM H中的N及额外槽关系仍未闭合。

MCU表raw235cc4的八项stride18，第四u32为bf044060..bf04407c。对应[ARM读侧](../native-imola-output-source/README.md)f3804060..7c的同组偏移，ARM消费确认写f3804020+4*c的index|80000000。两侧硬件别名、global status4200位和IRQ41生成仍需证明或明确建模，不能仅由偏移相同就认定已经工作。

## 实际id2及P结果writer

8016a204构造id2结果，读取S+4/Pcpu和S+8/Qcpu，分别写D+10/D+18的zero_extend(convert(pointer)+u32[be000064])，发送内部3c4/80字节结果。8016a62c实际写P的六个segment word及18..4b metadata，对P的80字节cache并sync；某模式会清六个segment word，所以id2和通知本身不证明有编码字节。

源路径锚点为`src/ipsx/release/spu/all/ctrl/common/buf_ctrl/buf_ctrl.cxx`。S的上游结果、Q内容、ES字节writer、CMOS/YC输入和完整3c4派发仍未闭合。global80a720c8用于(root+100)-u32[be000064]，其与ARM根A初始化的绑定未完成；不能将BSS地址减base后当文件数据。

E1（启动指令和多入口）→F1（分段静态映射）；E2（实际结果copy/cache/sync/SW）→F2（MCU发布指令）；E3（id2/P writer）→F3（结果内容有CPU来源，但实际编码字节仍缺）。[source-pins.json](source-pins.json)和测试保存内容型证据。`MCU_executed=false`、`actual_ES_byte_writer_closed=false`、`capture_verified=false`。
