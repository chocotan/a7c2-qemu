# 本机虚拟 Senser 的必要协议与 worker

这里只保留产品 version/root 动作实际使用的文件：

- `jiritsu_version_read.py`：有界 GET_FILE2 请求与严格回复解析。
- `jiritsu_preload_deploy.py`：固定 worker 上传读回、前像检查、单次 DEBUG、邮箱与中和。
- `jiritsu_run_command.py`：逐命令读取实际输出和退出码。
- `jiritsu_preload_clear.py`：恢复时的独立中和工具。

它们来自本项目已有的 `analysis/` 实现，不包含 `usb_service_probe` 或其它研究入口。运行时由 `usb_jiritsu.Sources` 对实际加载文件再次计算摘要；不会扫描研究目录。

在当前产品的已枚举 run 上选择一种动作：

```bash
python3 tools/jiritsu-authenticate.py --action authenticate --run /absolute/product/runtime/analysis/menu-runs/run-XXXXXXXX
python3 tools/jiritsu-authenticate.py --action version --run /absolute/product/runtime/analysis/menu-runs/run-XXXXXXXX
python3 tools/jiritsu-authenticate.py --action root --run /absolute/product/runtime/analysis/menu-runs/run-XXXXXXXX
```

默认动作是 `authenticate`。`root` 会同时读取版本并执行下述 worker 前置；不要在同一连接上再启动第二个消费者。物理 USB 路径、其它 run/lease 和未确认恢复状态均被拒绝。

`payload/a7c2_shell.c` 是 worker 审计源码。当前产品固定载荷为 10,328 B，SHA-256 `063248441ad61ecf55c495f986831560e2383b8d3feb52da631d77571781d10c`。v17/v18 大上传失败保留旧 70,912 B 载荷及其摘要 `d261855eb1ea461a77c7847fefef7e6960d4495433d245a9eeb458eef0b35e6e`，不把新产物冒充旧文件。新产物用同一 C 源码、原严格参数以及 `-Wl,-z,max-page-size=4096 -Wl,--strip-all` 构建，六项 host 行为测试通过；guest 执行尚未因此获得验证。任何不同摘要仍在上传前拒绝。

该 worker 只用于用户明确选择的本机虚拟相机 root 动作。部署前读取并保留 loader 前像，拒绝已有非空白 preload 内容；上传后必须逐字读回，身份结果必须包含同一命令、退出码 0 和四列全零 Uid/Gid。最终必须再次读回中和内容。无法确认中和时保持恢复锁存，不能通过断开或旧结果宣称恢复。

离线协议／host 测试只验证实现，不证明原 guest 已执行。实际枚举、版本、root、恢复和保存退出分别验收；拍摄、完整更新和物理 ASIC 兼容性不由此提升。
