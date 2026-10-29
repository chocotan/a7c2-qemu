# MBP编码接口：双端口mailbox与40a头部记录

已定位实际MCU→MBP命令提交和反向接收协议。此前作为硬件结果候选的P，实际来自CPU `header_mng.cxx` 的40a消息体，必须与40c完成通知分开。像素地址/格式、码流输出与编码控制指令语义仍缺，不启用原生codec。

范围：只读公开Imola2原件、静态反编译/原指令与延迟槽核对；未启动MCU/系统VM、网络或真实设备。原件10934476B、SHA15e75a9732e2f9904ada1c919c631dac0da57e605ce3daa4c6fb2ebe98982b5b。[source-pins.json](source-pins.json)13窗口1488B已按[独立bank工具](../imola-mcu-firmware-contract/image.py)读回摘要核对；RAM1不与ROM混映。

## 实际端口访问

| 项目 | 原值/行为 |
|---|---|
| SPU基址表 | VA802485c8，u32两项bf062000、bf072000 |
| 提交 | 80175c2c：index先截u8再检查<2；最多100h次轮询status+10的bit1 |
| 可提交 | AND2后BNEZ进入提交；不是等待该位清零 |
| 数据寄存器 | command写+0、argument写+4 |
| doorbell | 最后向+10写1 |
| 接收 | 8000b26c/8000ba08：读+10 bit3，有数据才读+8/+c |
| 接收确认 | 完成读取/分派后向+10写4 |
| MBP本地接收 | 80746fbc：be000010 bit3，读be000008/+c，写4确认 |
| MBP本地发送 | 807470f4：be000010 bit1，写本地+0/+4，再写1 |

发送超时调用8000ae50断言，但80175ce0明确跳回寄存器store，延迟槽v0=1；只有断言本身不返回时才不会继续。因此不能将断言当作可靠失败返回。index错误也有断言后继续寻址路径；虚拟接口可以保守拒绝非法index，但须标为适配器约束。

原代码显示SPU端口和MBP本地相同寄存器布局；两侧实际硬件别名和IRQ绑定未证明。实现可采用明确的虚拟paired-endpoint连接，但不能称作原芯片物理别名已验证。硬件FIFO深度、reset后的完整status值和其他位同样未知；bit1只表达mailbox容量，不是编码完成或相机ready。

## 编码命令块

80176a4c读取u32[req+18]为共享命令块指针；80176b30附近对2c00字节按40字节cache1a，再sync。80176ba4→80175d9c→80175c2c发送command20，argument为该指针，并按核mask提交。2c00=11264字节，**不是图像大小**。

RAM1的80745aac在command20分支到80745c9c，将参数传给8079cb14，queue参数1。80748298取命令块+9c0为控制子结构，随后出现当前MIPS32工具未解释的字：68e50400、b0e20d00/01/03/04。其是否为其他标准MIPS变体、工具缺失或厂商扩展正在独立核查；没有把这些操作变成NOP或猜成寄存器读写。RAM2有相关AVC/MBP字符串，但不能据此认为其指令/行为与RAM1相同。

## P来自CPU40a，不是原始硬件结果

```text
header_mng F+20e4
  ->8007f108 send40a
  ->801c4c6c分配ec字节body
  ->801c55a4复制7个u32与后续+1c记录
  ->80089ad0取消息+8
  ->80088ba8原样传vtable+1c
  ->vtable8023c838槽1c=80086c84
  ->800811f4实际计数consumer
```

800865a4的构造路径把8023c838写入对象，闭合虚调用身份。80176d18的40c是另一条消息：清req+22核等待位，全部完成后发送原请求字段，不承载此P。

AVC `header_ctrl_avc.cxx` 的80107848从队列取工作对象并调用finalizer；80107c90把所选头部长度累加到F+20e4，80107ccc累加头生成函数返回长度，80108384更新F+21ac与F+20e8（P+c8/P+4）。这是软件头部计数的正向生产证据，仍非整帧编码字节证明。具体AVC实例与F+20bc对象的安装边未完整闭合。

## 下一实现边界

有源可实现部分为两字mailbox传输：实际staging写入→doorbell→对端实际读两个字→确认退休，命令和argument保持原位。它不执行command20、不生成40c/40a、不读取像素或合成ES。单槽容量、未知status位、保守ACK guard与paired-endpoint必须声明虚拟策略；无IRQ证据就不发IRQ。

真正codec后端仍需要同一command20块内的宽高、stride、YC plane/packed格式、ES目的/容量，以及执行和完成条件。E1（端口寄存器）→F1（mailbox前端）；E2（40a及vtable）→F2（CPU packet来源）；E3（头部计数writer）→F3（不能当作硬件整帧结果）。`actual_ES_byte_writer_closed=false`、gap63、`capture_verified=false`。
