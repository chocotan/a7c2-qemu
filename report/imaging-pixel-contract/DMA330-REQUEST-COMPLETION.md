# 原DMA330请求、描述符与正常完成边

主会话收取研究代理的编译器/IRQ证据后，实际运行`build_evidence.py`和独立stdlib-only `verify_contract.py`：922条保留指令记录、173条重定位记录、137个紧凑范围/4800B以及32个模板footer均通过。该PASS仅指原字节和绑定，没有执行原DMA请求。

原件为`kmod/dma330.ko`，607336B，SHA `9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab`；以下地址是ET_REL节偏移。

## 请求及物理地址

|request偏移|类型|已证含义|
|---|---|---|
|+0|u32|通道0..15|
|+4|u32|描述符数量1..256|
|+8|u32|描述表的p32物理域地址；本加载不消费+0c|
|+10|pointer|配置指针，mem export明确清零|
|+18|function pointer|callback，要求非NULL|
|+20|u64|callback cookie|
|+28..3f|内嵌可写区|种类、附加字段和侵入式队列链接|

请求至少40h可写字节，排队期间存活，不能传用户虚拟指针。`make_inst`于.text+9c8从`info-24h`加载count和descriptor p32，info=request+28h；9d0/9d4重定位确认`arch_p32_to_p64 → arch_phys_to_va`。核内转换已另由[原kernel证据](DMA330-RUNTIME.md)闭合。

每项descriptor为12B little-endian：`u32 length_bytes, u32 source_p32, u32 destination_p32`，循环步进0Ch。src/dst直接进入DMAMOV SAR/DAR的32位立即数，不作为CPU指针解引用。原编译器按32768/128/8/1字节分解，目的对齐也参与选择；不得把编码长度检查当作无溢出、合法backing或目标边界的证明。

## 真正的正常完成

`.text+6908`在通道锁下检查`1 << (ch & 7)`事件，推进active form并经3870再次查剩余form。

- 还有form：3450确认事件、1a98启动下一form；尚不回调请求。
- 没有form：6cdc→5318终端响应；async kind2且channel state2时，5498调用`callback(int32_t status, u64 cookie)`。
- 回调后确认事件，经6e14→4448推进后续队列。回调运行时通道spinlock尚未释放，不可据此设计会睡眠的callback。

正常原微码footer是`DMAWMB → DMASEV(channel event) → DMAEND`。仅生成/提交微码不等于DMA执行。5318同样可被错误路径调用；abort分支给status=-5，不能看到callback就当作成功。

5318先摘链/毒化链接再callback。所追完成链没有释放请求分配；最终释放在调用者/callback边界，仍待具体client核对。不能在IRQ前提前回收，也不能无条件保持owner已退休。

## 当前边界

5c08在通道state≠2的IGNORE路径也能返回0；模块装载、submit=0、模板存在、甚至callback本身都不是数据正确的替代判据。后续需要实际源/目的摘要、对应IRQ/event、status、请求/缓冲生命周期和失败拒绝一起验收。

硬件qtest范围已另验16通道真实微码搬运及冷启动三类总线错误，但原kernel请求客户端未跑通。下一项只调查原proc诊断接口7358/1d10的真实语法及缓冲owner；未执行猜测性命令或补零请求。
