# 全部剩余产品工作矩阵

用户在核对剩余事项后要求“好的，全部完成”，随后要求先清理磁盘并把自有主机 `/tmp` 材料迁回项目。清理和常驻规则已完成，产品主线继续。以下按实际证据更新，旧收据保留当时的deferred／失败，不回填。

| 能力 | 源码／host | 原系统实际消费 | 本轮状态与剩余 |
| --- | --- | --- | --- |
| 默认原cold到HUD／MENU | 入口、ABI、lease、首帧预算已验 | 无参数start.sh、原脚本7项、28请求56边、保存退出通过 | 已发布ce25af2；完整硬件上电另列 |
| 原USB枚举／认证／版本／root | 候选DWC3／EP0、原PMCA、worker、回收守卫及host SG映射修复已验 | 054c0336/config1/4端点、认证7步、19B版本、四零Uid/Gid、中和、70,912B大OUT全文读回及保存退出通过 | 公开usb-large-out-file-cycle-20261110.json；正常AP模式另列 |
| 窗口RAM保存／恢复 | 候选登记、同源build、fd流、same-disk／snapshot失效和GTK已验 | 同一原窗口、源MENU捕获、498620574B流、同bootid、目标原MENU／HUD、源目标QMP0及10停止卷通过 | [窗口RAM报告](2026-11-09-window-ram.md)／window-ram-20261109.json；待本批发布；WBI另列 |
| 同USB root持久文件周期 | 有界命令、请求/回执、原版目标恢复、p2事务及实际host验 | v14同USB 93B写/读回、同盘新冷启动读回、52B原文件恢复、detach、四次QMP0与19卷冻结全过 | 限定通过；v3/v4 BrokenPipe与保全记录不回填，完整设置语义另列 |
| 默认虚拟SD容量与持久化 | 默认1GiB FAT16/32KiB簇；非零4KiB种子、guest有界pwrite/全文SHA、稀疏范围导出；干净副本构建/RAM0与最终host通过 | 原AP首轮写DB/XML，第二冷启动Open/MENU/再次导出；独立FAT全文和整卡SHA一致，QMP0/19卷冻结 | 限定通过，见1GiB专题/双收据；Backup首次拒绝后重试、驱动false保留；不代表拍摄成片 |
| 冷盘配置复位 | 仅p2、完整前像、其它字节核同、逻辑CAS／lease、失败回滚／未决阻启动已实现 | v14显式UI确认、事务committed、p2读回、区外字节不变、固件与SD未复位、原52B文件恢复读回全过 | 限定通过；不等于全部设置/首设语义，旧v4失败不回填 |
| 普通AP USB模式选择／MSC | usb_extcmd原身份准入、MSC IMDB实际优先路径、被动资源观测及原输入/LCD门禁已修 | 原openSvc state1→5/rc0、0x25b选择MSC行、正在连接至海量存储器页面已见；DSO/function/host枚举/块读回仍false | [MSC边界](2026-11-10-usb-msc.md)／usb-msc-frontier-20261110.json；继续原生产者/服务激活，20a3仅候选而非已证同因 |
| 通用USB大OUT | bridge仅剥离host 0x00ff0000 DMA/setup映射位；SHORT_NOT_OK/ZERO_PACKET保留，未知flag拒绝，guest校验不变 | v13/v14真实70,931B线请求status0/actual70931，guest 70,912B全文SHA读回及清理通过 | 限定通过；旧-95与EEXIST失败保留，其它bounce边界和物理格式未验 |
| 全部设置／首设完成跨重启 | 完整Backup文件双bank、语言/日期API／原文件读回已有 | 仅语言/日期及完整文件一致性通过 | 需额外设置项／首设完成、原同步和重启读回；不能仅核全文件SHA就称全语义通过 |
| 电源／稳定性 | 正常owner保存/退出，失败保全已实现 | 原MENU短事务和普通保存通过；历史APO/黑帧失败保留 | 反复开关／长运行／黑帧唤醒与原电源状态恢复待验 |
| 输入性能／全部控制 | 连续LCD、常驻原App32、按压释放与registry已有 | 已测中位97.3ms/max121.1ms | 严格全部<100ms未过；真实变化>15fps和所有按键/拨盘/触摸矩阵待验，读取次数不当FPS |
| 完整原启动／WBI | 原cold与限定QEMU RAM roundtrip已有 | BootROM／loader／原CP／SonyWBI／watchdog未完整执行 | 最终官方一致性独立审查要按最终代码和实际内容，不能称“全部一致” |
| 完整BODYDATA系统更新 | 研究原SDK/存储/crypto部分通过，必要模块还需接产品 | v25仍在约99.7MB后段失败；只读新证卡内BODYDATA全文SHA=2c08…且坏块与独立参考相同，排除卡构建/包内容，定位到guest读取或buffer交接 | 原路径A:\\BODYDATA.DAT未被旧斜杠观察器识别；候选只读诊断已过GNU11/ASan，实际读回与完整安装仍未过，不启动盲等整包 |
| 取景／照片／录像写卡 | CMOS／optics／AF／JPEG/H264／MPR/Fsys适配组件已有 | 原AP触发→实际帧→编码消费→原Fsys成片全链尚未过 | 用户已恢复推进；capture_verified保持false，主机独立生成文件不算 |
| recovery／清理／主机tmp | 根AGENTS §10、旧配置归档、活引用／loop／netns守卫已落盘 | 6份RAM稀疏／680重复缓存删／183配置读回／82项tmp迁移通过 | 实际回收158.58GiB；/tmp/cpfw在用loop11保留；其它机型/未知归属不动；完整报告本机scratch |
| 产品最终复现／发布 | 无缓存副本的QEMU/guest/1GiB卡与新实例RAM0已实际通过；默认build缺guest及observer安装点已修 | 当前默认／USB／RAM分别有原消费证据；干净副本只记构建/准备，不冒充另跑AP | 默认host 413过/41跳过、低延迟2 workers八组过；最终source清单、commit/push/readback后发布 |

本机实验只使用普通虚拟盘，不接真机、真实SD或物理磁盘直通。当前不启动子代理；主会话负责实现、原证据核对和集成。每项大问题直接在产品docs维护，研究资料继续留在analysis／a7c2-re；不把研究目录整包复制进产品。

新实验数据、固件、RAM、构建与日志放本项目目录。主机`/tmp`不再承载这些材料；短socket用专属`/run/user/<uid>/`并正常收尾。当前user活窗口与其它机型保持，失败VM只有核实际CANCEL/端口释放并保全后正常QMP退出，不强杀或提前释放lease。
