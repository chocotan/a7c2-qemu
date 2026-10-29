# /nondev/rm2的原始打开路径

最新同run证据`run-k3d13p5x`：原MediaConfig查询transport/business均0，配置valid1，
device_id=df10、path=/nondev/rm2、type0、connection count2。原Mount最终api1000/type4的
40B消息status=7fffffff，经原callback克隆投递给原waiter332，读回自然model1cf3=2a。
四个相关原provider库在选定cpio内均匹配原SHA，实际错误图RGBA亦与前轮逐字节一致。
完整链见`../media-mount-final-capture.json`。此轮只有free入口证据，不报告原free成功返回。
原clone的source字段为a5a5a5a5，未以它作为身份；按请求callback endpoint、同一provider tid、
wait queue、原指针及完整40B内容关联。

原`libInfraMediaCommon.so` SHA256=
d7cd602e9348e51703a6d3da396cfda949ea306856df7fa0deb62df1ff4ca974。
`mcmn_drv_open(const char*,u32,void**)`为ELF1b764；getdevinfo2fef0以strcmp匹配逻辑名字。
原表76cc8/76ce8与dummy表77548/77568的rm1/rm2都经重定位指向rm_open3c474，
相应root表都指向rm_mount3c848。因此全局切dummy不会取消RM层。

mod_init2fbac按参数69选择整套表，两分支都经rm_init3d1ec向80d9016e发cmd9，
取112B配置、解析内层MS/MMC名字；rm_mount再发cmd2，以target101/102及返回type2/3/7选择内层driver。
原提供者mcmn_drv.ko SHA256=
dd1106edc77fb05b49ab0b7b8c27e6c2790880415c8915c816aec945f374ad63，
注册在.text+1de8、handlers在.text+18b0/1990；这是ET_REL节内偏移，不是运行VA。
原模块依赖UDIF、Backup、OSAL及可读GPIO的插卡检测，当前没有为了绕过失败去加载它。

原dummy open28964按71eb8表选择/image_mmca等；只在ENOENT且RM index0..2时回退/image_rm1/2/3。
没有直接的/nondev/rm*文件项。内外层复用devctrl/handle，另有root/dev引用和release包装，
不能单独回一个任意handle。全局dummy还改变/dev/nflasha*，不把独立Fsys测试开关直接当APP修复。

下一动态观测已接入：mcmn_drv_open真实参数/返回/errno，以及80d9016e原同步包最多256B完整字节。
Open原函数在初始加载线程缓存，避免在IPC线程上调用dlsym；不改路径、flags、handle或返回。
实际源片段ASan/UBSan验证错误域80000004、输出handle、errno透明及RM raw边界。
cmd9/cmd2的精确规范由独立只读调查继续闭合；尚未确定实际失败于哪一条，不发虚拟ready。

后续`run-hqxkxsfb`已实测：原80d9016e stat在初始线程和实际open线程276均rc0/word0=0/word1=0，
open内caller=7f6580e4f8。原394d0在394f4调用stat，394fc读+4、39500为0时跳39618，
直接返回80000004，尚未分配或发送RM包。这已定位到队列预检查，不是FAT错误证据。
该状态值未被改写；真实队列创建/接收者/所有权调查正继续。
