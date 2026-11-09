# USB 初始化观察器二参 ABI 修复

新同 USB 文件周期在接通 VBUS 时两次进入原 `sen.elf` 异常监视器，均尚未认证、部署 preload 或改写测试文件。根因已在产品被动观察器闭合：原 `usbif_initialize` 是两个参数，单参 INIT_WRAPPER 丢失 X1，原程序随后把错误内存复制进自有回调表。修复只保留和透传两个原参数，原库／driver／认证业务保持。

## 原始证据

| 证据 | 不可变观察 | 推论范围 |
| --- | --- | --- |
| E1 原 `libInfraUsbCmn.so` SHA256 `6caefd0677ee01cc6cdd54555f4422b03a86d12304c60f5372de18315bdd4396` | `0x17db0 mov x22,x0`、`0x17dbc mov x21,x1`、`0x17ea8 cbz x21`、`0x17eb8 mov x1,x21`、`0x17ebc mov x2,#0x78`、`0x17ec8 bl memcpy` | 原入口既消费 handle，又消费120B回调表指针 |
| E2 原 `libsencore.so` SHA256 `3362d4b6e03dc517b04f1eb04d4199ff16d33f6e8f1bfddce657a375778d79e7` | `Usb::initialize_usb_interface` 在 `0xcc28` 加载 X1，`0xcc2c` 调 `usbif_initialize` | 原调用者确实准备第二参数 |
| E3 `run-co7re5dr` 原 callback tree | openSvc 前 root=`0x42c1d0`、ops=`0x42c770`；ops首字段已经含未对齐地址；异常时X20/PC指向相同错误字段 | 错误在openSvc之前已进入复制回调表，不能归咎尚未执行的START或host认证 |
| E4 原callback读取与间接跳转 | `proc_svc_event` 从 root+0x90 取ops、按事件读回调，`0x170fc blr x20` | 错表内容被原事件实际消费；异常摘要address0不是实际PC空值 |

F1：现有 `INIT_WRAPPER(usbif_initialize,...)` 只声明和调用一个 `uintptr_t` 参数，在原函数消费X1前调用了日志函数。X1按ABI是caller-saved，不能依赖日志后原值恰好未变。此前某轮通过只能说明该轮寄存器残留碰巧可用，不能证明单参包装正确。F1有原静态ABI、原调用者和两轮动态失败证据支持。

路径P1：原libsencore准备handle/回调表 → 单参wrapper未保存X1 → 日志消耗caller-saved寄存器 → 原usbif_initialize按120B复制错误指针 → 原VBUS事件读回调 → 原blr跳向未对齐地址。

## 修复和验证

产品 `source/usb-device/usb-start-observe.c` 使用明确的二参函数指针与wrapper，保存handle和callbacks，有限读取120B用于日志，最后以同两个值调用原trampoline，透传原返回值和errno。回调树观测只读，不修正错误地址、不插入默认回调，不改原USB状态或认证结果。

host回归实际执行生产wrapper函数，分别给正常callback表和NULL输入，核两个参数、原返回值、errno及输入120B不变；严格C11和ASan/UBSan两配置执行。测试另核上述六处原ELF机器码pin，原资产缺失时仍有独立wrapper行为覆盖。

新原系统复验与完整同USB持久文件周期另立结果。在实际复验通过前，该周期保持未完成，不能用host成功或历史root通过替代。

## 原失败保全

- v1 `run-_v_9un_b`：全部实际RAM范围／ELF／完整摘要核齐，25,769,317,539 B，SHA256 `b5fc03f6307d9249835b4831dda7d6517a2ab2d406c047e08946316ddef2fa0f`；内部盘原样保留，实际USB断开后正常QMP退出，owner／peer消失。首次lease重获碰到正常释放竞态，原拒绝保留，后独立重获通过。
- v2 `run-co7re5dr`：只增加callback前后被动观测，复现同类失败。完整RAM25,769,317,539 B，SHA256 `8e4bf1315c0cb31d142bb88066307448a651abd9e291bbf2d8aae8901f29ee6a`；原dump驱动超时后仅续收同一dump、核完成字节／所有ELF段／摘要，没有重抓；随后一次正常QMP退出，owner／peer和lease核齐。

两轮保存、原smode恢复和文件周期均未通过；没有执行root载荷，无目标文件写入。宿主虚拟controller属性及模块恢复本轮前像，未操作物理USB或真实SD。原始imports、asm、寄存器、callback字节、RAM和盘证据留在本机 `analysis/scratch/product-usb-file-cycle-20261109/` 与对应产品私有run，不混入公开代码包。

## 二参修复后的 v3 实际消费与清理边界

`run-uiyqr2c7` 未再出现 VBUS 回调异常，真实认证成立。原 worker 的顺序命令全部返回 exit 0：备份并比较52B原文件、挂载可写、追加标记、同步、恢复只读、四零Uid/Gid和93B全文SHA256 `f9ad5f3c27d1d44dd3d354eb9902b43e609c8e6169cf18772cf13b0ea764e366` 均已读回。该轮最终 seq65 的512字节中和内容读取被消费者固定180秒总alarm打断；新增命令与原清理共享该时限。因此这轮不能证明通用IN传输故障，也没有取得完整同USB清理通过，`verified=false` 和原 `jiritsu-root.json` 保持。

故障恢复另走已核身份的原串口，先读到512换行，再写并完整读回512空格（SHA256 `e449eaf70850b3535de8c39146533eec81cab7ce154bdae59affa8b14963e1ae`）；真实VHCI detach后端口status4、原消费者退出。旧host server的SIGTERM被其未释放回执守卫拒绝，只有端口、旧socket和消费者均实际释放后才结束该host-only进程；未向QEMU发信号。随后真实OFF完成设置/SD保存、19卷原freeze和一次QMP rc0。此恢复不算同USB全链成功，v3原失败不回填。

产品现将root会话预算改为基础180秒加每条显式命令30秒，最多16条，recover/version仍为180秒；清理内容及四零判据不变。另有默认关闭的root `--large-out-check`，用原worker输出文件做单次70,912B写入和完整读回，成功后由原worker退出删除。host边界与跨进程摘要绑定通过，实际大OUT和修正预算后的完整USB周期需独立原系统结果，不能由host测试提升。
