# 启动流程 09 · 隔离网络：USB 以太网链路与开关

本篇讲网络在启动链路里的位置：默认无网络；opt-in 的隔离 USB 以太网
profile 如何装配（第 4 步）；运行中 Wi-Fi 开关如何验收。
**原 Wi-Fi 扫描、关联虚拟 AP 不在已完成范围内。**

变量见[索引](README.md)。本次只回读源码与报告，没有跑网络实验。

## 1. 默认：没有网络

基础 QEMU 命令行保留 `-nic none`，没有 `-netdev`。
不能因为相机界面有 Wi-Fi 控件就推断存在数据链路。

注意区分两层：底层默认无网；正式 GTK 入口
（`camera_ui.py::main` 的 `VM(..., usb_net=True)`）会装配网络硬件，
但开关初始关闭。没启用 USB profile 的运行会拒绝 `wifi` 命令。

## 2. opt-in profile：派生 DTB + 原驱动

`usb_network.py::prepare_profile()` 生成派生物，不覆盖基础文件：

- 派生 DTB 加入 `usb@b000000` 节点：`generic-xhci`、
  MMIO `0x0b000000`（size `0x4000`）、SPI180、dma-coherent；
- 派生启动脚本保留 `-nic none`，同时加显式设备：
  `-netdev stream,...,addr.path=/out/ethernet.sock` + `-device usb-net`；
- profile 清单记录基础/派生文件 SHA256，并写明
  `link_initially_enabled=false`、`guest_probe_verified=false`——
  装配成功不是驱动绑定证据。

运行时开关 ON 才真正加载原内核模块（`wifi_toggle.py`）：
`mii → usbnet → cdc_ether → rndis_host → xhci-hcd → xhci-plat-hcd`，
然后配置 `usb0`。历史探针记录过原 `cdc_ether` 绑定 `usb0`、
sysfs driver 链指向它——那才是绑定证据。

踩过的坑：只在宿主设环境变量，没穿过 `profile_environment` 的白名单，
派生脚本/DTB 根本没被采用；显示分支覆盖构建选择曾让
`-device usb-net` 报 `No 'usb-bus' bus found`。所以这两个开关都在
profile 里显式转发。完成标志看本次 `runtime-manifest.json` 的实际
二进制/脚本/DTB，不看打印出来的变量。

## 3. 传输层：Unix stream 的长度前缀帧

链路是宿主用户态 peer 与 QEMU 之间的 Unix stream——不用宿主 TAP、
物理网桥或系统路由。协议是 QEMU `net/socket.c` 的长度前缀格式：

```text
发送：4 字节 big-endian uint32 长度 + 帧
接收：先攒齐前缀，再攒齐载荷；一次 recv ≠ 一帧；拒绝超过 64 KiB 的长度
```

踩过的坑：早期发裸以太帧，帧首 `ff ff ff ff` 被当成约 4 GiB 长度，
QEMU 一直等数据；guest 接口 UP、地址已配却 RX=0、ARP 无答。
先查帧界，不要先怪 guest 协议栈。

## 4. 帧字段与两层 checksum

peer 按实际字节构造以太头（14B）、ARP、IPv4（20B 头）和 ICMP echo。
IP 头 checksum 和 ICMP checksum 覆盖不同字节，分别计算。

踩过的坑（两个都实际发生过）：

- `_ipv4_frame(src, ...)` 把 4B 的 IP 源地址当成 6B 目的 MAC，
  帧长 96B 而非 98B；
- reply 把 type/code 改成 0/0 却沿用请求的 ICMP checksum，
  只重算了 IP 头——guest 内核照样丢包。

## 5. 双向验收：各自取接收端证据

- **宿主→guest**：peer 记录来自 guest IP 的 echo reply，
  identifier、sequence、完整 payload 都匹配本次请求才算通过；
- **guest→宿主**：guest 自己跑 `ping -c 2 -W 2 10.0.0.1`，
  解析其输出，要求 `M packets received` 且 M≥1。

踩过的坑：旧判据只看 peer 自己的"已应答"计数。有一次宿主记录
收到并回答了 2 次请求，guest 却打印 `2 transmitted, 0 received, 100% loss`。
生产端计数不能代替消费端证据；按旧判据得到的 true 已作废，不回填旧运行。

## 6. 相机运行中的 ON/OFF/ON

开关命令走与按键同一条有界控制队列（`{'action':'wifi','enabled':bool}`），
后端 `WifiLink` 执行后用 `interface_state()` 回读 `usb0` 的真实 ifconfig
块（UP 和 RUNNING 分开判），回读符合才报 `ok=true`：

| 操作 | 完成标志 |
| --- | --- |
| 第一次 ON | 模块加载、`usb0 10.0.0.2/24 up` 回读正确、ARP 后收到本次匹配 reply |
| OFF | `ifconfig usb0 down` 回读到 down、peer 还在、新探测无应答——三项同时成立 |
| 再次 ON | 同一 peer 连接，重新配置接口，取得**新的**匹配 reply |

OFF 不拆 peer 来制造假不可达；没有 peer 时返回 `probe_attempted=false`，
不算关闭验收。既有验收（含本包 `run-0hlybhgn`）完成过同 VM 的
ON/OFF/ON 加正常 SD 保存退出；这些走后端队列，没有另做 GTK 开关的
鼠标点击验收，两处不能合并宣称。

## 7. 防旧应答污染：序号 + nonce

每次探测用递增序号加 8 字节随机 nonce，匹配时查完整的
`(identifier, sequence, payload)`。历史教训：早期检查器每次发相同内容、
搜整个历史应答列表，把 ON 阶段的旧 reply 当成 OFF 后仍可达。
现在 OFF 和再次 ON 都用全新探测，旧应答满足不了新请求。

```bash
# 执行目录：$PKG；只读查看 framing、checksum 和探测逻辑
cd "$PKG"
rg -n 'pack|unpack|checksum|nonce|guest_mac' runtime/analysis/ethernet_peer.py
rg -n 'interface_state|usb0|probe_attempted' runtime/analysis/wifi_toggle.py
rg -n 'prepare_profile|guest_probe_verified' runtime/analysis/usb_network.py
```

## 8. 边界

已证：原 USB 驱动绑定、stream 帧界、双向 ICMP、后端重复启停。
接口名出现、UI 按钮、宿主发送、guest 收到、原 Wi-Fi 关联是五个层次，
一层完成不能顶替另一层。这里的"ping 通"是用户态 peer 之间的，
不是宿主系统路由。

原 Wi-Fi（bcmdhd 依赖芯片）没有恢复；`virtual-hci.c` 是蓝牙的
有限虚拟 HCI，同样不证明 Wi-Fi 扫描或虚拟 AP。
USB 数据桥不抵扣虚拟 AP 的验收要求，那一项仍未完成。

## 证据入口

- [网络分阶段失败、修复和集成记录](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/nine-feature-acceptance.md)
- [原开发模式与网络的真实关系](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/developer-modes/README.md)
- [本包后端 ON/OFF/ON 与限定结论](../../validation/README.md)
- 本包 [peer](../../runtime/analysis/ethernet_peer.py)、
  [profile 生成](../../runtime/analysis/usb_network.py)、
  [开关与回读](../../runtime/analysis/wifi_toggle.py)

## 如果你在做别的机型

xHCI 地址、IRQ、DTB cell 布局、原模块可用性都要重核，未必能复制 USB 路线。
可复用的是：分层抓包、精确帧界、checksum 分层计算、新 nonce 负对照、
消费端接收证据。先把可隔离的数据通道做实，再单独研究原无线控制面。
