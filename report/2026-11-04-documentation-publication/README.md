# 2026-11-04 文档进展发布

本次更新整理研究环境中已核的原场景选择、快门／Movie／REC输入、13图连接、严格关闭及403e／VDF剩余阻塞。**只发布文档与摘要；公开运行代码、测试源码、构建接口和10月31日移交的源码版本保持不变。** 原JPEG／MP4仍未完成，`capture_verified=false`，物理ASIC兼容性未验证。

## 阅读入口

- [当前进展与功能矩阵](../../docs/tech/2026-11-04-current-progress.md)
- [机器可读研究摘要](../../validation/2026-11-04-progress.json)
- [此次发布检查收据](../../validation/2026-11-04-documentation-publication.json)
- [既有公开包测试与历史记录](../../validation/README.md)

## 来源与限制

研究来源为`a7c2-re`中原生QEMU成果的huti、Scene／focus／reserved两个专题，最新冻结批`unified-camera-2u4h8eoi`、16,462 tests／12,819 subtests和934项once均已完成。本次把已核结论整理成自包含的公开摘要，没有复制原运行证据。源摘要和独立读回身份固定在进度JSON；它们用于来源追踪，不能替代本公开包的原VM复验。

本地隔离QEMU任务仅使用官方2.01 ALLLANG和普通虚拟磁盘文件，未连接真机或物理SD。Sony固件、系统dump、私有配置、卡／guest镜像、原始栈／反汇编和运行日志不随包分发。

## 此次如何校验

发布流程执行根项目旧成果脚本同步检查、公开树离线源码检查、既有清单摘要读回、变更Markdown链接与JSON检查，以及精确文档白名单检查。刷新`SOURCE-SHA256SUMS`时仅更新变更文档并加入新摘要，原源码项的摘要须全部保持不变；逐文件stage后再核提交范围。

离线源码检查可由读者在[主README](../../README.md#怎么运行)所列依赖及固定QEMU源码归档准备完成后，从本仓库根目录运行：

```bash
python3 -B tools/check-source.py
sha256sum -c SOURCE-SHA256SUMS
```

根项目的`analysis/sync_repo_scripts.sh --check`属于研究工作区检查，不是本公开包运行依赖。本次未重跑完整host／软件模型集、ARM／双原ABI、实际QEMU API、GUI或原成片；历史测试仍保留原日期。上述此次检查是否完成及返回码，以[发布收据](../../validation/2026-11-04-documentation-publication.json)为准。

| Evidence | Finding | Path |
| --- | --- | --- |
| 已核研究摘要及来源SHA | 研究UI／连接有进展，媒体保存仍失败 | 原研究读回→脱敏摘要→本包文档；不能冒作新源码移交 |
| 此次离线source／checksum／文档检查收据 | 公开文档入口与JSON可用、原运行源码未变 | 精确白名单→检查→刷新摘要→stage核对→普通commit／push |
