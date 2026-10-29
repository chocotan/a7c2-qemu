# 第11条：PinMem 视频输出 → HDMI 视频输入

当前状态：**第11条已在`run-ouc1t64_`与其余12条同轮通过原运行验收**。两条原内核UPM完整消费/free收据、24条原task_hdmi条件receive/free及原AP唯一56B回复同sender释放均通过；本轮SD与退出双锁也通过。见[最终报告](all-graph-connections.md)和[13边收据](thirteen-edges-native-proof.json)。

此前各轮定位并修复了AP/CP Backup命名空间、隔离调试通道、原内核free后及用户free/send收尾窗口的地址复用归属问题，失败结果不回填。详见[逐轮记录](hdmi-video-native-attempts.json)。`capture_verified=false`，无JPEG/MP4。

源码均在本成果 `../runtime/analysis/`。只使用公开 ALLLANG 与隔离本机 QEMU；未接触真机、物理 SD 或完整 dump。

## 已实现的合同

| 项目 | 有限实现与证据边界 |
|---|---|
| 精确端点 | `{4,2,0,90590818}` slot7 → `{4,1,0,909a015a}` slot0 |
| 握手 | 独立64B原请求、64B peer0100、72B peer8100、唯一56B AP8001；未完成时保留原请求，不发布成功回复 |
| 准入 | 实际第10条完成、同sender AP释放、两端canonical Get退役及共同资源检查；不依赖OSD12或音频13 |
| source gate | 从原构造清零的`+0x68`整字建立`+0x6a=0`历史；每个PinMem入口均受观测，未知状态输入拒绝，不在Connect时清零 |
| HDMI起态 | owner必须在任何HDMI输入之前构造；Starting为显式虚拟Initializing，不能临时选择RSEN_Lo |
| 输入历史 | 消费0102、0109、0127，既有八笔配置仍交原配置owner处理；0127保存payload SID，不使用请求source替代 |
| 状态转换 | 原`6255b4`的G58写入、Initializing exit`62547e`、HPD_Lo entry`6255ee`及cached HPD重放 |
| driver工作 | 保存18B初始化和36B配置；有限4806/job6 slot4 row0，实际12B`{7,0,0}`节点读取、释放后完成 |
| 输出通知 | 两笔16B UPM及两批各12笔20B条件通知；真实接收和同接收线程free才计消费 |
| 资源与线程 | 异步等待前释放共同资源锁；继续处理时同线程重新取得；每片段复核保存的registry，不跨线程unlock |
| AP消费 | 只有原请求sender线程成功释放唯一56B回复才置`ap_consumed=1` |

这些是虚拟控制状态、数据与所有权合同，不证明原CP执行、RTOS调度、页表或HDMI物理输出。

## 待闭合的两个真实消费者

条件通知source为`91ca0816`，目的为0127中保存的动态SID，本轮历史示例为`802a0116`。每笔20B为`{2,id,1,0,0}`，id依次为`0,17,16,15,14,13,12,11,23,22,21,30`；进入HPD_Lo与cached HPD重放分别发送一批，不能去重。

真正用户接收方已定位：appFw `task_hdmi`入口`34e3f7c`，在`34e3fc4`接收队列`802a0116`，比较source`91ca0816`，在`34e40c0`释放同一消息；条件0只free，其余11项发布模型事件。两批应是24次receive/free和22次模型发布。现有真实receive钩子覆盖该路径，无需猜测callback。见[条件消费者证据](hdmi-condition-consumer.md)。

UPM目的为`80920572`，16B消息为`{00920117,0,009a0000,0}`及`{00920117,2或3,009a0000,0}`。公开Backup键`00920085`为8B、偏移4为1，因此该公开seed选择第二id=3。原内核consumer为`upm.ko:k_psave_api`（ELFVA`126e8`），无ACK；原注册和真实free仍需运行证据。官方defconfig的KPROBES和FUNCTION_TRACER关闭，不能默认可直接用kprobe/ftrace。

UPM实际接收方是专用内核线程`UPM_TSK_POWER_SAVE_SET`，不是注册callback。`upm.ko`相对`.text+104`原receive，`+13c`调用`k_psave_api`，`+148`调用原free，`+14c`保留实际free返回码。send0只证明入队。

当前实现的专用内核收据路径在发送前准备观察、发送后等待完整收据：绑定同一U↔K地址映射、真实kernel task/TID、consumer分支、refcount/allocator路径和free返回。收据验证完成后只退休用户账本，不再次free已释放的OSAL分配，也不改硬件ready位。缺失或不完整收据仍拒绝。

## 最终唤醒竞态已修复

独立审查复现：最后26笔通知若在待处理片段退出、资源锁刚释放时全部消费，其progress回调可能被`progressing`忽略，最终停在ready=1/busy=1/queued=0。

根修在`pinmem-hdmi-video-connection.c`：仅锁存已由真实消费产生的ready请求；片段收尾保持单执行者，释放资源后同线程重新预约并继续。普通重入不产生忙循环。

新增`finish-window`和`finish-window-recursive`场景，均要求全部26笔实际receive/free后自动得到一份56B回复，不允许手工补progress。独立复核确认P2关闭：74项端点测试通过；临时删除锁存语句后，这两个场景均失败且AP回复为0。未修改生产文件进行反例实验。

## 验证基线

- 59模块：2021项测试、139个子测试通过；317份C/H/inc/sh及5份宿主入口前后摘要稳定。
- 原libc2.25加载与wrapper验证通过。
- observer：`29980f047d9dfe2432ec860be99e4073f55879057e38ab2ccba705a18d5cbedd`。
- ABI收据：`../runtime/analysis/scratch/final-graph-abi.json`，SHA256 `662575985484e70b8b9b3c637a2b5824e681fdec8af2659a7e820681c1e642aa`。
- 回归收据：`../runtime/analysis/scratch/final-graph-host-regression.json`，SHA256 `cbae2c413f4fb3a2ef5990b49e1ead262c12bbf70faa6c9fbc38915a5eef6814`。

后续CP参数表根修另通过60模块2022项/139子测试、319源稳定回归和原libc2.25 ABI；observer为`eb831bf203eb4a4600d7192783f3a0afbcf640136c1be7f6e2eb1d0238f546bb`。9a参数明确从同一固定公开CP bank实际读取，AP动态键继续使用原libbackup API，不把静态CP来源称为AP动态设置。

最终原验使用observer `898a0339c04a1fd6206e5069b66074cf041d797311098693600ef0d4cb08a1af`、321份冻结输入及完整保留镜像。2175/139全量基线和275/276项窄修回归谱系、76项host观察器验证受原ABI收据绑定；HDMI内容验收41项正反例通过。原运行已完成本条有限控制连接，当前仍未取得JPEG/MP4或图像帧证据。
