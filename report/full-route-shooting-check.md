# Full方案是否已经稳定拍摄：公开证据核对

结论：**没有已验收的稳定拍照录像。** Full成果中有原拍摄UI、持续菜单操作及
严格像素归属的证据；这些不能提升为有效取景、快门编码或拍摄文件通过。
本次仅只读核查公开文档和验收器源码，没有读full/private、真实setting或私有运行目录，
没有启动VM、改full方案或复验其原始run。以下run结论均为公开报告记载。

| 范围 | 已有公开证据 | 判定边界 |
|---|---|---|
| 完整dump主界面/菜单 | BLUETOOTH-OFF-STARTUP的run-8bej831b：180s观察，40..120宿主秒输入及实际页面；独立Rust窗口run-mo8ofq9s有12项导航，最后动作约94.74s | 有界交互可用；收尾中断runner，末段309仍保留，非正常关机/闲置唤醒/稳定拍摄 |
| Full框架的官方入口 | 2026-10-19-official-first-setup记载首设→主界面→菜单；run-nuniqqkv不可变HOSDAP02与参考RGB相符 | 证明原UI像素归属；不是完整dump run，也不是传感器图像 |
| 持续不黑屏 | 同官方入口五轮最后建屏后约60.1s进入pre-power-off；AP级20B注入不重置timer；菜单动作压在<60s窗口内可过 | 不能称长期稳定/正常省电唤醒；不能用全run时长或帧序号256代替驻留时长 |
| CMOS/镜头/AF | MEDIA-PIPELINE/IMAGING-SUBSET明确未端到端闭合 | 有效取景未验收 |
| 实际拍照录像 | 没有原capture→encoder→MPR/Fsys→JPEG/视频产物验收 | capture_verified仍false |
| SD/编码前置 | Full中RM有卡/挂载仍缺；曾仅选dummy后端但卡摘要完全不变。LIRO原4symbol失败，数据驻留不等执行 | native文件后端/SD的通过不能自动继承到full |

## 交叉检查验收器

Full的verify-shooting-ui.py只要求有内容归属的拍摄UI帧，允许收尾导出零但
早期存在有效frame；没有连续驻留时长、真实CMOS或快门产物检查。成功结果明确保留：
`camera_startup_verified=false, viewfinder_verified=false, capture_verified=false`。

probe-shutter-input.py检查半按/全按是否到原输入消费者，结果仍固定
`capture_verified=false`，明确需要原encoder生成JPEG及原Fsys写入已挂载卷。
因此“脚本成功”“按键41项都到达”“最后帧稳定态”均不足以称稳定拍摄。

## 文档阶段冲突

STATUS.md开头“尚未验收主界面”和后段“主界面完成”混有不同阶段/来源。
README的最新说明和BLUETOOTH-OFF-STARTUP能支持完整dump有限菜单交互；
官方首设报告能支持独立官方run的绘制验收。不能只取旧失败否认所有UI成果，
也不能把官方UI新通过回填成完整dump的摄像通过。未修改这些历史记录。

## 对当前路线的意义

Full可提供原启动、媒体RM、前端输入和显示适配的对照，但尚无已完成拍摄后端
可直接切换使用。下一步仍要分别闭合电源/闲置恢复、有效帧与AF/AE、编码owner、
真实Fsys挂载/文件写入和产物解析。本次未据full早期图像证明native当前问题已解。

公开依据：相邻full成果的README.md、BLUETOOTH-OFF-STARTUP.md、
SHOOTING-UI-REACHED.md、MEDIA-PIPELINE.md、IMAGING-SUBSET.md、
FILE-MEDIA-BACKEND-PORT.md、verify-shooting-ui.py、probe-shutter-input.py；
2026-10-19-official-first-setup/REPORT.md的60.1s五轮及更新验收节。

## Retry复核与独立审查

第二次核查追加公开Markdown/Python中稳定拍摄、capture/viewfinder通过及JPEG/MP4
产物声明检索，并收取独立只读审查结果。独立审查同样未找到full的稳定拍摄证据：
CAMERA-UI.md的40/40扫描明确排除power/shutter，WRITE-THROUGHPUT.md明确仅静态
取证、没有动态压测；两者都不能提升为拍摄能力。公开代码中局部配置/连接verified
为true不等于capture_verified为true，合成测试输入中的true也不是运行证据。

Full的FILE-MEDIA-BACKEND-PORT.md保留历史对兄弟native当时仅Fsys测试的描述，
不能拿它否定native后续已取得的相机DB/XML和SD持久化验收。这里只采用它自身
full的卡写失败/挂载缺口，且始终不把native的存储成功迁移为full摄像成功。
本次依然没有读取私有run或重新启动VM；结论是公开证据未支持稳定拍摄，
不是一次新运行的失败判决。

## 再次Retry：读取当时正在运行的官方派生full实证

这次先查进程，发现已有full VM及runner（run-_xwo2mtn），因此未再启动第二台，
未终止/发键/改变该会话。先单独验证其full-system.json来源为
`official-bodydata-derived`、BODYDATA SHA为
`eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`，
images=19，随后只读取该官方session的run输出，不接触full/private或真实setting。
这不是本会话新启动的实验，也不称为完整dump配置的动态复验。

读取期间它已完成。终态result的terminal_evidence_checked=true，console507973B
SHA256 `76340826194d90ebcefc39475a9a762ce5f00552c07ea0c6d8b530135c4d8fff`
与terminal_console_sha256一致；state=observation-completed、error=null，
但camera_startup_verified=false。viewfinder_verified/capture_verified字段缺失，
不能写成显式false或通过。

该run配置为680秒媒体订阅/通知实验，file_media=off、bluetooth_policy=original，
不是快门或录像验收。console有57条FULL_INPUT_RECEIVE；后段出现0x322，
随后set_pre_power_off_seq的B/E两条记录，最后建屏0x309/count0。
最新live-frame.ppm为640×480纯黑，主会话转换并实际看图；其PPM SHA256为
`a6087ec5178c7619d8136de2aa159dde7161d56f9e4c3b899b7165935d0353d8`。

本run未见Fsys_WriteDirectFileAsync/sdf_encode_jpeg/mc_still_enc字面标记，
run顶层无JPEG/ARW/MP4/MOV文件或capture/shutter proof。这些有界否定不能证明
所有子目录/guest盘上绝无文件，也不能用未执行快门的run判定快门失败；
它只说明这轮没有提供稳定拍摄通过证据，且收尾实际已黑屏。

结论不变但证据更具体：full框架的当前这轮官方派生运行不是稳定拍摄通过，
不能用observation-completed或按键receive计数提升其功能。后续若验收稳定拍摄，
仍需独立计划真实快门/REC、原编码及挂载卷产物，并验证闲置/唤醒与跨run保存。
