# Endpoint6终端VBB：寄存器编程已到达，像素语义仍缺

已静态绑定endpoint6的8420 consumer及其一条条件硬件launch路径：同一嵌套记录经过地址归一化，写入bf068xxx/bf078xxx及后续engine寄存器。**像素read/write仍未证明**；方向、pitch、packing和完成语义未闭合，不能据此启用codec后端或发成功完成。

范围为公开Imola2只读原字节/构造/虚表/分派核对，无MCU/系统VM、网络、硬件或private/full。12个RAM0窗口14032B及完整身份见[source-pins.json](source-pins.json)。本报告独立于3234/381冻结代码轮，不回填测试或原运行。

## Endpoint与同一nested handle

静态记录80243e1c为`{4,0,0,8006d65c,8,1000,80258ea8}`；不能把首word4当endpoint。入口8006d65c明确调用8006d568(6)，分配95b4字节、在object+4构造driver root，把传入u16保存到object+95b0，再调用8006d480。worker读取该u16，通过8000cc28得到endpoint6，调用801aadac(endpoint,-1)。classifier8006d380把8420映射index3，table80244c6c+3*8为`{8006bcd4,0}`。

outer handler8006bcd4验证u16[M+6]==18h，复制P=M+8的24字节body，保留H=u32[P+14]，经801bd514清message所持引用，再调用8006df0c(driver_root,&retained_P,u16[M+2])。没有仅因queue receive就释放nested work。

8006df0c映射*H并调用driver state对象。初始state0是assert/error handler；active state与core选择未观察。state1方法80072400保留请求到队列，调用8006ff84；starter→800739b0又在32字节reply record中保留引用，再到8007538c。

队列/core寻址包含MTLO→未解释word…001c→MFLO。此处保留其结果为opaque地址，不认证`root+index*stride`，不猜MADD/DMULT，也不宣称当前capture已走该条件分支。

## Work selector与归一化

令A=u32[H]，W按已有MCU mapper形成：A<1e000000时W=A+80000000；否则仅当u32(A+c0000000)<=1fffffff时采用该值，其他得到0。它映射work record，不是把图像plane映射为host pointer。

core mode0选W，mode1选W+4c，mode2提交二者。构造/vtable将两个launch method绑定为801be358/801bdd68。core0首先依序调用：

```text
801bfd98(context,u8[C+1c],W)  改W+0/W+4
801bfed8(context,u8[C+1d],W)  条件改W+8
801bff38(context,W)           编程硬件并launch
```

第一函数从两word减u32[C+18]，再按mode转换；0/1/9保留减法后值，2右移1，3用multiply-high，4/5/d除3乘4并对齐512，6/7/f左移1。数值模式还不是已命名的pixel format。第二函数仅在W8非零时检查mode；1保留，2右移1，其他走assert。两个完整函数已另以Kuna重核（静态），有限数值实现与硬件执行应分开。

## 硬件边界

801c0790对core0使用普通u32 store：

| 同一work字段/条件 | 实际寄存器/操作 | 尚不能推断 |
|---|---|---|
| normalized W0 | bf068214 | 输入还是输出、byte address单位 |
| normalized W4 | bf06860c | plane packing、Cb/Cr顺序 |
| W8 | 条件写bf068810 | byte count或pitch |
| byte W+c | 选bf06861c低bit | 具名格式/任务类型 |
| byte W+d | 可清写bf06880c值的bit31 | 完成或有效含义 |
| context.byte1 | bf068218/bf068610 | bit depth/width等单位 |
| 配置/状态读 | bf068200/600/400，条件800 | 保持源nonzero gate，不造ready |
| 控制写 | bf068034=0，及420/614/21c、条件814 | DMA已执行或完成 |

core1的801c0164对应bf078xxx。801bff38还把W+1c与W+3c交800792a0，后者向后续engine base+1100..113c、1240/1244、1030/1034等写字段；随后8007953c写1到base+1010。构造给core0 initial base=bf064000（start=bf065010），core1 initial base=bf074000。寄存器store和start字存在是内容型源证据，不是引擎已消费内存的证据。

## 实现与验收边界

可独立实现的部分仅是已完整定界、普通指令明确的数值归一化；必须保留opaque字节与错误原子性，不能由返回0推断像素完成。真正engine model仍需FT/VBB/VDO寄存器的方向/geometry/pitch/packing/bit-depth解释，以及actual buffer lease和completion。mode值、active state/core选择、custom queue index及physical alias也未获运行验证。

未闭合与RC selector0、SA1564e的同一lease连接，未证明DMA IRQ完成，更未执行原codec。E1（endpoint与handler）→F1（terminal binding）；E2（retained H到W及launch method）→F2（同一工作记录）；E3（寄存器store/start）→F3（真实hardware-facing边界，而非像素完成）。`actual_origin_pixels_consumed=false`、gap63、`capture_verified=false`。
