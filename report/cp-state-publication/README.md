# 源数据回复与完整状态发布后端

此模块把已完成的四字节数据owner、76块完整快照校验和OSAL消息租约接在一起。它不生产缺失的状态字段，不以诊断ACK或BSS零值替代数据，也不构成原CP执行或相机拍摄成功。

代码位于 `runtime/analysis/device-models/cp-state-publication.{c,h}`；统一总验之前仍须接入真实provider与原observer收发钩子。该目录的开发没有启动VM或访问设备/网络/私有配置。

## 请求与发布

- 只接受type0/3003或3000、24 B零尾、source80020002；16 B回复的四数据字节必须由 `cp_start_state_data_build_reply` 从已消费真实虚拟输入的owner生成。HOST_TEST来源不能进入此服务。
- mode1为type5/4073、12 B、payload byte8=1。原mode0/2仍交独立owner；本服务不扩展它们的白名单。
- mode1接管原request前，provider必须给出完整、已发布、与本owner shadow不同的同代76块快照。再次调用 `cp_full_state_snapshot_copy` 核全部头、长度、已知掩码、合法镜头域及代次。不完整时无ACK，原request仍由caller持有。
- 完成校验后先排队独立12 B mode1 ACK，再排队独立6d4 B type6/2040。两次send0只记录排队，不能记AP消费。
- 原ACK必须由本次原sender真实free0；完整2040必须先由原receive观察到同指针/source/长度/全部字节，再由那个实际receiver线程free0。receiver可与mode1 sender不同。
- 只有2040原接收与真实free0、send已返回成功且无fault，才推进此虚拟owner的shadow。外层word+4始终为原协议0，不拿它存generation。

源码合同沿用 `report/lens-init-contract/README.md`：CP357750的mode1立即控制回复、353c18/D93660全量76getter、8dad54发布上下文及AP353277c固定快照拷贝。3003/3000数据源与完整快照布局另见 `report/cp-start-state-data/` 和 `report/cp-full-state-snapshot/`，本后端复用其检查，不重新猜枚举。

## 错误与所有权

constructor仅一次、PID在继承锁之前检查。provider、分配、设source、send、free、日志及父资源guard回调均在私有mutex之外执行。分配别名/短包/source变更/数据变更/未知provider/错误线程/重复receive/提前notice free均拒绝。进入接管后的传输失败保留fault与尚未释放的指针；不会把清理free记成原AP消费。inline原free通过send_inflight记录延迟完成判断，避免send错误被提前消费掩盖。

初始shadow0只是本虚拟owner的显式策略，不是原RAM初始值。readback区分provider数据复制、完整布局复制、队列发送和AP实际消费；business/current/原CP/EE/frame/capture不会因这些动作自动变true。

## 自测

```bash
cd runtime/analysis
python3 -B -m pytest -p no:cacheprovider test_cp_state_publication.py -q
```

一次pytest执行19个独立C进程场景，使用真实四字节算法和真实76块校验器，严格C11/Wall/Wextra/Werror/pedantic及ASan/UBSan。覆盖3003/3000、mode1/2040、不同receiver线程、inline消费、provider未知/stale/坏枚举、两阶段分配失败、send/request-free错误、fork、错误ACK线程、未receive便free、缺前驱及错误请求。数据fixture明确为本机源输入测试，不提升为原运行证据。

Evidence是上述C输入与实际传输回调/字节校验，Finding是排队、原接收和free三阶段已被分别约束；Path为实际provider→完整数据校验→独立消息→原receive→真实free→shadow。当前原SDK/模型provider接线与最终综合VM仍未完成，`capture_verified=false`。
