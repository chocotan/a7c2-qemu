# 照片媒体字段首写：遗留模拟器强写，而非原固件默认值

run-5163p5er捕获到目标appFw字段7e6e7f0从0变为1。写入者经主会话
匹配选中observer摘要、原符号和机器指令后，确认为模拟器自己的
plane_config_send中的遗留KEY_GATE_OVERRIDE。

这项发现纠正此前初始化来源假设：不能再把观察值1解释为原固件默认值、
持久化配置载入结果，或因此修改录像选槽/添加第二张卡来掩盖错误。

## 运行证据

硬件entry断点核原Application_System_Init入口后读取baseline=0，随后安装
4B硬件写watchpoint，记录一次0→1，未调用setter或修改应用寄存器。
这里“观察不写”的限制只适用于调试探针；被观察的遗留模拟器另有错误写入，
本轮正是捕获该写入，不能把整个运行宣称为无业务状态强写。

- appFw base=7f3310e000，目标绝对地址7f3af7c7f0。
- 写后PC=7f880922a4，LR=7f88092294；两者不在appFw代码范围。
- observer gate绝对地址7f880d96b0，对应原符号VA7b6b0，得observer
  base=7f8805e000；写后PC对应VA342a4。
- 选中initramfs的simulation/menu-observe.so与主会话核原本机ELF一致：
  329840B、SHA256e8f1884df01e0ec7842f6102f2d98b09cd4bd349fb279a56bf60071a68fbf3f0。
- 原函数plane_config_send在VA33fac、852B；写后PC之前的VA342a0
  为STR w8,[x22,x25]，源中第二项强写目标正是appFw+7e6e7f0。
  固定VA34260/112B窗口SHA256
  195f341277a9e8e548628fc459d08aa8632616690032b0e820684a914da23673。
- 调用栈保留原appFw返回VA34e56e8、34e936c、34c5f84、30ea790、3209e48。

watch结果文件SHA256
1a966434cc08bdac2f3b9e03e0bef62b6a8997e4ff1ac1da2e2f48b83338978c；
GDB原日志SHA256bcd133eb39d75d6b10e6850c14638f9994e1a38ea8c4bc99394fb6ee3df30e77；
console原日志SHA25697598f41f590138a4a723ec51d763b7b3f1bf5d6b6b231b36311f9d655fb67a3。
本轮gtk-input-proof仍保持ok=false、capture_verified仍false；没有改旧proof。

## 安全退出和存储

调试器停止、独立CPU恢复确认、安全关闭guard全部通过，无强制终止调试器。
原Fsys_FlushVolume返回0，owner217在CONT后恢复，最终SD导出fsck返回0。
主会话另算整卡SHA256
7544176af6b70e8ecd3d5825b6fae340c7badcde5db8b41b2e93ab68d446f94c，
与导出一致，并独立运行fsck.fat -n返回0。VM及本轮owner已退出。

## 修复与验收范围

VM结束后，主会话移除plane_config_send中全部七项原业务状态强写，
不以其它裸写或setter替代。新增测试直接提取实际生产函数编译执行，
用七个字段的sentinel分别验证正常、send失败、async分配失败、延迟通知
路径均不改业务值；现有watch/串口失步/SD清理回归一起运行。

宿主回归已完成：41项测试、24个子测试通过，0.77s，退出0。实际函数
sentinel测试以ASan/UBSan执行四条路径；git diff --check通过。
随后启动修复后的单VM自然简中首设/主界面/MENU/REC及只读媒体字段验收，
该轮尚待终态结果，未在此提前标记功能通过。

移除错误首写并不等同原拍摄链已恢复。修复后仍需真实运行核自然首设、
主界面/MENU、REC最终规则、媒体字段与SD安全保存。若其它原设备状态缺失
导致控件受限，应实现实际设备合同，不能恢复这组强写。

首写来源可以据本轮证据闭合；单槽媒体功能及实际照片、录像仍不得标完成。

## 修复后实跑run-7s_eex47

重建后的observer在选中initramfs中SHA256为
326d5e3b3223e9558c03ee8f5da8cd1d5f010ee1b10f3120b07e4b52f24d3c35。
main实际核原简中首设后的拍摄HUD和中文MENU，C1/半按/全按/REC的八个
原App32输入分别被thread302收到。移除七项强写没有使这些已验证路径失效。

八字段只读均返回0：still cache/live=0/0、movie cache/live=1/1、
mount1/2=2/0、product9/index16。原REC图现在显示“存储卡无空间。”，
该图不再显示此前的“插槽2无卡”；这只验证该错误强写的修复效果。
HUD剩余数仍为0，没有产出照片/录像，下一阻塞为任务50容量消费者。

原Fsys_GetFreeSpace多次返回0，日志首wordff77的完整结构语义尚未核，
不能直接称作空闲空间。独立fsck.fat -n显示11files、4732/65399clusters，
真实128MiB卡仍有大量空闲。因此不能强写剩余容量或关闭容量规则来拍摄。

原Flush返回0，owner217在CONT后恢复（序号920055420496176）。整卡独立
SHA256c351b1d4cf50709d33a53d363f77beadd6d88cff3c06701315eeab814f7b6df8
与导出一致，导出fsck及主会话独立fsck均0。
consoleSHA2567821bf1aa56510c9321a3aa01f23457e2d1907579df2031a8dd686bba6c7e5b8；
REC文件SHA2564efde0e74ee27fba1fb3231b8de357dd04d9ac73098c6d6aeee4533f4334df72。

原自动overall proof继续false，未回填旧失败；main新增限定人工review，
capture_verified仍false。首写来源与删除错误强写的回归完成，不扩大为
完整媒体映射、容量、热插拔或拍摄通过。

只读证据检查器随后重试完成：原全按ON/OFF顺序、22张640×480原LCD图像
的RGB摘要、134217728B磁盘摘要/同一私有副本目录树、CONT恢复记录均通过。
目录中仅DATABASE.BIN(9670656B)和MEDIAPRO.XML(406B)两个普通文件，媒体
候选0，capture_verified保持false。结果JSON摘要为
7f06ff0692c8bb5f76a8be8e9c9b3178de26a9b2832f35b1d6d42a2b3fc8cb77。
首次检查仅因输出目录创建竞态未能启动，错误另存，不回写或覆盖为成功。
