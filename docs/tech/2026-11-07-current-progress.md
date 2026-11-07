# 11月7日源码与开发进展

本次同步当前权威工作树的运行源码，保留原生菜单路线，并新增独立的[完整系统源码路线](../../report/2026-10-17-qemu-full-system/README.md)。完整系统的持久虚拟盘、开发 UI、USB owner/namespace 守卫、P1 更新 U/D/E 和隔离 DEV 身份适配一并移交；原生侧同步功能模型、输入/状态/退出、成片证据检查器及所需测试。逐文件来源与公开适配由 [source-port 清单](../../tools/source-port-20261107.json)记录，最终身份由 `SOURCE-SHA256SUMS` 绑定。

**原相机程序仍未完成 JPG/MP4 成片，P1 安装与完整启动也未通过。** 本包源码移交、公开 host 检查和研究环境的原 guest 结果分开记账；此次没有重新构建整机 QEMU、运行原固件、连接 USB 或真实设备。默认未知状态继续拒绝，实验 profile 显式选择；40a5 保持禁用。

## 完整系统与当前更新结果

已有完整 dump 路线完成同一持久内部虚拟盘的原 kernel→p3 init→p7 pivot/chroot→原 init2/bootin/im/AP 到拍摄页，原 MENU/焦点/返回和专属程序跨重启读回执行已有独立证据。同盘 RAM roundtrip 在固定 upstream-host profile 下完成，不能推广为 Sony WBI 或任意热启动。显示、输入的阶段体验已由用户接受；源环境测得活动约18fps，全部按键低于100ms的指标仍未通过。这里移交的是这些工作流的当前源码，原 RAM/磁盘/构建收据没有混入源码包。

v35 的[原 host 收据](../../report/2026-11-06-system-update-runtime/p1-dev-identity-v35-host-validation.json)固定1,016项输入，摘要 `a7b2c90b5434c298085d8d3a84a3500c0200ce9a1821258b3d3841379f9e4b0f`、`input_drift=[]`。601 host / 926 subtests / 20 skipped、VHCI7、角色5/5和fresh producer1/8是研究端已闭合结果，不能作为本公开包的测试数。fresh U/E 的隔离 DEV C 为25,336B，hook为22,128B，两阶段逐字节相同；默认 stock C、DSO pin、原 key 比较和四字节逆证明均保留。

后继唯一一轮原 guest 已结束，[v35 actual 收据](../../report/2026-11-06-system-update-runtime/p1-dev-identity-v35-actual.json)记录相同 receiver PID1111 的六个原 passive tap 身份通过，原 SDFileManager Initialize `0xa758` 与 manager `0x7df0` 返回0，原 BODYDATA Open/Seek 与虚拟 trust-anchor reply/copy/free/比较实际发生。旧身份失败和新 DEV profile 拒绝均未出现；后继原 receiver仍返回1。

现在已有原内容与代码窗口支持的具体拒绝点：`DecryptorModule::verifySum()` 在 `DecryptorModule.cpp:110` 比较 **39447 ≠ 60944**，抛出`0x30002`；原 throw LR经PT_LOAD映射为CORE `0xb64c`。这是511个little-endian u16的加和校验。原 key 比较rc0，观测字段 `original_return=1` 只是“原函数已调用返回”标志；真实 key比较LR为ELF `0xac94`。93条原事件与8个代码窗口/3,260B由主会话独立核验，原字节和日志不分发。

这个拒绝不唯一指认上游生产者；原 helper/provider变换或上下文、前512B变换及1024B拼装仍需追查。没有放宽块和、长度、CRC、SHA、RSA或原key校验，DEV不继承stock CBC成功。完整 BODYDATA 读完、bypass实际执行、原writer及安装均未证明。

本轮正常QMP quit、owner rc0、无VM信号，记录的owner/后裔均退出且lease独占重新获得。失败盘只有p2/p13改变，其他19范围不变，失败原件保留。对应`restore-before`已在新独立实例完成，1,962,934,272B / SHA256 `c5603b236a9b5639c9cf3d1af4231e00abac2684a42702d1b82eb281da497c2c`，全盘与21范围主会话独立读回相同；保留原有功能，没有恢复原厂或启动恢复guest。

## 原生模型、菜单和 USB 边界

原生运行源码包含当前OP20参数bank、OP21 crank、OP22 movie-format、OP23 one-way OU-crank、BB timecode状态、保留帧输入/编码输出及完整所有权/退出检查。host软件模型消费不能提升为原AP成片；旧4072失败与后继研究失败仍保留原结论。

原菜单新增入口与bool首切片、最小空正文页已有原事件/状态/LCD证据；完整菜单SDK仍未过，APO恢复也未过。本包同步现有原生运行依赖，不把此轮源码更新说成独立appFw重建SDK全部交付。后台008仍暂停。

USB原通知与模式选择/MSC页面有有限原消费证据；宿主枚举、EP0/function、jiritsu认证/root仍未通过。当前控制与namespace/port/owner源校验已随完整系统路线提供，实际host桥接依赖单独准备。40a5的14槽历史、common APPLY队列到live及kind0效果仍未闭合，绝不以固定ACK或伪ready解堵。启动后黑屏的唯一根因仍未确认。

## 复现与本包验收

普通ALLLANG入口继续见[根README](../../README.md)。完整镜像/持久盘/开发更新的源码入口、外部资源边界与依赖准备见[完整系统README](../../report/2026-10-17-qemu-full-system/README.md)。Sony原件、密钥、私有配置、完整native snapshot及构建产物需读者自己准备，精确摘要拒绝规则保留。

公开host入口为：

```bash
python3 tools/prepare-host-models.py
python3 tools/test-host.py
python3 tools/test-system-runtime.py
python3 tools/test-public-models.py
python3 tools/check-source.py
sha256sum --check SOURCE-SHA256SUMS
```

`prepare-host-models.py`仅从随附公开DTC源码构建宿主libfdt/dtc和项目DTB，源码前后摘要核同，不构建或执行QEMU。原Sony资产相关测试明确skip，存在但摘要错误仍失败。所有实际结果、初始失败和选中范围见[源码发布收据](../../validation/2026-11-07-source-publication.json)。

本包最终检查包括适配器81项、宿主基础384项（58跳过）与完整系统538项／885子测试（39跳过）通过，以及固定QEMU归档、三阶段补丁和硬件源码摘要检查通过。公开模型完整首轮运行1548.77秒，16057项与22456子测试通过、1687跳过，同时暴露44失败／339 setup错误；这些失败记录保留。修复后以8个隔离宿主进程补测：382个不同失败节点全部覆盖，204个通过，178个因缺少明确外部原件或历史真实收据跳过，无遗漏。修改涉及测试夹具、原件缺失说明和公开布局源码摘要，生产实现未改；没有重跑第二轮完整模型集。逐项覆盖与8路结果见[模型补测闭合回执](../../validation/2026-11-07-model-repair-closure.json)。

Evidence→Finding→Path：精确DEV C/DSO来源与U/E完整读回、同PID原Initialize返回0、原verifySum拒绝和21范围恢复 → 身份冲突已越过，更新仍因具体原校验拒绝，不能宣称安装完成 → 发布当前源码与有限收据，保留拒绝和退出/恢复证据，下一步闭合同一块的前后缀生产来源。公开源码的host验证只证明所述软件边界。
