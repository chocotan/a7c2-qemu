# 接收前vtable+28：实际是性能logger，不转换参数指针

已沿真实constructor闭合16919c的callback：**sfmc_enc::performance_log_recv_msg_if**。它按命令选择计时对象，不重写packet+10/+30，也不执行98B copy。不能用此调用解释为何169260能安全解引用输入地址；具体地址转换缺口仍在169174上游。

公开av-cam.bin只读，无固件执行、系统VM、设备/网络或private/full。[8窗口3944B](source-pins.json)使用KVA=ffffffc001000000+raw；不套CP/ELF偏移。结论独立于3249/381冻结轮，gap63/capture=false。

## 对象和虚方法的实际绑定

A6264保存outer this→x19；A62d0设置x0=outer+90，A62dc把该值留到sp+8并由A62e0调用166c44。A63f4重新加载为x3，A63f8调A71a8；该constructor保存x3→x21，经A71f8/A71fc传给1690ac，后者存receiver+10。

166c5c..6c设置vptr=ffffffc001363a18；+28槽raw363a40的8B为`d8a82701c0ffffff`，即ffffffc00127a8d8。RTTI31dd10指向31dce0，其字符串`N8sfmc_enc27performance_log_recv_msg_ifE`提供名称证据。此处不是从日志词或附近类型猜目标。

## 精确作用范围

27a8d8再调同对象+38槽，raw363a50→1670f8。该selector在相关路径只读取packet u16+0/u16+2/u32+2c/u16+a，分别判CID2003、MID0201、command210和subtype，返回计时对象或0。

返回0时27a8e8直接退出；否则将计时对象vptr+18方法装入**x1**并尾跳。原packet pointer已不再作为该方法参数。subtype0/1/3/4/7/8分别选167874/167b6c/167ce8/1679f0/167e64/167fe0；2/5/6为0。全部6个方法只enable计时对象+18、在stack构造描述符、经2efc4调用service00910042，并把返回值存计时对象+8。没有读写packet+10/+30、copy98或2f500调用。

这是对**真实已绑定callback及所有该分支targets**的有界负结论，不是全程序搜索不到converter。不能将方法slot号+28解释成消息offset，也不能把内部计时成功当收包、参数消费或编码完成。

## 当前缺口

[包坐标报告](../native-video-packet-coordinates/README.md)已给出MPR fixed-area两地址以及48B→CMD+8的真实复制；上述logger没有补上原地址域到KVA的转换。[状态动作报告](../native-video-state-action/README.md)的最终输入仍为已有inline。后续[指针转换合同](../native-video-pointer-conversion/README.md)已在更早dispatcher找到Q+10转换并闭合type1/805720f9条件提交；本logger仍不承担转换。type0/default、全98B跨度与runtime选择/lifetime仍未认证。

E1（constructor x3）→F1（实际嵌入context）；E2（vptr/RTTI/两个间接槽）→F2（logger身份）；E3（全部timing targets）→F3（不转换或读取参数体）。没有新增resolver、默认字段、ACK或ready，不报告原帧/编码/写卡通过。
