# 2026-11-06 文档进展发布

本次整理研究环境中已核的完整离线 cohort、Once／source 工具失败与修正、晚期 4000（OP22）的有限控制内容，以及下一笔 4072 发送失败与安全收尾。**只发布文档与摘要；公开运行代码、测试源码、构建接口和 10 月 31 日移交的源码版本保持不变。** 原 JPEG／MP4 仍未完成，`capture_verified=false`，物理 ASIC 兼容性未验证。

## 阅读入口

- [当前进展与功能矩阵](../../docs/tech/2026-11-06-current-progress.md)
- [机器可读研究摘要](../../validation/2026-11-06-progress.json)
- [此次发布检查收据](../../validation/2026-11-06-documentation-publication.json)
- [既有公开包测试与历史记录](../../validation/README.md)

## 来源与限制

研究来源为 `a7c2-re` 中原生 QEMU 成果的 vxju 完整离线 cohort 与 EHG 原固件QEMU运行。离线侧实际通过 22,952 tests／20,213 subtests，JUnit 43,165、0 failure／error／skip，1,388 sources／277 modules；原 3dgq 失败 21,557／20,131（14 failure／1,390 error）保留，必要复查 1,431／1,698 通过。原固件QEMU侧 `run-ehgdk5qp` 的晚期 OP22（4000）返回 240 B、config 24→25，4057（OP14）完成，下一 4072 发送断言失败，UI1 以 FirmwareFault 结束；卡上无 JPEG／MP4。

本次把已核结论整理成自包含的公开摘要，没有复制原运行证据。源摘要和独立读回身份固定在进度 JSON；它们用于来源追踪，不能替代本公开包的原 VM 复验。公开运行源码基线仍为 `d6fb503`，不含研究侧 OP20／21／22／23 的最新实现，也不能直接复现 22,952 项测试或把离线通过当作原固件成片通过。旧公开 shutter-gate 源码发布继续保留。

本地隔离 QEMU 任务仅使用官方 2.01 ALLLANG 和普通虚拟磁盘文件，未连接真机或物理 SD。Sony 固件、系统 dump、私有配置、卡／guest 镜像、原始栈／反汇编、nonce 和运行日志不随包分发。

## 此次如何校验

本次草稿阶段只做只读检查：核对权威来源文件的大小／SHA-256，解析新增 JSON，检查 7 个候选文件的精确白名单，扫描 Markdown 相对链接是否只指向已存在公开文件或本包新文件，并检查禁用路径／秘密标记。公开源文件在草稿前后不变，公开仓工作区在读取时为 clean。

父会话在正常提交前另行执行并记录：

```bash
bash analysis/sync_repo_scripts.sh --check
python3 -B tools/check-source.py
sha256sum -c SOURCE-SHA256SUMS
```

`SOURCE-SHA256SUMS` 由父会话在候选文件落位后最后更新；本包不生成自引用摘要，也不把未执行的检查写成通过。发布采用普通 commit／push，不使用 force。完整 host／软件模型集、ARM／双原 ABI、实际 QEMU API、GUI 与原成片均未在本次重跑；历史测试保持原日期和范围。

| Evidence | Finding | Path |
| --- | --- | --- |
| 已核研究摘要与来源 SHA | 离线 cohort 通过；原固件QEMU 4072 发送失败；无媒体 | 研究读回→脱敏摘要→本包文档；不能冒作新源码移交 |
| 草稿只读检查 | 7 文件白名单、JSON、链接与来源摘要可核 | 候选包→父会话复检→普通 commit／push |
| 公开运行源码范围 | 本次只改文档；代码仍为 `d6fb503` | [主 README](../../README.md) 与 [验证记录](../../validation/README.md) |
