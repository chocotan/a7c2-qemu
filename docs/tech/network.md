# 大步骤 7：让隔离网络的每一层都能自证

这篇解决原 USB 以太网与宿主用户态 peer 的隔离通信，不解决用户要求的 Wi-Fi 扫描、关联虚拟 AP 或全部 Sony 无线业务。

变量见[索引](README.md)；本文只摘录历史实验和协议核对，本次没有访问网络。

## 小步骤 1：先证明原内核绑定了虚拟网卡

**问题 →** 原 bcmdhd 依赖芯片，不能靠 UI 开关凭空恢复无线。
**现象 →** 选择原内核 USB host+标准网卡驱动作为有限隔离数据通道。
**误判 →** 出现网卡名就说可以 ping，或说原 Wi-Fi 已连接。
**定位 →** 核原模块加载、USB 枚举与 sysfs 实际 driver 链。
**解决 →** 已验原模块 `mii/usbnet/cdc_ether/rndis_host/xhci-hcd/xhci-plat-hcd`。
原 `cdc_ether` 在 `usb0` 绑定，平台 `b000000.usb`。
派生 DTB 对应 MMIO `0x0b000000`、size `0x4000`、SPI180、`generic-xhci`。
**剩余 →** 这是本机型板级接线；首次探针没有相机 app/SD，不算整机链路验收。

## 小步骤 2：先查 transport 帧界，不要先怪 ARP

**问题 →** 接口 UP、地址已配，guest RX仍为0，ARP无答。
**现象 →** 宿主发送裸以太帧后，QEMU一直等。
**误判 →** USB枚举警告、guest协议栈或 MAC一定有问题。
**定位 →** 读QEMU `net/socket.c` 的 `net_socket_send/net_fill_rstate`。
该 `-netdev stream` 协议先读长度，再读帧；不是裸帧 socket。

```text
发送格式：4字节 big-endian uint32(len(frame)) + frame
接收：累积完整前缀，再累积完整载荷；不要把一次recv当一帧。
本peer拒绝超过64KiB的荒谬长度。
裸帧以ff ff ff ff开头时会被误当约4GiB长度，故一直等。
```

**解决 →** peer按长度前缀封装和解帧，链路开始出现双向流量。
**剩余 →** framing正确只证明帧可过链路，不证明guest接收ICMP成功。

## 小步骤 3：按实际字节重核 MAC、长度与校验和

**问题 →** 宿主说已答，guest ping却100%丢包。
**现象 →** 宿主→guest已通，guest→宿主仍收不到应答。
**误判 →** “收到请求并发回了”就等于guest收到。
**定位 →** 逐帧核以太头14B、MAC6B、IP地址4B和真正发送的ICMP载荷。
历史发现 `_ipv4_frame(src,...)` 把4B IP当6B目的MAC，帧长96而非98。
另有 reply把type/code改0/0后沿用请求checksum，只重算了IP头。
**解决 →** 目的地址用 `guest_mac`；按实际reply字节重算ICMP checksum。
校验 `checksum(reply)==0`；IP头checksum与ICMP checksum分别处理。
**剩余 →** 本页不推导未核过的原Sony无线协议，不能靠同名Wi-Fi控件扩大范围。

## 小步骤 4：收紧双向“成功”的判据

**问题 →** 旧 `guest_ping_verified` 判据只知道宿主发了reply。
**现象 →** peer自己有 answered counter，guest统计却0 received。
**误判 →** 用生产端发送计数代替消费者接收证据。
**定位 →** 同时取匹配payload、peer计数和guest原ping统计。
**解决 →** guest成功要求其自身输出 `M packets received` 且M>=1。
修后原guest实见2 transmitted/2 received/0% loss，历史探针双向通过。
旧判据得到的true作废，不回填旧运行。
**剩余 →** 这只说明隔离USB以太网上的ICMP，不是宿主系统路由ping或无线关联。

## 小步骤 5：把独立链路接到相机运行，再做 ON/OFF/ON

**问题 →** 独立shell探针通过，正常相机profile可能没带入开关。
**现象 →** 启动器会清除继承的MENU/QEMU变量，裸调用与正式入口行为不同。
**误判 →** 在host设置变量就当guest一定启用；只改按钮颜色就显示已开启。
**定位 →** 核正式profile显式透传、guest接口状态和实际数据通道。
**解决 →** 后端同一串行控制队列更新真实接口，回读后才更新状态。
同VM ON有本次新匹配echo；OFF接口down，新探测无回复；再次ON有新匹配echo。
本包后续正常相机运行也已复验ON/OFF/ON，并正常保存SD退出。
**剩余 →** 本包这两轮用UI同一后端队列，没有另做GTK开关鼠标点击，不能合并宣称。

## 小步骤 6：防止旧应答和隔离逃逸污染结果

**问题 →** 重开链路时，迟到reply可能被当作新成功。
**现象 →** 同IP、同peer的旧包仍可能留在接收路径。
**误判 →** 任意echo reply都可满足下一轮ON；使用host TAP即可叫隔离。
**定位 →** 每次探测记录递增序号、随机nonce与匹配payload。
**解决 →** 本包只连接host用户态peer与guest的Unix stream；不用物理桥或host TAP fd。
OFF用新的探测作负对照，旧应答不能满足下一轮成功。
**剩余 →** 不能把此协议peer当成host系统ping路由；也没有真实Wi-Fi UI关联证据。

```bash
# 执行目录：$PKG；只读查看framing、checksum和新探测逻辑
cd "$PKG"
rg -n 'pack|unpack|checksum|nonce|guest_mac' runtime/analysis/ethernet_peer.py
rg -n 'usb0|ping|nonce' runtime/analysis/usb_network.py
```

## 解决了什么，仍未解决什么

原USB驱动绑定、stream帧界、双向ICMP和后端重复启停已在各自范围通过。
接口名、UI按钮、host发送、guest收到、原Wi-Fi关联是五个不同层次。
用户所指Wi-Fi包括原UI扫描并关联虚拟AP，这一要求仍未完成；USB数据桥不抵扣它。
在既有启动、存储和成像工作之后，最后单独验扫描结果、关联状态与虚拟AP数据消费。
这只是剩余验收方向，本页没有已实现虚拟AP的结论，不借固定ready值掩盖缺口。

## 证据入口

- [网络分阶段失败、修复和集成记录](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/nine-feature-acceptance.md)。
- [当前原模式与网络的真实关系](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/developer-modes/README.md)。
- [本包后端ON/OFF/ON与限定结论](../../validation/README.md)。
- 本包 [peer](../../runtime/analysis/ethernet_peer.py) 与 [网络控制](../../runtime/analysis/usb_network.py)。

## 如果你在做别的机型

xHCI地址、IRQ与原模块可用性必须重新核；未必能复制本机USB路线。
可复用的是分层抓包、精确帧界、独立checksum、新nonce和消费者接收证据。
先把可隔离的数据通道做实，再单独研究原无线控制面。
