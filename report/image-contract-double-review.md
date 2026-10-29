# 成像合同：同题双人独立调查的首轮裁定

两位代理在用户要求后收到同一问题：从既有 av-cam 路线出发，是否能闭合
2000/cmd3 请求消费、实际提交、正常完成及 buffer 所有权。双方不互读结果。
Kimi 报告实际已落盘；Grok 未保存报告，主会话另存其部分交付并注明来源。
两位均已结束，任务34仍未完成。

## 原件身份

公开 av-cam.bin 为13797088B，SHA256
90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096，
主会话独立匹配 native-assets.json。VA为ffffffc001000000加文件偏移。
固定原窗口均不超过1800B；本轮没有运行VM或修改生产运行代码。

## 逐项裁定

| 项目 | 独立结果分歧 | 主会话核验 |
|---|---|---|
| 42bcc 身份 | A称ApiResizeRotate；B称Acquire | 原日志字符串为Acquire / ApiInstanceManager.cpp；支持B的限定结论 |
| 成功输出 | A称u64指针；B称高低word | 原STP存hi32、lo32，随后flag；不是普通小端u64布局 |
| 3c208 | A扩大为提交/ownership；B仅后继调用 | 原函数只是写对象+20hex的word，生命周期语义未闭合 |
| 3d480 | A提出实际提交候选；B未到 | 有对象构造及后继调用，但2000/cmd3实际分派至它的边未证 |
| 97058 | A称复制descriptor+8的像素 | 原参数流与之矛盾：输入x0在该窗口未用，w1为selector，x2为对象；目标为新取得的指针，源为对象+18hex，长度来自内部header |
| 82830759 | A提出完成消息；B未到 | 构造消息的函数存在，但正常完成调用、接收者、释放及freshness未证 |

主会话核3d470/416B的SHA256为
11e92fa20e08703323ffbb0e70bf5f7b20ec0065f4e49ad47c2038f4b02b3405；
97058/240B的SHA256为
3acbdef4a8560f60de4125351e3e185ec8a2a1f832e17e70beffd7fc2c2c52aa。
原字节、映射和反汇编保留于scratch/image-submit-contract/main-verify.txt
及main-transfer-verify.txt。

## 结论与下一入口

没有接受任何可实现的完整成像合同，也没有新增frame-ready或成功ACK。
两人一致不代替证据；各自有不同覆盖缺口，分歧由原指令裁定。
后续仅追3d480的实际虚调用者，以及2f028/2ef9c传输接口的类型和正常完成；
不再把Acquire返回0、状态word或独立消息构造当作一帧已完成。
ValidState0仍既不证明ready，也不证明invalid。整体拍照录像未完成。
