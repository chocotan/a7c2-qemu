# 原RM队列、消息与释放契约

原用户API可注册80d9016e对应的真实kernel-backed队列，无须加载带GPIO/MMIO检测的mcmn_drv.ko。
以下是静态契约，不等同当前已创建服务；独占原API传输/注销测试正等待执行。

## 真实队列API

`libosal_uipc.so` ELF6b78：
`osal_reg_msg_queue_cb(u32 id,void **handle,void (*cb)(void *,ulong),ulong arg)`。
80d9016e的bit15=0，转3cd8，以ioctl80000008注册本进程的原UIPC上下文；
`osal_uipc.ko` .text+e90→5278将callback节点接入低16位016e队列，bit31不禁止用户注册。
不能跨进程借用已初始化fd/映射。非广播此路径的consumer负责free payload，代理完成不代替free。
注销用`osal_unreg_msg_queue_cb(id,handle)`。

`osal_stat_msgq`必须提供16B；原KO .text+3160字段：
00=pending消息数，04=有效异步callback数（不计注销节点），08=broadcast标志，0c=sync callback存在。
所以当前word1=0精确表示无有效异步callback，不能改成1伪装服务。
真实valloc上限4096B；注册成功仍不能证明136/32/7B实际分配、投递、消费和释放成功。

## 请求与回复

Common sender394d0先stat、再valloc/snd_msg，随后从显式私有replyQ阻塞接收，非snd_sync协议。
24B小端头：u32 opcode@00，u16版本1@04，u16 payload长度@06，u32 replyQ@08，u32结果@0c，
8B opaque@10。原sender清opaque，KO复制保留，AP未单独检查token。
KO消费并free请求；另从replyQ分配回复，发到header+08；AP拷回后free回复。
发送失败由发送方清理。outer source不是该路径寻址依据，原两端未总是显式设置它。

- cmd9：136B，112B配置；首word配置集1，之后三项36B，按位置对应rm1/2/3。
  项+0 index、+4物理端口聚合位图、+8设备类掩码、+c/+10 MS/MMC selector，
  +14/+18其他类selector、+1c PCI busnr、+1e联合定位byte、+20 PCI能力。
  MMC20/21/22解析mmca/b/c；当前rm2消费第二项，整包+50h为MMC selector。
- cmd2：32B，target@18为101/102/103，type@1c请求0；AP接受2/3/7。
  类型0可查询三次、间隔100ms，耗尽NoMedia；其他不支持类型System error。
  原handler读MMIO/GPIO判卡，不能复制硬件ready常量代替虚拟backing状态。
- 错误回复24B，payload长度清0，错误留+0c。

## 订阅

cmd3总长28B，+18为订阅队列N，0取消。只有已有Front快照才发初始通知，不能登记即冒称ready。
7B通知：byte0=02，byte1/2本链未解释；byte3 bit0/1/2为RM1/2/3 Enable；
byte4/5/6各RM bit0 hold、bit1 port_state、高4位RemoveCnt。
初始通知从N分配，dest=N、source=N，AP free(N,msg)。
变化通知保留Front source及分配归属，AP free(8028017c,msg)；不能混两种所有权。

Enable/port_state不证明磁盘存在或可读写。任何后续有限虚拟SD都必须以owned image的真实
打开、几何、读写/flush和原Fsys消费约束这些状态，并明确全局dummy69对内部卷的影响。

## 当前测试边界

已有独占fsys-file-test新增queue模式：以原reg_cb注册80d9，检查真实16B stat，原分配/发送
32B内部标记，callback逐字节核对并free，注销后另一个进程复核idle。
它不实现RM命令、不生成插卡通知、不返回挂载成功；随后仍会回归原Fsys写与100h重挂。
源已按同一Sony ABI交叉编译通过，运行/消费/释放尚待结果，不报告服务已建立。
