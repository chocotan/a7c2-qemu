# 第二十三跑：4070接管后继续至4028拒绝，异步worker仍未完成

本轮独立审查并集成4070六文件候选，完成preload/CPIO/生产RAM卡binding重建和产品宿主回归。真实guest各保留一笔404e与4070，原AP同一线程随后发送type5/4028/16B；4028返回−1020并触发原Imaging3109及系统错误断言。本次没有1010/event39等待现场，也没有第二笔4070 busy。未进入HUD、未发快门、未生成JPEG或写卡，不能记shooting-ready通过。QEMU使用唯一QMP ID正常quit、rc0，无信号，租约保留到退出，原失败完整保留。

范围来自本轮审查→集成→第二十三跑委托，不再委派，不连接真实设备。沿用direct-bootin、虚拟CP和原App32输入，未执行原Sony loader、原CP RTOS、WBI恢复或完整冷启动。flavor=null。更早P1/Fsys/HUD收据保持历史结论，本轮没有覆盖或追认它们。

## 审查及最小集成

[独立审查](../../../../scratch/a7c2-cp-4070-20261115-candidate1/main-independent-review-v1.md)未发现必修P1。P2限制是单笔永久保留、无退役入口、原worker/bracketing/AP1010未执行；README明确正常worker零参数closure会发送1010，未把它降为可选无操作。没有candidate2，也没有借此次集成添加generic ACK。

直接核对AP入口3541ad0：x4/x5/w3为零，调用35358b8后，x22为零的分支跳过回复登记及等待；CP callback475738正常发type4/1010/12B，AP35319cc转内部event39并释放接收包。后续event39业务尚未闭合。AP/CP全SHA和保存的三个pin文件逐窗口字节由[verify-review.py](../../../../scratch/a7c2-cp-4070-integration-20261115/verify-review.py)读回，见review-readback.json；这次没有新反编译会话。

4070独立单笔槽与旧404e槽可同时pending；state_mutex/PID owner、重复/别名、sending/fault/retained_request检查保留。free hook拒绝释放pending，不把rc0当成业务完成。4043仍按原表写0x2bd字节为1并标记apply_pending，旧snapshot ABI及历史审计路径未改。

集成目录：[a7c2-cp-4070-integration-20261115](../../../../scratch/a7c2-cp-4070-integration-20261115/)。先核冻结输入及六文件before SHA，再备份并完整读回、git apply --check、精确应用六文件补丁及after SHA读回；没有覆盖产品其它修改。重建链沿原build-observers.sh→prepare-menu-initramfs.sh→生产derive，真实fsck由既有恢复owner执行。

- preload SHA256：`70c6b6fa64ac1e9ccb82e7f9d0c10b86e8cd534b4f18ea8417fde0692d61bf0f`。
- 生产binding：`derive-prod-c3e519ced810d932`；derivation.json SHA256 `1da97b8f06a305b62d128e0af1addad514cbaf47a80c7ab363018a5f534031de`。
- RAM CPIO SHA256：`fb67fb3d5d5368a59b1eb6294158ed455ba91caf7cba735b1170f285d7d7b520`。
- KO内容未变：`b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5`。

CPIO仅`simulation/menu-observe.so`内容改变，member set和mode保持一致。新binding和1GiB seed实际被guest消费，全卡SHA仍为`71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`；preload和KO的guest SHA也匹配。

产品宿主回归按两组、两线程执行：CP/history为6 pytest方法+100 subtests，UDATE/Backup/BB为6方法+69 subtests，另有CP40b8六场景及BB0159五场景，全部通过。新4070 fixture的14场景由产品pytest入口实际编译运行，含双槽顺序/别名、free保护、fork、fault、sending、重入与并发，ASan/UBSan及严格警告开启。integration脚本中的预填134逻辑场景字段不能取代实际测试计数；不同层级不简单相加。未复跑未改的USB重型回归，沿用第二十二跑原收据。

## 真实guest前沿

运行目录：[candidate23](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate23/)，原run为`runtime/analysis/menu-runs/fae2`；归档逐文件全SHA与原run一致。下列行号使用原console按LF划分的物理行，runtime-summary使用通用换行拆分时行号会不同。

