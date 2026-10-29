# 原请求队列写点观察（限定范围验收；恢复仍未完成）

当前已确认原APO撤销到达取消专路，request100原门控值为1且进入原发布入口，但没有取得真正消费/调度证据。静态末端三个候选均为生产侧，精确计数引用分析也未发现直接xref；这不等于没有间接写入。参见[原电源报告](native-apo-power.md)。

此观察默认关闭，仅允许本成果当前用户拥有的单次`runtime/analysis/menu-runs/run-*`、原AP摘要和当前控制窗口owner。原AP SHA256=`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`；custom overwrite拒绝。私有Unix调试socket只在该run的`/out/request-queue-gdb.sock`创建，无TCP监听、无真机或物理盘。

## 方法与限制

- 先用硬件执行断点停在原发布调用`app_base+24d8774`，检查原帧中保存的caller为`app_base+262aafc`，queue为`app_base+7e4e5d0`。此时只读原调用者仍拥有的向量/header，要求原request ID100，不构造或重写消息。
- 在`Q+10`设置硬件写观察，拒绝软件观察点回退。最多16次停止，记录原PC/LR、队列三个原始qword；同值写可能不停止，写前/写后的停点阶段也须另核。
- 计数或free不是消费完成判据。初始caller-owned R与脱链后R的所有权/后继调用尚须关联；不会在未证生命周期下解引用旧request或widget。
- 调试停CPU会影响时序，所以此轮只用于定位；功能验收必须在无此调试的独立运行复验。观察结果默认`ok:false/dispatch_proven:false`，即使有write stop也不当唤醒成功。

## 运行前检查

需要本机支持AArch64的`gdb`。先运行主机测试（不启动QEMU）：

```bash
cd runtime/analysis
python3 -m pytest test_request_queue_watch.py test_sd_session_retry.py test-menu-control.py -q
```

通过后仅串行使用私有实验入口：

```bash
A7C2_VIRTUAL_HCI=virtual-rom-v1 python3 -u check-natural-gtk-input.py \
  --new-ui --firstboot --simplified-chinese --sustain --export-sd --queue-watch-probe
```

该旗标仅为此子会话显式启用原power观察、合法920142一次请求、mode readback及Unix GDB profile，不修改公开默认首设。host从已验证序号的原lib readback核PID及ASLR基址，再按当前run manifest重导所有固定地址；不接受任意target地址。

## 保存与退出

GDB仅由本会话拥有的Popen管理。保存前和finally先请求调试退出，必要时只终止该GDB子进程；不向guest进程发送SIGCONT。SD导出最前面用QMP `query-status`核CPU运行；只对debug/paused恢复并再次核实，再处理任何旧SD序号恢复及新Flush。失败保留旧序号，不创建替代Flush；guest的Fsys owner STOP协议保持独立。

主要证据在该run：`queue-watch-events.jsonl`、`queue-watch-result.json`、`queue-watch-gdb.log`、`queue-debug-cpu-resume.json`。`queue-watch-ready.json`仅表示调试连接及发布断点设置阶段，绝不表示相机、设备、快照或队列消费ready。

## 已执行的前置验证

`bc6ba28e4`主机组合实际为50 passed、2 subtests passed；另通过shell/主脚本/嵌入GTK driver语法及真实GDB Python模块导入，无VM附加。主机测试涵盖owner/原AP身份/路径拒绝、配置地址重新推导与篡改拒绝、caller-owned向量边界及读取失败、QMP return包壳、CPU恢复失败时保留旧SD序号、CPU恢复→旧序号恢复→新Flush顺序、只清理本会话Popen及幂等。这些均不算guest消费/唤醒通过。

独立隔离实跑`b125681a2/run-ns8rhlui`已核：原publication及16次硬件计数变化，包含0→1→2→3→0；发布停点24cba54、清零停点24cce18，均由原store及后继PC独立对应。达到16限额后正常detach、无强杀，CPU与SD/原owner恢复另已通过。晚期LCD全黑，整体恢复false。完整限定review在该run的`queue-watch-review.json`。

新增显式`--queue-handoff-probe`要求同时使用`--queue-watch-probe`，以同一R当前dispatch gate/handler、原ctor及返回S、manager入口/map分支、组队列原payload关联S，再观察原run/析构。不会在构造前读取未初始化对象；不匹配活队列payload时拒绝读取S，ready=0则结束该链，run/析构只在当前调用参数匹配时读取。主机验证及独立串行实跑按新版本另核，不把前一轮50项结果推广到新增代码。

`run-gbywdh97`取得R gate/handler、S ctor/返回/manager五点，但漏了b5c→b68的合法支，未命中b64不能当manager阻塞或完整handoff；旧结果保留partial。修订改等b5c并绑定manager当前SP-90帧，入队前原调用返回便终止关联，原R释放或S析构也终止，拒同址后续对象复用。构造后立即安装S run/dtor硬件guard，不等group之后才安装；SIGINT按主机停止观察处理。

CPU清理修订为`request-queue-control.sock`专用私有Unix QMP monitor，独立于SDK已有QMP/串口。GDB退出后先query-status/必要的cont/再核running，才释放owned run FD并允许下一快照/teardown；export最前guard保留。失败保留run lease与own GUI/VM、独立Xvfb及控制目录，proof列出PID/路径供恢复，退出非零，拒启动下一VM。GUI退出未确认也不SIGKILL。该异常分支不宣称旧正常detach轮已覆盖，新增回归与无固件双monitor fixture单独记录。
