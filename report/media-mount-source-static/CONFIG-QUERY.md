# 80cf016d是MediaConfig查询

先前使用“RM query”的探针标签仅因结果设备名可能为/nondev/rm*，不能据此称为资源管理器查询。
原提供者已独立确认是`libInfraMediaConfig.so`，SHA256
756aa62554f970b7fbfd609d2a53008a3ecc80c608a98ef778baa399efcbebaf。
`libMWF.so` SHA256为63104a2506a385144ee4b485357c72cff7420aedc8d705e40124df20e6f97e69。

原Init6750→constructor6538，在65e8/65f0装入80cf016d，65fc RegisterCallBack，目标CallbackPoint6198。
原IMDB行1edb0指向该provider和InfraMediaConfig_Init，启用maskffffff9f。
run-vzk9iksr原App日志已见该module的B/E Ii，但这不替代callback实际注册成功证明。

## 查询字段

全部offset相对228B原buffer；指针为查询期间原SDK所有，不由探针持有或修改。

| offset | 内容 |
|---|---|
| 00 | u32 API1000 |
| 04 | u16消息类型3 |
| 06 | u16 payload size cc |
| 14 | u32业务结果 |
| 18 | u32 media_id |
| 1c | 配置记录有效byte；不是插卡/上电状态 |
| 1e | u16 device_id |
| 20 | 设备名20B，34终止byte |
| 38 | u32设备类型 |
| 3c | 连接数byte |
| 40 | 四个8B连接项 |
| 60 | 128B属性 |
| e0/e1 | mediaNo/initPriority |

handler6388→GetMediaInfoCmd4e04，遍历16×110h记录，匹配ID后从记录+4复制c8h字节到query+1c。
主会话直接核原4e04原字节，含110h stride、总1100h、200B复制；此函数没有设备打开或卡状态读取。
未知ID在handler中写业务结果1，成功0；MWF SendAndRecv只转换OSAL返回，不判这项业务结果。

原建表5de4读Backup cf0000+i×40h和64个连续单字节项，并按cf040a/cf0408等支持位筛选。
原81e8设备表及SetDevicePathByDeviceID4810给出路径/类型，例如df00→/nondev/rm1、类型0，仍可valid1。
具体本轮media1000匹配哪一条，须以实际查询回复为准，不能从例子直接推出。

## Mount两阶段和最终消息类型

MediaMount请求API1000、消息类型2；初始查询API1002、类型1。旧日志的command字段实际是消息类型，
不是服务API编号。原ParseMessage@libInfraMediaMount.a1a0在a280用`api | 0x40000`建立最终Header，
在a2e0把DispatchCommand结果写header+c，a30c回调发送。因此**最终消息类型为4**。
首次完成消息筛选只含类型1/2，不覆盖它；已补4并做实际源片段ASan/UBSan保序/短帧/errno测试。
正在执行的较早采样使用RM_QUERY/present_byte旧标签；按本文件解释为配置查询及配置有效位。
后续代码已改CONFIG_QUERY/config_valid_byte，并分开记录MWF result和业务结果。

## 错误表边界

`provider-error-tables.json`从原ELF表和R_AARCH64_RELATIVE字符串引用提取：
MWF 1e620/33×20h、MCmn 1ea40/15×20h。主会话独立核7550/76d8循环上限和未匹配返回7fffffff。
多个已命名错误也直接映射7fffffff，例如MWF::ER_NO_RECEIVER(5001)、MCmn SYSTEM/FAIL等。
7fffffff再由appFw转换成模型2a；不代表单一errno或FAT坏。

现有文件后端/dev/mmca测试不覆盖/nondev/rm*。下一项只读调查跟进MediaCommon对这些路径的实际
driver/provider分派及初始化，不凭配置valid就发媒体ready。