| 原console物理行 | 原事件 | 结论 |
| --- | --- | --- |
| 7503–7506 | sequence6/404e，恰一笔ASYNC_PENDING | 旧404e槽仍工作，handler/internal0901/completion保持0 |
| 7507–7510 | 同tid461 sequence7/4043，request_free_rc=0 | 4043既有路径保持 |
| 7525–7554 | sequence8/4070，raw `050070400600008000000000`，恰一笔4070_PENDING | 4070已被接管，worker/bracketing/internal1010/apply/completion仍0 |
| 7555–7558 | 同tid461 sequence9/4028，raw `05002840070000800000000000000000`，UNHANDLED | AP跨过4070同步发送边界，当前未停等1010 |
| 7599 | 4028原send rc−1020，目的90030001，源80020002，type5/16B | 首个观测到的负send是新的4028 |
| 7677–7680 | lib_assert.cpp:46及infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109 | Imaging3109仍出现，触发命令由4070移为4028 |

本轮旁路send-trace只记录委派给下层的发送，不单独打印被模型直接接管的4070返回值。4070 rc0的证据是已部署并读回的代码、恰一条pending、同一原AP线程随后sequence9/4028，以及原发送非零会断言的路径，不能伪称有独立P18_OSAL_RESULT/4070/rc0原行。

[运行汇总](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate23/runtime-summary.json)记录404e pending=1、4070 pending=1、两种protected-free=0、unsupported=0、三条Imaging commit=0、ENTER_REC_STILL=0、mailbox/broker=false。没有注入1010、没有强行清pending或改EE状态。断言发生后串口边界未知，原诊断器停止追加写入，因此不存在异常后的精确event39等待PC，也没有将初始池快照冒充4070后的池读回。

BB状态继续按真实证据分别记账：0118在7225行pending_mask=3、retained=1、applied/completion=0；0159在7251行记录lower0302、lower_pending=1、lower_sent=0；0500原send在7273行rc0，7277行CONSUMED记录value1/freed3/completion0。0500_CONFIG独立行未捕获，不推断1500或模式后端完成。0118/0159/0500仍partial。

## 收尾、恢复与下一步

QEMU身份pid2311871/starttime126548444已退出；launcher2311804不存在，run内无socket/FIFO且/proc/net/unix无引用。QMP退出ID为`b889a8a6fbaba059785bf74c6c6de748`，原响应为return空对象、同ID；qmp-exit-unknown.json明确process_exit_observed=true、signals_sent空。QEMU rc0、runner closed、租约保持到退出；driver rc2诚实保留业务失败。未重试，首个新拒绝与原断言已充分留证。

恢复前像在集成目录restore；逐文件全SHA读回，目录0700、文件0600，manifest保留原路径和mode。需要回退时，在无活消费者后恢复四个修改文件并移除两新增测试，沿同构建链恢复产物；旧preload、CPIO和构建收据也已保全。尚未执行回退。

四个主目录逐文件st_blocks登记的本轮新增/保留实占为3,014,590,464B，实际回收0B；采样可用1,938,367,467,520B，保留64GiB余量。该计数含恢复前像及当前derive，reflink共享区可能重复计数，不等于底层独占新增。集成前可用1,941,489,709,056B，文件系统净变化单独记录，不当作本任务回收量。补充脚本、报告及收据见final-supplement.json；主目录与补充账本均为采样，账本自身后续写入字节不递归计入。未执行回收；恢复前像、当前binding、唯一失败和检查重放品由父会话接收核收，后续按身份/活引用精确白名单回收可重建品。

下一步是为当前4028先恢复原命令合同：构造器、CP handler/payload、回复或异步事件、所有权与调用者等待方式，再决定最小实现；不在本次4070委托中猜测其语义或泛化接收所有命令。4070的worker/1010/event39及0118/0159/0500后端仍为独立未完成项。

| Evidence | Finding | Path |
| --- | --- | --- |
| AP3541ad0/35358b8固定原字节 | 4070入口不等独立同步回复 | 有界接管→观察下一命令，不能计worker完成 |
| CP475738/AP35319cc固定原字节 | 原worker零参数正常有1010及event39 | 后续实现应绑定真实状态、消费/free与退役 |
| guest部署SHA、7554 pending、7555 sequence9 | 4070当前同步边界已推进 | 保持completion0，追新4028合同 |
| 7599负send与7677–7680断言 | 当前阻塞是4028发送拒绝，Imaging3109仍在 | 先恢复4028合同再实施；无generic ACK |
| 0118/0159/0500 partial日志 | 显示/VDF/模式后端仍未闭合 | 分别验证下层消费者和原AP完成 |
| QMP同ID响应、rc0、无owner/socket/lease遗留 | 失败保全及自有资源生命周期闭合 | 父会话核收原日志/恢复点，再继续下一实现 |
