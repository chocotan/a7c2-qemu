# 第三条type3连接：InfraImaging OUT0 → ADF IN0

`run-6uf1qibg`已通过第三type3握手：原AP258/TID381消费唯一56B回复并释放rc0/fault0/ap1；callback guard明确未选type5分支，前两边/ADF历史保持。本轮同SD/退出双锁与独立四边原内容复核通过。117个新组合场景、四边联合958测试/139子测试和原ABI通过。见[四边本轮收据](four-edges-native-proof.json)。`imaging_adf_connection_native_verified=true`仅指有限控制连接，`PCM_verified=false`、`capture_verified=false`。

## 实际请求与原件合同

`run-509c5q1z`/`run-en0re8bn`中，原AP消费两端Get后发送64B请求：

```text
target=90050004 source=81cf61c4
c461cf81a0a0a0a0010040001800000040000000000000000010010028000200030000000200000000000000040005900300000001000000000000003f005890
S={3,2,0,90050004}
P={3,1,0,9058003f}
```

源端是InfraImaging六对象slot4；sink是既有ADF **10对象**slot4，不能因源owner为六对象而把ADF也记成六。父交接曾误写ADF6，现已按原表与既有registry核对纠正；不重建或修改ADF owner。

本节地址为CPVA，raw=VA−108000。公开cpapp-b.bin SHA256为`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。

| 项 | 原件证据 |
| --- | --- |
| source | 构造b09f06；属性1109ee4、slot4对象1a3a508 |
| ADF owner | AdfPinCtrl122ef64/vptrd13214；Sender122ef94 |
| ADF完整pin构造 | 67abf0，表d13234/步长12；池1788274/步长56，slot4=1788354 |
| ADF slot4属性 | d13264三个完整u32 `{3,1,0}`，追加SID9058003f |
| 完整初态 | 68b582显式写self/peerFF/state1/pending0；68b570仅vptr/Sender0，不足以证明初态 |
| peer handler | 67a75a→1972b8；197350..390比较P四个完整u32，含SID |
| 额外callback guard | 19743a..44a，仅type5/dir1/index0才调用，type3跳过 |
| sink通用握手 | 197476→68b818，写peer S/state0并生成72B8100；后续无业务posthook |
| source completion | 46f438→68b9a6，只有日志/错误记录，非0104格式分支 |

父独立核表及两个关键窗口：68B callback guard/return SHA `1a608cf1accd2aeac3303df14dc420d43d0a6bc3879684b1b00c0b739c9a9a9c`；58B source completion SHA `7af7c34b97b643ddea3271651fbc50e07c15424e648b15950d57332c2fb385cb`。见`imaging-type3-adf-source-pins.json`。

## 消费顺序与没有发生的工作

64B原请求→64B1000/0100/40/1内部peer请求→72B1000/8100/48/1回复→唯一独立56B1000/8001/32/2 AP完成；源1→2→0，sink1→0，完整self/peer读回，源pending清除。控制信封outer replySID0，OSAL source按完整owner设置，目的AP从本次caller提取。

这条source/sink实例是未连接构造态1，**不是AIP S1**。原AIP S0、AB失败/1004历史保留。type3分支不产生sink marker、DMM申请/SSYN格式、PCM样本、ADF新B0、AVIO作业或source7新事件；不能套前两条边的marker与格式后处理。未来若实际出现type3 0104，需另行闭合其消费合同。

## 实现与回归

`imaging-adf-connection.c/h`要求实际前两条边已clean/AP消费、buffer Free且无未归还所有权，type3两笔Get回复释放后才接管当前request。复用`native_infraimaging_registry()`与`full_adf_registry()`，只改变本边两个端口；旧寄存器、时钟、AB失败、cache、mapped backing、旧control统计和其它端口逐字节保持。

新117场景执行完整0323→0336→032d→BB→首数据边→type8→type3 Get前置，核独立消息/所有权、两个动态caller、分配/发送/释放失败、递归/fork/inline/concurrent free、故障锁存/重试拒绝及高位type3别名拒绝；与前置和registry联合334项通过。完整源/测试只读review1f2无P1–P3。

默认关闭配置为：

```sh
A7C2_IMAGING_ADF_CONNECT=virtual-imaging-audio0-adf-audio0-v1
```

要求已有第二控制边及其完整publicALLLANG/同a0d/同256GB目录SD链，new UI/firstboot/自然快门/安全导出。guest为`MENU_IMAGING_ADF_CONNECT`，exact构造门禁与typed intent不能代替本轮实际消费。

本轮console12337..12345记录64B请求/64与72B握手、callback guard跳过、前驱保持与唯一56B原AP消费。原observer `1b089e606bb01b54d4412e157e54d651cd2810da37fe4743a84589ad96c01e4f`、283冻结源，四边同轮严格评价返回0。旧ADF10对象、源S0/AB失败及相关时钟/缓存未重置。本节通过不包含PCM、图像帧或JPEG/MP4；其余9条连接和302c仍未完成。
