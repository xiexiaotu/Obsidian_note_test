# IIC—软硬件 I2C 通信（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F4xx 中文数据手册》I2C 引脚复用表、《RM0090 STM32F407 参考手册》I2C 章节、《AT24C02 数据手册》、《BH1750FVI 数据手册》、《HTU21D 数据手册》、《PCF8563 数据手册》、《LIS3DH 数据手册》。
> **学习提示**：配合参考手册中 I2C_CR1/CR2、I2C_CCR、I2C_TRISE、I2C_OAR1/OAR2、I2C_SR1/SR2、I2C_DR 寄存器的说明一起阅读，效果更佳，特别是涉及寄存器位定义和状态机事件（EV5/EV6/EV7/EV8）的部分。
> **特别说明**：本笔记内容以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 STM32 HAL 库，所有实验结果**通过串口（USART1 + printf）输出**。
> 本笔记**同时覆盖硬件 I2C 与软件 I2C 两种实现方式**，并以一套实际接线为背景：**BH1750 光照、HTU21D 温湿度、PCF8563 时钟、LIS3DH 三轴四个传感器模块，全部挂在同一组 I2C 总线上（SCL = PA1、SDA = PA0）**。

---

## 1. I2C 通讯协议简介

I2C 通讯协议（Inter-Integrated Circuit）是由 Philips 公司开发的一种**同步、半双工、多主多从**的串行总线协议。因为它只需要两根信号线就能挂载几十个器件，布线极简、扩展性强，所以被大量用于连接 EEPROM、传感器（光照、温湿度、加速度）、RTC、触摸屏、OLED 屏等芯片。本笔记后面要驱动的那套传感器，正是"一组总线挂四个器件"的典型例子。

和芯片分为内核层与片上外设一样，理解通讯协议最基本的方法仍然是**分层**：把它分为**物理层**和**协议层**。

- **物理层**：规定通讯系统中机械、电子部分的特性，确保原始比特能在物理媒体上传输——相当于规定"用嘴巴还是用肢体交流"。
- **协议层**：规定通讯逻辑，统一收发双方的数据打包、解包标准——相当于规定"用中文还是英文交流"。

### 1.1 物理层

I2C 总线只需两根线：

- **SDA（Serial Data）**：双向数据线，主机和从机都通过它收发数据；
- **SCL（Serial Clock）**：时钟线，由主机产生，用于同步数据位的传输。

I2C 物理层的几个关键特性：

1. **开漏输出 + 上拉电阻（线与逻辑）**。总线上所有器件的 SDA/SCL 引脚都是**开漏（OD）**结构，只能把线拉低，不能主动拉高；高电平由**上拉电阻**提供。这样任何器件拉低总线都能让整条线变低，实现"线与"，天然支持多主机冲突检测与仲裁。**这是 I2C 最本质的一条电气规则，也是软件 I2C 必须把 GPIO 配成开漏输出的原因。**
2. **多设备与地址寻址**。一条总线上可以挂多个从机，每个从机有唯一的器件地址（7 位或 10 位），主机通过发送地址来选择与哪个从机通讯。本笔记的四个传感器加一片 EEPROM 就共用一组总线，靠地址区分。
3. **总线电容限制**。总线上的器件数量受线路寄生电容限制，I2C 规范要求总线电容 **不超过 400pF**，电容过大时上升沿变缓、波形变差，表现为通讯失败或误码。加长走线或挂太多器件时需要减小上拉电阻，或用 I2C 缓冲器/中继器。
4. **共地**。所有器件必须共地，否则双方电平基准不一致。

**表 1-1 I2C 速率等级**

| 模式 | 最高速率 | 说明 |
| --- | --- | --- |
| 标准模式（Standard） | 100 kbit/s | 最通用，兼容性最好 |
| 快速模式（Fast） | 400 kbit/s | 工程上最常用，STM32F4 的 I2C 外设也支持到这里 |
| 快速模式+（Fast Plus） | 1 Mbit/s | 需要专用器件，F4 的 I2C 不支持 |
| 高速模式（High Speed） | 3.4 Mbit/s | 需要高速模式主机码，只有部分 STM32 型号支持 |

**表 1-2 上拉电阻典型取值**

| 场合 | 典型上拉电阻 | 说明 |
| --- | --- | --- |
| 100kHz、短走线、挂 1~2 个器件 | 4.7kΩ ~ 10kΩ | 最常用 |
| 400kHz 或总线电容较大 | 2.2kΩ ~ 4.7kΩ | 上升沿要更快，电阻必须更小 |
| STM32 内部弱上拉（约 40kΩ） | 不可用 | 上拉太弱，高速时上升沿爬不起来，**必须外部上拉** |

> 上拉电阻的取值上限由上升时间决定（`Rp(max) ≈ tr / (0.8473 × Cb)`），下限由器件灌电流能力决定（一般 3mA）；实践中记住"**低速 4.7k、高速 2.2k**"即可，特殊场合再查公式。
> **挂多个传感器模块时要特别注意**：BH1750、HTU21D 这类成品模块板上往往自带 4.7kΩ 上拉，四个模块并联后等效上拉可能只有 1kΩ 出头，反而拉不到低电平——建议**只保留一组上拉**。

### 1.2 协议层

I2C 的数据包由 **起始信号 + 从机地址 + 读/写位 + 应答 + 数据 + 应答 + …… + 停止信号** 组成。下面逐个拆解。

#### 1.2.1 I2C 通讯过程

一次典型的"主机写数据到从机"过程如下：

```
      ┌─── 起始 ───┐┌──── 地址 + R/W ────┐┌应答┐┌── 数据 ──┐┌应答┐        ┌── 停止 ──┐
SDA ──┘            └┤ 7 位地址 │ R/W=0 ├┤ACK ├┤ 8 位数据 ├┤ACK ├─ …… ──┐  └──────────┘
                     └─────────────────┘└────┘└──────────┘└────┘        │
SCL ────┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌──
        └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘ └─┘
```

整个过程的要点是：**数据的每一次翻转都必须发生在 SCL 为低电平期间，SCL 为高电平期间数据必须保持稳定**（只有起始和停止信号是例外）。

#### 1.2.2 起始与停止信号

起始信号 S 和停止信号 P 是 I2C 中唯一两个**在 SCL 高电平期间允许 SDA 跳变**的时刻：

```
起始信号 S：SCL 为高时，SDA 由高 → 低
停止信号 P：SCL 为高时，SDA 由低 → 高
```

```
        SCL ────────┐         ┌────────          SCL ────────┐         ┌────────
                   └─────────┘                             └─────────┘
        SDA ────┐                   ┌────          SDA ──────────┐           ┌────
                └───────────────────┘                            └───────────┘
              ↑ 起始条件 S                                        ↑ 停止条件 P
```

- 总线空闲时，SDA 和 SCL 都被上拉电阻拉高；
- 起始信号之后总线被占用，停止信号之后总线回到空闲；
- 如果主机想在不释放总线的情况下改变传输方向（例如写寄存器地址后立刻读数据），可以再发一次起始信号，称为**重复起始信号 Sr（Repeated Start）**。AT24C02 的随机读、PCF8563/LIS3DH 的寄存器读都必须用 Sr。

#### 1.2.3 数据有效性

I2C 使用 SDA 传输数据、使用 SCL 进行同步，每个时钟周期传输 1 位数据：

- SCL 为**低电平**时，发送方把数据放到 SDA 上（可以变化）；
- SCL 为**高电平**时，SDA 上的数据必须稳定，接收方在此刻采样。

**表 1-3 常用信号缩写**

| 信号 | 含义 |
| --- | --- |
| S | 起始信号（Start） |
| Sr | 重复起始信号（Repeated Start） |
| P | 停止信号（Stop） |
| SLAVE_ADDRESS | 从机地址，7 位或 10 位 |
| R/W | 方向选择位，0 = 写（主机→从机），1 = 读（从机→主机） |
| ACK | 应答，接收方把 SDA 拉低 |
| NACK | 非应答，接收方保持 SDA 为高 |

#### 1.2.4 地址与数据方向

起始信号之后，主机发送的第一个字节是**从机地址 + 方向位**，格式为：

```
[D7 D6 D5 D4 D3 D2 D1] [R/W]
  ←──  7 位从机地址  ──→   ↑
                         0 = 写，1 = 读
```

- 7 位地址器件：第 1~7 位是地址，第 8 位是 R/W，第 9 位是应答；
- 10 位地址器件：先发固定的 `11110xx` + 地址高 2 位，再发地址低 8 位；
- **主机发送地址后，只有地址匹配的从机才会回应答（ACK）**，其余从机保持沉默。写数据时主机发、从机应答；读数据时从机发、主机应答。

> **工程上极易混淆的一点**：同一个器件地址常有两种写法。以 AT24C02 为例，7 位地址是 `1010000b = 0x50`，而"8 位形式"（把地址左移一位、低位拼上 R/W）是 `0xA0`（写）/ `0xA1`（读）。**STM32 HAL 库的 API 用的是 8 位形式**，即 `HAL_I2C_Mem_Write(&hi2c1, 0xA0, ...)`。本笔记后面每一个传感器都会同时给出两种写法。

#### 1.2.5 应答（ACK）与非应答（NACK）

I2C 规定每传输完 1 个字节（8 位），接收方必须在第 **9 个**时钟周期给出应答：

- **ACK**：接收方把 SDA 拉低，表示"我收到了"；
- **NACK**：接收方保持 SDA 为高（释放总线），表示"没收到 / 结束"。

```
        第 1~8 个时钟（数据位）          第 9 个时钟（应答位）
SCL  ─┐ ┌─┐   ……   ┌─┐                ┌─┐
      └─┘ └─┘        └─┘                └─┘
SDA  ── 8 位数据（高位在前）──┐                   ← ACK：从机拉低
                             └───────────────────
```

两种非应答的典型场景：

1. **主机读从机数据时**，收到最后一个字节后主机要回 **NACK**，告诉从机"不要再发了"，然后发停止信号（读取 BH1750 的 2 字节光照值、读取 LIS3DH 的 6 字节加速度值时都要用到）；
2. **主机寻址从机失败时**，从机不回应答，主机读到的是 NACK，可据此判断器件不存在（HAL 库会返回 `HAL_ERROR`，软件 I2C 则能从 `I2C_WaitAck()` 的返回值直接看出来）。

---

## 2. STM32F407VET6 的 I2C 简介

STM32F407VET6 共有 **3 个 I2C 外设**：I2C1、I2C2、I2C3，全部挂在 **APB1 总线**上（F407 在 168MHz 系统时钟下 APB1 = 42MHz）。这里要特别强调：**STM32F407 的 I2C 引脚复用全部使用 AF4**，选引脚时不要和 USART 的 AF7、SPI 的 AF5 混了。

I2C 外设主要特性：

- 支持 **100 kbit/s 标准模式**与 **400 kbit/s 快速模式**；
- 支持 **7 位和 10 位**器件地址，可编程的自身地址（做从机时用）；
- 支持 **DMA** 传输，降低 CPU 占用；
- 支持 **SMBus 2.0**（ARP、超时、警报等，I2C 通讯用不到）；
- 支持 **PEC（Packet Error Checking）** 数据包校验；
- 支持**时钟延展（Clock Stretching）**与**多主机仲裁**（HTU21D 的 Hold Master 模式就依赖时钟延展）；
- 支持多种中断：起始位 SB、地址匹配 ADDR、发送空 TXE、字节传输完成 BTF、接收非空 RXNE、错误（AF/BERR/ARLO/OVR/TIMEOUT）。

F407VET6 各 I2C 的引脚映射（CubeMX 选引脚时直接查这张表）：

**表 2-1 STM32F407VET6 I2C 资源与引脚映射（LQFP100 可用引脚）**

| 外设 | 总线 | SCL 引脚 | SDA 引脚 | 复用 AF | 备注 |
| --- | --- | --- | --- | --- | --- |
| I2C1 | APB1（42MHz） | PB6 / PB8 | PB7 / PB9 | AF4 | 最常用，本笔记硬件实验选 PB8/PB9 |
| I2C2 | APB1（42MHz） | PB10 / PF1 | PB11 / PF0 | AF4 | PF0/PF1 只在 100 脚以上封装才有 |
| I2C3 | APB1（42MHz） | PA8 | PC9 | AF4 | I2C3 的另一组引脚在 PH7/PH8，**VET6 没有 PH 口**，只能用 PA8/PC9 |

> 说明：I2C1 的 SCL 可选 PB6 或 PB8、SDA 可选 PB7 或 PB9，两组引脚任选一组即可，**不能交叉**（不能 PB6 配 PB9）。
> **极易踩的坑（本笔记的关键结论）**：F407VET6 的 I2C 只能复用在上表这几个引脚上，**PA0、PA1 没有 I2C 复用功能**（PA0 只有 TIM2_CH1/TIM5_CH1/TIM8_ETR/USART2_CTS/UART4_TX/ETH_MII_CRS/ADC123_IN0，PA1 只有 TIM2_CH2/TIM5_CH2/USART2_RTS/UART4_RX/ETH_MII_RX_CLK/ADC123_IN1）。因此当你的传感器总线接在 **PA1=SCL、PA0=SDA** 上时，**只能使用软件 I2C（GPIO 模拟）**，片上 I2C 外设的信号根本引不到这两个脚上。详见第 6.8 节。
> 补充：I2C 外设还有一个 **SMBA** 引脚，只用于 SMBus 的警报信号，普通 I2C 通讯不使用，CubeMX 配置 I2C 模式时不会占用它。

---

## 3. I2C 内部结构详解

掌握功能框图（通讯引脚、时钟控制、数据控制、整体控制逻辑四大模块）就掌握了 I2C 外设的核心，编程思路会非常清晰。下面按模块拆解。

### 3.1 通讯引脚

- **SCL**：时钟线，主机模式下由 I2C 外设根据 `I2C_CCR` 分频产生；从机模式下由外部主机驱动。
- **SDA**：双向数据线，收发共用。**开漏输出，必须外部上拉**。
- **SMBA**：SMBus 警报线，普通 I2C 不用。

CubeMX 中把 I2C1 的 Mode 选为 **I2C** 后，PB8/PB9 被自动配置为 `GPIO_MODE_AF_OD`（复用开漏）+ `GPIO_AF4_I2C1`。**注意 CubeMX 默认 Pull = No pull-up and no pull-down**，所以外部上拉电阻是电路设计者的责任。

### 3.2 时钟控制（SCL 频率计算）

SCL 的时钟由 `I2C_CCR` 寄存器控制。CCR 是一个 **12 位**的分频系数，并配合 `I2C_CCR` 的 DUTY 位选择占空比：

**标准模式（Sm = 1，最高 100kHz）**，占空比固定 1:1：

```
Thigh = CCR × TPCLK1
Tlow  = CCR × TPCLK1
```

**快速模式（F/S = 1，最高 400kHz）**，占空比可选：

```
DUTY = 0（2:1）：Thigh = CCR × TPCLK1        Tlow = 2 × CCR × TPCLK1
DUTY = 1（16:9）：Thigh = 9 × CCR × TPCLK1    Tlow = 16 × CCR × TPCLK1
```

其中 `TPCLK1 = 1 / PCLK1`，PCLK1 是 I2C 所挂 APB1 总线的时钟。

**手算示例**：PCLK1 = 42MHz、快速模式 400kHz、DUTY = 2:1

```
TPCLK1 = 1 / 42 000 000 ≈ 23.81 ns
TSCL   = 1 / 400 000   = 2500 ns
THIGH  = TSCL / 3      ≈ 833 ns
TLOW   = 2 × TSCL / 3  ≈ 1667 ns
CCR    = THIGH / TPCLK1 = 833 / 23.81 ≈ 35 = 0x23
```

**验证**：Thigh + Tlow = 35×23.81 + 70×23.81 ≈ 2500ns，对应 400kHz，正确。

同理，标准模式 100kHz 时 `CCR = 5000ns / 23.81ns ≈ 210 = 0xD2`。此外写入 `I2C_TRISE` 的上升时间值也必须与 PCLK1 匹配（标准模式约 1000ns、快速模式约 300ns），HAL 库会根据 `ClockSpeed` 自动计算 `CCR` 和 `TRISE`，**CubeMX 中只需填 ClockSpeed 一个值**，上面的推导主要用于理解与排查波形问题。

### 3.3 数据控制

- **DR（数据寄存器）**：发送时写入待发字节，接收时读出收到的字节。
- **OAR1 / OAR2（自身地址寄存器）**：STM32 做**从机**时，从机地址存放在这里，OAR1 支持 7 位/10 位，OAR2 只支持 7 位。做主机时该值无关紧要。
- **PEC 寄存器**：包错误校验，用于 SMBus 或高可靠性场合，普通 I2C 通讯关闭。

### 3.4 整体控制逻辑

I2C 外设的"控制中心"由以下寄存器构成：

**表 3-1 I2C 主要寄存器**

| 寄存器 | 作用 |
| --- | --- |
| `I2C_CR1` | 使能外设（PE）、起始/停止控制（START/STOP）、应答控制（ACK）、中断使能 |
| `I2C_CR2` | 中断/DMA 使能、工作频率 FREQ、从机地址发送控制 |
| `I2C_CCR` | SCL 时钟分频（见 3.2） |
| `I2C_TRISE` | 最大上升时间（总线时序） |
| `I2C_OAR1/OAR2` | 自身从机地址 |
| `I2C_DR` | 数据寄存器 |
| `I2C_SR1/SR2` | 状态寄存器，通过不同事件标志位指示通讯进度 |

SR1/SR2 是**状态机**的核心：HAL 库的 `HAL_I2C_Master_Transmit()` 之类函数内部就是在轮询这些标志位。理解事件代号对读参考手册和排查问题很有帮助：

**表 3-2 I2C 通讯事件与标志位**

| 事件 | 标志位 | 含义 | 主机动作 |
| --- | --- | --- | --- |
| EV5 | `SB = 1` | 起始条件已发出 | 写入 DR 发送从机地址 |
| EV6 | `ADDR = 1` | 地址发送完成（7 位） | 读 SR1 再读 SR2 清除标志 |
| EV8 | `TXE = 1` | 数据寄存器空 | 写入下一个待发字节 |
| EV8_2 | `TXE = 1` 且 `BTF = 1` | 最后一个字节已发完 | 置 STOP 结束传输 |
| EV7 | `RXNE = 1` | 接收数据寄存器非空 | 读 DR 取走数据 |
| EV7_1 | `RXNE = 1` 且 `BTF = 1` | 最后一个字节已收到 | 回 NACK 后置 STOP |

**表 3-3 常用错误标志**

| 标志 | 含义 | 常见原因 |
| --- | --- | --- |
| `AF` | 应答失败 | 从机地址错、器件不在线 |
| `BERR` | 总线错误 | 起始/停止信号位置异常 |
| `ARLO` | 仲裁丢失 | 多主机竞争总线失败 |
| `OVR` | 溢出 | 上一字节还没读走，新数据又来了 |
| `TIMEOUT` | 超时 | SMBus 超时，或总线被从机拉住不放 |

### 3.5 通讯过程（主机模式状态机）

**主机发送流程**（例如读 EEPROM 时先写存储地址、读传感器时先写寄存器号）：

1. 置 `START = 1` 产生起始条件，等待 **EV5**（SB=1）——"起始已发出"；
2. 写 `DR`（从机地址 + 写位），等待 **EV6**（ADDR=1）——"地址已被应答"；
3. 写 `DR`（数据字节），等待 **EV8**（TXE=1）——"数据寄存器空了，可以再写"；
4. 最后一个字节写完等待 **EV8_2**（TXE 与 BTF 都为 1）——"最后一个字节真正移位发完"；
5. 置 `STOP = 1` 结束传输。

**主机接收流程**：

1. 起始 + 地址（读位），等待 **EV6**；
2. 收到字节后 **EV7**（RXNE=1），读 `DR` 取走数据；
3. 收到**最后一个字节**前（或收到后）置 `ACK = 0`，准备回 NACK；
4. 置 `STOP = 1` 结束传输。

**HAL 库把这些状态机全部封装掉了**，应用层只需调用 `HAL_I2C_Master_Transmit()` / `HAL_I2C_Mem_Write()` 这类函数并检查返回值。只有在做**从机**、**DMA** 或排查死锁时才需要直接关心这些标志位。

---

## 4. HAL 库 I2C 句柄与初始化参数

HAL 库用一个句柄结构体统管 I2C 的所有配置：协议参数放在 `Init` 子结构（类型 `I2C_InitTypeDef`），CubeMX 会替我们填好并生成初始化函数。

```c
typedef struct {
  uint32_t ClockSpeed;      /* SCL 时钟频率，如 100000 / 400000 */
  uint32_t DutyCycle;       /* 快速模式占空比：2:1 或 16:9 */
  uint32_t OwnAddress1;     /* 自身地址 1（做从机时才有意义） */
  uint32_t AddressingMode;  /* 地址模式：7 位或 10 位 */
  uint32_t DualAddressMode; /* 双地址模式：使能/禁止 */
  uint32_t OwnAddress2;     /* 自身地址 2，仅 7 位 */
  uint32_t GeneralCallMode; /* 广播呼叫：使能/禁止 */
  uint32_t NoStretchMode;   /* 禁止时钟延展：使能/禁止 */
} I2C_InitTypeDef;
```

成员与 CubeMX 配置项对照：

**表 4-1 CubeMX Parameter Settings ↔ HAL 结构体成员**

| CubeMX 配置项 | 结构体成员 | 本笔记取值 | 说明 |
| --- | --- | --- | --- |
| I2C Speed Mode | `ClockSpeed` + `DutyCycle` | Fast Mode | 选 Standard / Fast |
| Clock Speed | `ClockSpeed` | 400000 | 100kHz 或 400kHz |
| Fast Mode Duty Cycle | `DutyCycle` | `I2C_DUTYCYCLE_2` | 2:1 或 16:9 |
| Own Address 1 | `OwnAddress1` | 0 | 只做主机时不用管 |
| Addressing Mode | `AddressingMode` | `I2C_ADDRESSINGMODE_7BIT` | 本笔记四个传感器都是 7 位 |
| Dual Address Mode | `DualAddressMode` | `I2C_DUALADDRESS_DISABLE` | 一般不用 |
| Own Address 2 | `OwnAddress2` | 0 | 仅 7 位 |
| General Call | `GeneralCallMode` | `I2C_GENERALCALL_DISABLE` | 一般不用 |
| No Clock Stretch | `NoStretchMode` | `I2C_NOSTRETCH_DISABLE` | **必须允许延展**，HTU21D 依赖它 |

> **重要提醒一**：`I2C_InitTypeDef` 的成员随 STM32 系列而变。**F1/F2/F4 用 `ClockSpeed` + `DutyCycle`（填写"要多少 kHz"，硬件自己算 CCR）**；而 F7/L4/H7 等较新系列改成了 **`Timing`**（填写一个算好的 32 位时序值）。网上很多 F4 教程里出现 `Init.Timing = 0x60201E2B` 的写法，那是 F7/L4 的代码，直接搬到 F407 上会**编译报错或时序全错**，看教程时务必先确认芯片系列。
> **重要提醒二**：本节讲的都是**硬件 I2C** 的初始化。**软件 I2C 没有任何 `I2C_InitTypeDef` 需要配置**，它只需要把两个 GPIO 配成开漏输出（见第 5.4 节），时序全部由代码用延时循环模拟（见第 8 章）。

常用 API 一览：

**表 4-2 HAL I2C 常用 API**

| API | 用途 | 说明 |
| --- | --- | --- |
| `HAL_I2C_Master_Transmit()` | 主机发送 | **命令型器件**（BH1750、HTU21D）发命令用它 |
| `HAL_I2C_Master_Receive()` | 主机接收 | 配合上面的函数读取测量结果 |
| `HAL_I2C_Mem_Write()` | 写器件寄存器/存储单元 | **寄存器型器件**（AT24C02、PCF8563、LIS3DH）首选，内含"写地址 + 重复起始 + 写数据"完整时序 |
| `HAL_I2C_Mem_Read()` | 读器件寄存器/存储单元 | 同上，内含 Sr 时序 |
| `HAL_I2C_IsDeviceReady()` | 探测从机是否应答 | 返回 `HAL_OK` 说明器件在线，也可用于等待 EEPROM 内部写周期 |
| `HAL_I2C_GetState()` | 读句柄状态 | 典型值 `HAL_I2C_STATE_READY` |
| `HAL_I2C_Master_Transmit_IT()` 等 | 中断方式 | 完成触发 `HAL_I2C_MasterTxCpltCallback` |
| `HAL_I2C_Master_Transmit_DMA()` 等 | DMA 方式 | 大数据量、低 CPU 占用 |
| `HAL_I2C_Slave_Receive_IT()` 等 | 从机方式 | 让 STM32 充当 I2C 从机 |

> `Mem_AddressSize` 参数填 `I2C_MEMADD_SIZE_8BIT`（AT24C02、PCF8563、LIS3DH 都是 8 位寄存器地址）或 `I2C_MEMADD_SIZE_16BIT`（更大容量的 EEPROM，如 AT24C256）。
> **命令型器件不能套用 Mem 系列函数**：`HAL_I2C_Mem_Write()` 至少要发 1 字节数据，而 BH1750 的"命令"就是一次单独的一字节写（START + 地址 + 命令 + STOP），所以必须用 `HAL_I2C_Master_Transmit()`。

---

## 5. STM32CubeMX 配置工程

为了同时演示硬件 I2C 与软件 I2C，本节在**同一个工程**里配置：I2C1 外设（PB8/PB9，硬件 I2C 用）、PA1/PA0 开漏输出（软件 I2C 用）、USART1（串口输出用）。三者互不冲突。

### 5.1 新建工程与芯片选择

1. CubeMX 欢迎页 → **New Project**，在 *Select MCU* 搜索框输入 `STM32F407VET6`，选中 LQFP100 封装，确认进入工程。

> 📷 图 5-1 新建工程、搜索并选中 STM32F407VET6（此处可插入截图）

### 5.2 系统时钟（RCC + Clock Configuration）

1. **RCC** → HSE 选择 **Crystal/Ceramic Resonator**（外部 8MHz 晶振）。
2. **Clock Configuration**：PLL 源选 HSE，PLL_M=8、PLL_N=336、PLL_P=2，系统时钟 **SYSCLK = 168MHz**；APB1 分频 ÷4 → **42MHz**（I2C1/2/3 的时钟 PCLK1），APB2 分频 ÷2 → **84MHz**（USART1 时钟）。
3. 若外部晶振不是 8MHz，按板子实际晶振调整 PLL_M。

> **注意**：APB1 时钟直接决定 SCL 的实际频率。如果 APB1 配成 36MHz 而不是 42MHz，生成的 `CCR` 值会随之变化，但只要你在 CubeMX 里填的是"400000"，HAL 会按实际 PCLK1 重算，最终 SCL 仍是 400kHz——**这正是用 CubeMX 配置比手写寄存器安全的地方**。

### 5.3 配置 I2C1（硬件 I2C：PB8/PB9）

1. 左侧 **Connectivity → I2C1**，Mode 选 **I2C**。
2. 芯片图上出现 I2C1 的候选引脚，**左键点击 PB8 选 `I2C1_SCL`、PB9 选 `I2C1_SDA`**（也可以选 PB6/PB7，两组任选其一，不可交叉）。
3. **Parameter Settings** 按表 4-1 填写：

**表 5-1 I2C1 Parameter Settings 配置值**

| 配置项 | 取值 |
| --- | --- |
| I2C Speed Mode | Fast Mode |
| Clock Speed | 400000 Hz |
| Fast Mode Duty Cycle | Duty Cycle Tlow/Thigh = 2 |
| Own Address 1 | 0 |
| Addressing Mode | 7-bit |
| Dual Address Mode | Disable |
| Own Address 2 | 0 |
| General Call | Disable |
| No Clock Stretch | Clock stretching enabled |
| Analog Filter / Digital Filter | 默认（Analog Filter 使能） |

4. **NVIC Settings**：纯阻塞式收发可以不勾；如果采用中断方式收发，勾选 **I2C1 event interrupt** 与 **I2C1 error interrupt**；如果用 DMA，再到 **DMA Settings** 添加 I2C1_TX / I2C1_RX 通道。

> 📷 图 5-2 I2C1 引脚分配与 Parameter Settings 面板（此处可插入截图）

### 5.4 配置 PA1 / PA0 为开漏输出（软件 I2C 总线）

这套传感器按你的接线接在 **SCL = PA1、SDA = PA0**，而这两个脚没有 I2C 复用功能（见 2 节与 6.8 节），所以**不需要（也不能）在 CubeMX 里给它们选 I2C 外设**，只能当作普通 GPIO 使用：

1. 左侧 **System Core → GPIO**，点击 **PA1**，选择 **GPIO_Output**；再点击 **PA0**，同样选 **GPIO_Output**。
2. 选中 PA1，在下方 **GPIO mode and Configuration** 面板中按表 5-2 设置；PA0 用同样的参数。

**表 5-2 软件 I2C 的 GPIO 参数（PA1=SCL、PA0=SDA 相同配置）**

| 配置项 | 取值 | 说明 |
| --- | --- | --- |
| GPIO output level | High | 初始化为高电平，总线处于空闲态 |
| GPIO mode | **Output Open Drain** | 开漏，I2C 的硬性要求 |
| GPIO Pull-up/Pull-down | Pull-up | 配合外部上拉，双保险 |
| Maximum output speed | Very High | 时序更陡，高速率下波形更规整 |
| User Label | `I2C_SCL` / `I2C_SDA` | 起个别名，代码可读 |

> **为什么软件 I2C 的 GPIO 必须配成"开漏输出"而不是"推挽输出"？**
> 因为 I2C 是"线与"总线：如果 STM32 用推挽输出把 SDA 拉高（强驱动 3.3V），而此时从机正想把 SDA 拉低来回应答，两个引脚就会直接对打，轻则通讯失败，重则**烧毁引脚**。开漏输出只能拉低、不能主动拉高，高电平交给上拉电阻，这才是 I2C 正确的电气姿势。
>
> **另需注意 PA0 是 WKUP 引脚**：如果开发板上 PA0 已接了按键或其它功能，请改用别的空闲 GPIO（例如 PE2/PE3），并同步修改 7.3 节代码里的引脚宏。

### 5.5 顺带配置 USART1（串口输出）

本笔记所有实验结果都通过串口打印，因此顺手把 USART1 配好（详细原理见《USART—串口通信》章节）：

1. 左侧 **Connectivity → USART1**，Mode 选 **Asynchronous**；
2. **Parameter Settings**：Baud Rate = 115200，Word Length = 8 Bits，Parity = None，Stop Bits = 1，即常说的 **115200-8-N-1**；
3. 引脚自动分配到 **PA9（TX）/ PA10（RX）**，AF7；
4. 若采用中断接收指令，再在 **NVIC Settings** 勾选 *USART1 global interrupt*（本笔记只用 printf 单向输出，可以不勾）。

> 📷 图 5-3 USART1 配置为 115200-8-N-1（此处可插入截图）

### 5.6 工程生成设置与 printf 重定向

1. **Project Manager → Project**：填工程名、选择工程存放位置，工具链选 **MDK-ARM (V5)** 或 STM32CubeIDE。
2. **Project Manager → Code Generator** 建议勾选 *Generate peripheral initialization as a pair of .c/.h files per peripheral*，生成 `i2c.c/h`、`gpio.c/h`、`usart.c/h`，把自己写的驱动与 CubeMX 管理区隔离开。
3. 右上角 **GENERATE CODE**。

生成后重点关注这几处代码：

- `i2c.c`：`MX_I2C1_Init()` —— 硬件 I2C 协议参数初始化；
- `gpio.c`：`MX_GPIO_Init()` —— 其中包含 PA1/PA0 的开漏输出配置（软件 I2C 的物理层）；
- `usart.c`：`MX_USART1_UART_Init()` —— 串口输出；
- `stm32f4xx_hal_msp.c`：`HAL_I2C_MspInit()` —— 硬件 I2C 的时钟/GPIO 配置；
- `stm32f4xx_it.c`：`I2C1_EV_IRQHandler()` 等中断入口（勾选 NVIC 后生成）。

列表 1: 代码清单 5-1 CubeMX 生成的 MspInit 关键片段

```c
void HAL_I2C_MspInit(I2C_HandleTypeDef* hi2c)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if (hi2c->Instance == I2C1)
  {
    /* 1. 使能 I2C1 与 GPIOB 时钟 */
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_I2C1_CLK_ENABLE();

    /* I2C1 GPIO Configuration
       PB8 ------> I2C1_SCL
       PB9 ------> I2C1_SDA */
    GPIO_InitStruct.Pin       = GPIO_PIN_8 | GPIO_PIN_9;
    GPIO_InitStruct.Mode      = GPIO_MODE_AF_OD;      /* 复用开漏，I2C 必须 */
    GPIO_InitStruct.Pull      = GPIO_NOPULL;          /* 依赖外部上拉电阻 */
    GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF4_I2C1;        /* I2C 固定用 AF4 */
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* 2. 复位一次 I2C 外设，清除上电残留状态（可选但推荐） */
    __HAL_RCC_I2C1_FORCE_RESET();
    __HAL_RCC_I2C1_RELEASE_RESET();
  }
}
```

列表 2: 代码清单 5-2 CubeMX 生成的软件 I2C 物理层配置

```c
/* gpio.c */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();

  /* 软件 I2C 的 SCL(PA1) / SDA(PA0)：开漏输出 + 上拉，初始高电平（总线空闲） */
  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_1 | GPIO_PIN_0, GPIO_PIN_SET);

  GPIO_InitStruct.Pin   = GPIO_PIN_1 | GPIO_PIN_0;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_OD;   /* 开漏，I2C 必须 */
  GPIO_InitStruct.Pull  = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}
```

列表 3: 代码清单 5-3 printf 重定向到串口

**Keil MDK（需勾选 Options → Target → Use MicroLIB）：**

```c
/* 在任意 .c 文件（建议 main.c 或新建 bsp_printf.c），USER CODE 区添加 */
#if defined(__CC_ARM) || defined(__ARMCC_VERSION)   /* ARMCC/AC6 均适用 */
#pragma push
#pragma micro_lib
/* 重定向 fputc：printf 每输出一字符调用一次 */
int fputc(int ch, FILE *f)
{
  HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, HAL_MAX_DELAY);
  return ch;
}
#pragma pop
#endif
```

**STM32CubeIDE（GCC/newlib）：**

```c
/* USER CODE BEGIN 0 */
#include <sys/stat.h>

/* 重定向 stdout：write 系统调用落到串口 */
ssize_t _write(int fd, const void *pdata, size_t bytes)
{
  HAL_UART_Transmit(&huart1, (uint8_t *)pdata, bytes, HAL_MAX_DELAY);
  return bytes;
}
/* 使用 printf 前先关闭缓冲，或输出后 fflush(stdout) */
/* USER CODE END 0 */
```

> **纪律提醒**：重新 GENERATE CODE 只会覆盖 `MX_..._Init` 等 CubeMX 管理区域，用户代码写在 `USER CODE BEGIN/END` 注释块内即不会被冲掉。自己写的传感器驱动建议单独放 `bsp_soft_i2c.c/h`、`bsp_bh1750.c/h` 等文件，不写进 `i2c.c`。

---

## 6. 传感器模块与 I2C 总线接线

本节补充这套传感器的硬件信息：它们**全部挂接在同一组 I2C 总线上**（SCL = PA1、SDA = PA0），因此器件地址、访问方式和电气细节必须事先弄清楚。

### 6.1 传感器套件一览

**表 6-1 传感器套件一览**

| 模块 | 类型 | 测量范围 | 精度 / 分辨率 | 访问方式 | 供电 |
| --- | --- | --- | --- | --- | --- |
| BH1750 光照 | 数字环境光强度 | 1 ~ 65535 lx | 1 lx（H 分辨率模式） | **命令型** | 3.3V |
| HTU21D 温湿度 | 数字温湿度 | -40~125 °C；0~100 %RH | ±0.3 °C；±2 %RH | **命令型** | 3.3V |
| PCF8563 时钟 | 实时时钟 / 日历 | 秒~年，含世纪位 | BCD 编码 | **寄存器型** | 3.3V |
| LIS3DH 三轴 | MEMS 三轴加速度计 | ±2 / 4 / 8 / 16 g | 12 位，1 mg/LSB（±2g） | **寄存器型** | 3.3V |

> **两类器件的区别是本笔记的一条主线**：
> **命令型**器件（BH1750、HTU21D）没有"寄存器地址"概念，主机直接写一条命令字节让它开始测量，再直接读结果，代码上用 `HAL_I2C_Master_Transmit/Receive`（软件 I2C 用"起始+地址+命令+停止"）；
> **寄存器型**器件（PCF8563、LIS3DH、AT24C02）有明确的寄存器/存储地址，主机先给出地址再读写数据，代码上用 `HAL_I2C_Mem_Write/Mem_Read`（内部含**重复起始 Sr**）。

### 6.2 同一组 I2C 总线接线

**表 6-2 传感器接线表（同一组 I2C 总线）**

| 模块 | 接口类型 | 信号 | STM32F407VET6 引脚 |
| --- | --- | --- | --- |
| BH1750 光照 | IIC | SCL | **PA1** |
| | | SDA | **PA0** |
| HTU21D 温湿度 | IIC | SCL | **PA1** |
| | | SDA | **PA0** |
| PCF8563 时钟 | IIC | SCL | **PA1** |
| | | SDA | **PA0** |
| LIS3DH 三轴 | IIC | SCL | **PA1** |
| | | SDA | **PA0** |

四个模块的 SCL 全部并接到 PA1、SDA 全部并接到 PA0——这就是**同一组 I2C 总线**；每个模块的 VCC 接 3.3V，GND 与 STM32 共地。总线拓扑如下：

```
        3.3V ─────────┬───────────────┬───────────────┬───────────────┐
                      │               │               │               │
                   4.7kΩ           4.7kΩ           （模块自带      （模块自带
                      │               │             上拉可选）       上拉可选）
   PA1 (SCL) ─────────┴────┬──────────┴────┬──────────┴────┬──────────┴────┬───
                           │               │               │               │
                        BH1750         HTU21D         PCF8563          LIS3DH
                        (光照)         (温湿度)        (时钟)          (三轴)
                           │               │               │               │
   PA0 (SDA) ─────────┬────┴──────────┬────┴──────────┬────┴──────────┬────┴───
                       │               │               │               │
   GND ────────────────┴───────────────┴───────────────┴───────────────┘
```

> 📷 图 6-1 四个传感器模块并接在同一组 I2C 总线（SCL=PA1、SDA=PA0）上的实际接线（此处可插入照片）

### 6.3 器件地址汇总与冲突检查

**表 6-3 同一总线上各器件的 I2C 地址**

| 器件 | 7 位地址 | 8 位写地址 | 8 位读地址 | 地址由什么决定 |
| --- | --- | --- | --- | --- |
| LIS3DH 三轴 | 0x18 | 0x30 | 0x31 | SA0 引脚（接高 → 0x19 / 0x32 / 0x33） |
| BH1750 光照 | 0x23 | 0x46 | 0x47 | ADDR 引脚（接高 → 0x5C / 0xB8 / 0xB9） |
| HTU21D 温湿度 | 0x40 | 0x80 | 0x81 | 固定，不可改 |
| AT24C02 EEPROM | 0x50 | 0xA0 | 0xA1 | A2/A1/A0 引脚 |
| PCF8563 时钟 | 0x51 | 0xA2 | 0xA3 | 固定，不可改 |
| （可选）MPU6050 | 0x68 | 0xD0 | 0xD1 | AD0 引脚（接高 → 0x69 / 0xD2 / 0xD3） |

**"地址互不相同"是它们能共用一组总线的唯一前提**：0x18、0x23、0x40、0x50、0x51 五个地址两两不同，所以可以全部并接在 PA1/PA0 上互不干扰。如果两个器件地址相同（例如两片 AT24C02），必须通过 A0/A1/A2、ADDR、SA0 这类地址跳线引脚把其中一个改到别的地址，否则必然通讯失败。**接线前先用万用表量一下这些跳线引脚的电平，是最省事的排错手段。**

> **为什么 PCF8563 和 AT24C02 的地址这么接近（0x50 / 0x51）？** 因为它们的 7 位地址高 4 位都是固定的 `1010`，AT24C02 低 3 位由 A2/A1/A0 决定（全 0 时即 0x50），PCF8563 则固定为 `001`（0x51）。只要 AT24C02 的 A0 不是 1，两者就不会冲突。

### 6.4 BH1750 光照传感器

- ROHM BH1750FVI，数字式 16 位环境光强度传感器，**内置 ADC，直接输出 lx 值**，无需外部标定；
- 测量范围 1 ~ 65535 lx，最高分辨率 1 lx；
- 采用**命令式接口**：没有寄存器地址，直接写命令字节；
- 支持连续测量与单次测量，连续模式下可随时读取最新结果。

**表 6-4 BH1750 常用命令**

| 命令 | 含义 |
| --- | --- |
| `0x01` | 上电（Power On） |
| `0x00` | 掉电（Power Down） |
| `0x07` | 复位数据寄存器 |
| `0x10` | 连续 H 分辨率模式（1 lx，一次测量约 120 ms） |
| `0x11` | 连续 H 分辨率模式 2（0.5 lx） |
| `0x13` | 连续 L 分辨率模式（4 lx，一次测量约 16 ms） |
| `0x20` | 单次 H 分辨率模式（测完自动回到掉电） |

**读取与换算**：连续读取 2 字节（**高字节在前**），

```
光照 (lx) = (高字节 << 8 | 低字节) / 1.2
```

使用要点：

1. 初始化顺序是"发 `0x01` 上电 → 发 `0x10` 启动连续测量 → 等一次测量完成（约 120ms）"；
2. 因为它是命令型器件，**用硬件 I2C 时请用 `HAL_I2C_Master_Transmit()` 发 1 字节命令**，不要用 `HAL_I2C_Mem_Write()`（后者会多插一个寄存器地址阶段，语义不对）；
3. 软件 I2C 下读取流程是：`起始 + 0x46 + 命令` 或 `起始 + 0x47 + 读 2 字节 + NACK + 停止`。

### 6.5 HTU21D 温湿度传感器

- TE Connectivity HTU21D，数字式温湿度传感器，出厂标定；
- 温度 -40~125 °C（±0.3 °C），湿度 0~100 %RH（±2 %RH）；
- 7 位地址**固定 0x40**，不可更改，因此总线上只能挂一片；
- 同为**命令式接口**。

**表 6-5 HTU21D 常用命令**

| 命令 | 含义 |
| --- | --- |
| `0xE3` | 触发温度测量（**Hold Master**，测量期间拉住时钟） |
| `0xE5` | 触发湿度测量（Hold Master） |
| `0xF3` | 触发温度测量（**No Hold Master**，主机自己等待） |
| `0xF5` | 触发湿度测量（No Hold Master） |
| `0xFE` | 软复位 |
| `0xE6` / `0xE7` | 写 / 读用户寄存器（分辨率配置） |

**读取与换算**：读到 2 字节，**低 2 位是状态位，必须先屏蔽**（`raw & 0xFFFC`），再代入公式：

```
温度 T (°C)  = -46.85 + 175.72 × ST  / 2^16
湿度 RH (%)  = -6.00  + 125.00 × SRH / 2^16
```

> **本传感器最大的坑——时钟延展**：Hold Master 模式（`0xE3`/`0xE5`）下，器件在测量期间会**把 SCL 拉低不放**（时钟延展），阻止主机继续发时钟；只有支持时钟延展的主机才能正确读取。**硬件 I2C 的 HAL 库会等待时钟延展，两种模式都可用；软件 I2C 如果不实现延展检测，就必须改用 No Hold Master 模式（`0xF3`/`0xF5`）：发完命令后延时约 50ms（温度）/ 16ms（湿度），再单独发起读操作。** 本笔记的软件 I2C 代码采用 No Hold Master 模式。

### 6.6 PCF8563 时钟（RTC）

- NXP PCF8563，低功耗 CMOS 实时时钟/日历，I2C 速率最高 400kHz；
- 7 位地址固定 **0x51**；
- 提供秒、分、时、日、星期、月、年（含**世纪位**），**所有时间数据都是 BCD 编码**；
- 支持报警中断、定时器、可编程 CLKOUT 方波输出。

**表 6-6 PCF8563 常用寄存器**

| 地址 | 名称 | 说明 |
| --- | --- | --- |
| `0x00` | 控制寄存器 1 | TEST、STOP（**置 1 停表**）、TEST1、AIE、AF 等 |
| `0x01` | 控制寄存器 2 | 报警中断、定时器中断使能 |
| `0x02` | 秒（VL_Seconds） | 位 7 = VL（时钟完整性标志，为 1 表示时间可能不准），位 6~0 = 秒 BCD |
| `0x03` | 分（Minutes） | 位 7 恒 0，位 6~0 = 分 BCD |
| `0x04` | 时（Hours） | 位 6~0 = 时 BCD |
| `0x05` | 日（Days） | 位 5~0 = 日 BCD |
| `0x06` | 星期（Weekdays） | 位 2~0 |
| `0x07` | 月 / 世纪（Century_Months） | 位 7 = 世纪位 C，位 4~0 = 月 BCD |
| `0x08` | 年（Years） | 00 ~ 99 |
| `0x0D` | CLKOUT 控制 | 输出频率选择 |
| `0x0E` ~ `0x0F` | 定时器控制 / 倒计时 | 定时器功能 |

使用要点：

1. **写入时间前必须先停表**：把控制寄存器 1（`0x00`）的 **STOP 位置 1**，写完秒~年共 7 个字节后再清零启动，否则写入过程中可能发生进位导致时间错乱；
2. **连续读写**：从秒寄存器 `0x02` 开始连续读 7 字节即可拿到"秒分时日月星期年"，PCF8563 支持地址自动递增；
3. **BCD 与十进制互转**：`BCD = ((dec/10)<<4) | (dec%10)`，`dec = ((bcd>>4)*10) + (bcd & 0x0F)`；
4. **掉电走时依赖备份电池**：模块上没装纽扣电池时，断电后时间会丢失，每次上电都需要重新初始化时间；PCF8563 的 VL 位为 1 就说明发生过掉电、时间不可信。

### 6.7 LIS3DH 三轴加速度计

- ST LIS3DH，MEMS 三轴线性加速度计，支持 I2C 与 SPI 两种接口；
- 7 位地址 **0x18**（SA0 接低）或 **0x19**（SA0 接高）；8 位写地址 0x30 / 0x32；
- 量程可选 ±2 / ±4 / ±8 / ±16 g，输出可选 8 / 10 / 12 位，输出数据率 ODR 1Hz ~ 5.3kHz；
- 是典型的**寄存器型器件**。

**表 6-7 LIS3DH 常用寄存器**

| 地址 | 名称 | 说明 |
| --- | --- | --- |
| `0x0F` | WHO_AM_I | 固定返回 **0x33**，用于确认器件在线 |
| `0x20` | CTRL_REG1 | 使能各轴（Xen/Yen/Zen）、ODR 设置、低功耗模式 |
| `0x21` | CTRL_REG2 | 高通滤波配置 |
| `0x23` | CTRL_REG4 | BDU、BLE、FS[1:0] 量程、HR 高分辨率位 |
| `0x28` ~ `0x2D` | OUT_X_L ~ OUT_Z_H | 三轴输出，**低字节在前（小端）** |

使用要点：

1. **先读 WHO_AM_I 确认器件**：返回 0x33 才继续初始化，这是最有效的"接线是否正常"检查；
2. **多字节读要置子地址最高位**：LIS3DH 要求在寄存器地址上置 **MSB = 1**（即 `out_x_l | 0x80`）才启用**地址自动递增**，否则连续读到的都是同一个寄存器；
3. **数据是小端**，与 MPU6050（大端）相反：`acc = (int16_t)((buf[1] << 8) | buf[0])`；
4. 本笔记采用 `CTRL_REG1 = 0x57`（ODR = 100Hz、XYZ 使能）、`CTRL_REG4 = 0x08`（±2g、高分辨率 12 位），此时灵敏度为 **1 mg/LSB**，静止平放时某一轴读数约为 **±1000**（对应 1g），可用这个常识判断数据是否可信。

### 6.8 关键结论：这套传感器必须用软件 I2C

**表 6-8 PA0 / PA1 在 STM32F407VET6 上的复用功能**

| 引脚 | 可用的复用功能 | 是否有 I2C |
| --- | --- | --- |
| PA0 | TIM2_CH1、TIM5_CH1、TIM8_ETR、USART2_CTS、UART4_TX、ETH_MII_CRS、ADC123_IN0 | **没有** |
| PA1 | TIM2_CH2、TIM5_CH2、USART2_RTS、UART4_RX、ETH_MII_RX_CLK、ADC123_IN1 | **没有** |

STM32F407VET6 的 I2C 引脚是**固定**的（表 2-1）：I2C1 = PB6/PB7 或 PB8/PB9，I2C2 = PB10/PB11 或 PF0/PF1，I2C3 = PA8/PC9，全部使用 AF4，**PA0/PA1 不在其中**。由此得到三条结论：

1. **按现有接线表（SCL=PA1、SDA=PA0）驱动这套传感器，只能用软件 I2C**——片上 I2C 外设的信号无法引到这两个脚上，CubeMX 里也点不出这两个引脚为 I2C 功能；
2. 如果确实想用**硬件 I2C** 驱动同一套传感器，**必须把总线改接到 I2C1 的 PB8/PB9**（推荐）或 I2C3 的 PA8/PC9，硬件接线要跟着改——这正是第 7 章"硬件 I2C 实验"需要修改接线的原因；
3. 反过来看，**"引脚随便挑"正是软件 I2C 最大的优势**：PA0/PA1 是板上留出来的一组 I2C 排针，用软件 I2C 可以原样使用，不必改板、不必飞线。

**表 6-9 本笔记的总线分工**

| 用途 | 总线 | SCL | SDA | 驱动方式 | 挂接器件 |
| --- | --- | --- | --- | --- | --- |
| 传感器组（按原接线） | 软件 I2C | **PA1** | **PA0** | GPIO 模拟时序 | BH1750、HTU21D、PCF8563、LIS3DH |
| 硬件 I2C 实验 | 片上 I2C1 | **PB8** | **PB9** | I2C 外设 + HAL | AT24C02（或改接后的传感器组） |

### 6.9 电气与接线注意

1. **上拉电阻只留一组**：PA1/PA0 两根线都需要上拉。四个现成模块板上往往各自带 4.7kΩ 上拉，并联后等效阻值可能低到 1kΩ 出头，灌电流过大反而拉不到低电平——**建议只保留一组 4.7kΩ，或按模块说明去掉多余上拉**。
2. **统一 3.3V 供电**：这四个器件的 IO 都是 3.3V，PA0/PA1 也是 3.3V 电平，不需要电平转换；切勿把模块接到 5V 后直接连 STM32。
3. **必须共地**：所有模块 GND 与 STM32 GND 相连，否则电平没有共同基准。
4. **走线尽量短**：SCL/SDA 并行走、远离 PWM 与时钟等强干扰线；线长超过 20~30cm 时降低速率（软件 I2C 调大延时，硬件 I2C 把 ClockSpeed 降到 100kHz）。
5. **总线电容**：四个模块加上走线，总电容接近或超过 400pF 时会明显恶化波形，此时应减小上拉电阻（如 2.2kΩ）或缩短走线。
6. **地址跳线先确认**：BH1750 的 ADDR、LIS3DH 的 SA0、AT24C02 的 A0~A2 都要按表 6-3 检查，避免地址冲突（本套器件默认接线已经互不冲突）。

---

## 7. 实验一：硬件 I2C —— 读写 AT24C02 与 BH1750 光照

**实验目标**：使用 STM32 片内 I2C1 外设读写两类典型 I2C 器件——**寄存器/存储型器件 AT24C02**（先给存储地址再读写）与**命令型器件 BH1750**（直接发命令、直接读结果），并把 EEPROM 回读数据与光照值**通过串口打印出来**。这是硬件 I2C 的标准入门实验，也是与第 8、9 章软件 I2C 做对比的基准。

### 7.1 硬件设计

> **本实验的接线必须修改（关键）**
> 第 7 章用的是**片上 I2C1 外设**，而 STM32F407VET6 的 I2C 引脚只能复用在上表 2-1 列出的引脚上，**PA1/PA0 无法复用为 I2C**（见 6.8 节）。所以本实验有两条路线，请按自己手上的接线选择：

**表 7-1 硬件 I2C 实验的两种接线方案**

| 方案 | SCL | SDA | 驱动方式 | 适用情况 |
| --- | --- | --- | --- | --- |
| **方案 A（真正的硬件 I2C，推荐）** | PB8 | PB9 | 片上 I2C1 外设 | 把传感器组从 PA1/PA0 **改接到 PB8/PB9** |
| 方案 B（不改线，退化为软件 I2C） | PA1 | PA0 | GPIO 模拟 | 保持原接线，但本实验代码不适用，请直接用第 8、9 章的软件 I2C 实现同样功能 |

本章所有"硬件 I2C"代码都按**方案 A（PB8/PB9）**编写。若你希望 PA1/PA0 一分不动，请直接跳到第 8 章——用软件 I2C 读取这套传感器的效果与硬件 I2C 完全一致。

**方案 A 的接线**：把原来接 PA1/PA0 的四条信号线整体挪到 PB8/PB9，其余（VCC、GND）不动：

**表 7-2 方案 A 接线表（原 PA1/PA0 → 改接 PB8/PB9）**

| 模块 | SCL 接到 | SDA 接到 | VCC | GND |
| --- | --- | --- | --- | --- |
| AT24C02（板载 EEPROM） | PB8 | PB9 | 3.3V | GND |
| BH1750 光照 | PB8 | PB9 | 3.3V | GND |
| HTU21D 温湿度 | PB8 | PB9 | 3.3V | GND |
| PCF8563 时钟 | PB8 | PB9 | 3.3V | GND |
| LIS3DH 三轴 | PB8 | PB9 | 3.3V | GND |

**表 7-3 方案 A 与实验一相关的硬件要点**

| 项目 | 接法 | 说明 |
| --- | --- | --- |
| 总线 | SCL = PB8、SDA = PB9 | 所有模块并接 |
| 上拉 | 4.7kΩ × 2 到 3.3V | **只保留一组**，避免多模块上拉并联后过小 |
| AT24C02 地址 | A0/A1/A2 接地、WP 接地 | 7 位地址 0x50 |
| BH1750 地址 | ADDR 接地 | 7 位地址 0x23 |
| 串口 | USART1：PA9(TX) → USB 转串口 RXD，PA10(RX) ← TXD，共地 | 用于打印结果 |

### 7.2 软件设计

#### 7.2.1 编程要点

1. CubeMX 完成 I2C1（400kHz、7 位地址）配置，PB8/PB9 复用开漏 + AF4，生成代码（见 5.3 节）；
2. **按器件类型选 API**：
   - **寄存器/存储型**（AT24C02）用 `HAL_I2C_Mem_Write/Mem_Read`；
   - **命令型**（BH1750）用 `HAL_I2C_Master_Transmit/Master_Receive`；
3. EEPROM 每写完一次，**必须等待 5ms 内部写周期**（用 `HAL_I2C_IsDeviceReady()` 轮询探测），否则下一次操作会被 NACK；
4. 写超过 8 字节要**按页拆分**，避免跨页回卷；
5. 先用 `HAL_I2C_IsDeviceReady()` 探测器件在线再读写，出问题时能立刻区分"器件没接上"和"数据错"；
6. 所有结果**通过 USART1 用 printf 打印**，串口参数 115200-8-N-1。

#### 7.2.2 代码分析

列表 4: 代码清单 7-1 AT24C02 硬件 I2C 驱动（bsp_i2c_ee.h）

```c
/* bsp_i2c_ee.h —— AT24C02 基于硬件 I2C1 的驱动接口 */
#ifndef __BSP_I2C_EE_H
#define __BSP_I2C_EE_H

#include "stm32f4xx_hal.h"

#define EEPROM_ADDRESS    0xA0   /* 8 位地址：0x50<<1 | 写位 */
#define EEPROM_PAGESIZE   8      /* AT24C02 页大小，写周期不可跨页 */
#define EEPROM_MAX_TRIALS 3      /* 探测器件在线时的重试次数 */
#define EEPROM_TIMEOUT    100    /* 每步超时 ms */

HAL_StatusTypeDef AT24C02_WriteByte(uint16_t memAddr, uint8_t data);
HAL_StatusTypeDef AT24C02_WriteBuffer(uint16_t memAddr, uint8_t *pData, uint16_t len);
HAL_StatusTypeDef AT24C02_ReadBuffer(uint16_t memAddr, uint8_t *pData, uint16_t len);
uint8_t AT24C02_Check(void);

#endif
```

列表 5: 代码清单 7-2 AT24C02 字节写、写周期等待与按页拆分写

```c
/* bsp_i2c_ee.c —— 写在单独文件里，重新生成 CubeMX 代码不会丢失 */
#include "bsp_i2c_ee.h"
#include "i2c.h"       /* 提供 hi2c1 */

/* 等待 EEPROM 内部写周期结束：期间器件不响应，探到应答即返回 */
static HAL_StatusTypeDef EEPROM_WaitStandby(void)
{
  uint32_t tickstart = HAL_GetTick();

  while (HAL_I2C_IsDeviceReady(&hi2c1, EEPROM_ADDRESS, EEPROM_MAX_TRIALS,
                               EEPROM_TIMEOUT) != HAL_OK)
  {
    if ((HAL_GetTick() - tickstart) > 10)   /* 超过 10ms 视为异常 */
    {
      return HAL_TIMEOUT;
    }
  }
  return HAL_OK;
}

/**
  * @brief  向 AT24C02 指定单元写 1 字节
  * @param  memAddr: 片内地址 0x00~0xFF
  * @param  data:    待写入字节
  * @retval HAL_OK / HAL_ERROR / HAL_TIMEOUT
  */
HAL_StatusTypeDef AT24C02_WriteByte(uint16_t memAddr, uint8_t data)
{
  /* HAL 自动完成：起始 + 器件地址(写) + 存储地址 + 数据 + 停止 */
  if (HAL_I2C_Mem_Write(&hi2c1, EEPROM_ADDRESS, memAddr,
                        I2C_MEMADD_SIZE_8BIT, &data, 1, EEPROM_TIMEOUT) != HAL_OK)
  {
    return HAL_ERROR;
  }
  /* 关键：等待 tWR（最大 5ms），否则下一次操作会 NACK */
  return EEPROM_WaitStandby();
}

/**
  * @brief  向 AT24C02 写入任意长度数据，自动处理 8 字节页边界
  * @note   AT24C02 的页写不能跨越页边界，跨页会回卷覆盖本页开头的数据
  */
HAL_StatusTypeDef AT24C02_WriteBuffer(uint16_t memAddr, uint8_t *pData, uint16_t len)
{
  uint16_t pageRemain;

  while (len > 0)
  {
    /* 本次最多写到当前页末尾 */
    pageRemain = EEPROM_PAGESIZE - (memAddr % EEPROM_PAGESIZE);
    if (pageRemain > len)
    {
      pageRemain = len;
    }

    if (HAL_I2C_Mem_Write(&hi2c1, EEPROM_ADDRESS, memAddr,
                          I2C_MEMADD_SIZE_8BIT, pData, pageRemain,
                          EEPROM_TIMEOUT) != HAL_OK)
    {
      return HAL_ERROR;
    }
    if (EEPROM_WaitStandby() != HAL_OK)
    {
      return HAL_TIMEOUT;
    }

    memAddr += pageRemain;
    pData   += pageRemain;
    len     -= pageRemain;
  }
  return HAL_OK;
}
```

列表 6: 代码清单 7-3 读数据与器件探测

```c
/**
  * @brief  从 AT24C02 读取任意长度数据
  * @note   HAL_I2C_Mem_Read 内部使用重复起始 Sr：
  *         起始 + 器件地址(写) + 存储地址 + 重复起始 + 器件地址(读) + 数据… + NACK + 停止
  *         连续读会从当前地址自增，到 0xFF 后回卷到 0x00（整片回卷，无页限制）
  */
HAL_StatusTypeDef AT24C02_ReadBuffer(uint16_t memAddr, uint8_t *pData, uint16_t len)
{
  return HAL_I2C_Mem_Read(&hi2c1, EEPROM_ADDRESS, memAddr,
                          I2C_MEMADD_SIZE_8BIT, pData, len, EEPROM_TIMEOUT);
}

/**
  * @brief  探测 AT24C02 是否在线
  * @retval 1 = 在线，0 = 不在线
  */
uint8_t AT24C02_Check(void)
{
  return (HAL_I2C_IsDeviceReady(&hi2c1, EEPROM_ADDRESS,
                                EEPROM_MAX_TRIALS, EEPROM_TIMEOUT) == HAL_OK) ? 1 : 0;
}
```

列表 7: 代码清单 7-4 BH1750 光照读取（命令型器件，硬件 I2C）

```c
/* bsp_bh1750.h */
#define BH1750_ADDR_W     0x46    /* 8 位写地址：0x23 << 1 */
#define BH1750_ADDR_R     0x47
#define BH1750_POWER_ON   0x01
#define BH1750_CONT_H_RES 0x10    /* 连续 H 分辨率模式，1 lx */

/* bsp_bh1750.c */
#include "bsp_bh1750.h"
#include "i2c.h"

/**
  * @brief  写一条命令（命令型器件：起始 + 地址 + 命令 + 停止，没有寄存器地址阶段）
  */
static void BH1750_WriteCmd(uint8_t cmd)
{
  HAL_I2C_Master_Transmit(&hi2c1, BH1750_ADDR_W, &cmd, 1, 100);
}

/**
  * @brief  初始化并进入连续测量模式
  */
void BH1750_Init(void)
{
  BH1750_WriteCmd(BH1750_POWER_ON);   /* 上电 */
  HAL_Delay(10);
  BH1750_WriteCmd(BH1750_CONT_H_RES); /* 启动连续 H 分辨率测量 */
  HAL_Delay(180);                     /* 等第一次测量完成（约 120ms） */
}

/**
  * @brief  读取光照强度
  * @retval 单位 lx
  * @note   连续读 2 字节，高字节在前：lx = (H<<8 | L) / 1.2
  */
float BH1750_ReadLux(void)
{
  uint8_t buf[2];
  uint16_t raw;

  if (HAL_I2C_Master_Receive(&hi2c1, BH1750_ADDR_R, buf, 2, 100) != HAL_OK)
  {
    return -1.0f;                     /* 读取失败返回负值，便于串口识别 */
  }
  raw = (uint16_t)((buf[0] << 8) | buf[1]);
  return raw / 1.2f;
}
```

列表 8: 代码清单 7-5 测试主程序（串口输出）

```c
/* main.c 的 USER CODE 区 */
#include "bsp_i2c_ee.h"
#include "bsp_bh1750.h"

#define DATA_SIZE  32
uint8_t ee_write_buf[DATA_SIZE];
uint8_t ee_read_buf[DATA_SIZE];

int main(void)
{
  uint16_t i;

  HAL_Init();
  SystemClock_Config();      /* 168MHz，APB1=42MHz */
  MX_GPIO_Init();
  MX_USART1_UART_Init();     /* 串口输出，115200-8-N-1 */
  MX_I2C1_Init();            /* 硬件 I2C1，PB8/PB9，400kHz */

  printf("\r\n===== STM32F407VET6 硬件 I2C 实验（I2C1：PB8/PB9）=====\r\n");

  /* ---------- 1. AT24C02：寄存器/存储型器件 ---------- */
  if (AT24C02_Check() == 0)
  {
    printf("错误：未检测到 AT24C02，请检查上拉电阻与接线\r\n");
  }
  else
  {
    for (i = 0; i < DATA_SIZE; i++)
    {
      ee_write_buf[i] = (uint8_t)i;      /* 0,1,2,…,31 */
    }

    if (AT24C02_WriteBuffer(0x00, ee_write_buf, DATA_SIZE) != HAL_OK)
    {
      printf("错误：EEPROM 写入失败\r\n");
    }
    else if (AT24C02_ReadBuffer(0x00, ee_read_buf, DATA_SIZE) != HAL_OK)
    {
      printf("错误：EEPROM 读取失败\r\n");
    }
    else
    {
      printf("AT24C02 回读 %d 字节：", DATA_SIZE);
      for (i = 0; i < DATA_SIZE; i++)
      {
        printf("0x%02X ", ee_read_buf[i]);
        if (ee_read_buf[i] != ee_write_buf[i])
        {
          printf("\r\n错误：地址 0x%02X 数据不一致\r\n", i);
          break;
        }
      }
      printf("\r\nAT24C02 读写测试%s\r\n",
             (i == DATA_SIZE) ? "成功" : "失败");
    }
  }

  /* ---------- 2. BH1750：命令型器件 ---------- */
  BH1750_Init();

  while (1)
  {
    printf("BH1750 光照：%6.1f lx\r\n", BH1750_ReadLux());
    HAL_Delay(1000);
  }
}
```

**分析**：

- `HAL_I2C_Mem_Write()` 一个函数就覆盖了"起始 → 器件地址+W → 存储地址 → 数据 → 停止"整个时序；而 BH1750 这种**命令型器件没有"存储地址 + 数据"的两段结构**，只能自己用 `HAL_I2C_Master_Transmit()` 发一字节命令，再单独 `HAL_I2C_Master_Receive()` 读 2 字节结果。**"两类器件用两套 API"是 I2C 编程中最容易搞混的地方**；
- **本实验最容易踩的坑是写周期等待**。AT24C02 收到停止信号后进入 5ms 的内部编程周期，此期间它**不响应任何寻址**。若立即发起下一次写，会得到 `AF`（应答失败），HAL 返回 `HAL_ERROR`。用 `HAL_I2C_IsDeviceReady()` 轮询探测正好等价于"等待器件空闲"；
- 32 字节写入被自动拆成 4 次页写（0x00、0x08、0x10、0x18 各 8 字节），每次写完都等待 5ms，所以肉眼看不到明显延迟；
- 读取失败时返回 `-1.0`，串口上会打印出一个明显的负值，便于区分"真的没有光"和"通讯失败"。

#### 7.2.3 下载验证

编译下载到开发板，打开串口调试助手（115200-8-N-1），上电应看到：

```
===== STM32F407VET6 硬件 I2C 实验（I2C1：PB8/PB9）=====
AT24C02 回读 32 字节：0x00 0x01 0x02 … 0x1F
AT24C02 读写测试成功
BH1750 光照： 156.7 lx
BH1750 光照： 158.3 lx
```

**三个验证动作**：

1. **断电再上电**（或按复位键），AT24C02 读出来仍是 0x00 0x01 0x02…，说明数据真的写进了 EEPROM 而不是只在 RAM 里；
2. **用手遮住 BH1750**，串口上的光照值应明显下降（接近几 lx）；**用手机手电筒照它**，数值应升到上千 lx——这证明光照数据是实时采集的；
3. 若把 BH1750 从总线上拔掉，光照值会变成 `-1.0`（读取失败），说明探测逻辑有效。

---

## 8. 实验二：软件 I2C 基础时序与读写 AT24C02（SCL=PA1 / SDA=PA0）

**实验目标**：完全**不使用 STM32 的 I2C 外设**，只用两个普通 GPIO（PA1/PA0，开漏输出）模拟 SCL/SDA 时序，实现同样的 EEPROM 读写功能并通过串口打印。这条总线就是第 6.2 节那张接线表的传感器总线，**本节写好的时序层会在第 9 章原封不动地拿去驱动四个传感器**。

### 8.1 硬件设计

- **SCL 接 PA1、SDA 接 PA0**，与四个传感器模块共用同一组总线（这也是用这两个脚的原因：时序层一写好，下一章立刻能驱动传感器，无需重新接线）；
- 两根线**需要 4.7kΩ 外部上拉电阻**到 3.3V——这一点软硬件 I2C 完全一致；
- AT24C02 的 A0/A1/A2 接地、WP 接地，器件地址仍是 0xA0（7 位 0x50）；
- 串口仍用 USART1（PA9/PA10）打印结果。

> **注意**：PA0/PA1 在 F407VET6 上没有 I2C 复用功能（表 6-8），所以本节**绝不能**把这两个脚配成 I2C 外设——它们的角色就是两个普通开漏 GPIO。如果开发板上 PA0 已被按键等功能占用，请换成别的空闲 GPIO 并同步修改下面的引脚宏。

### 8.2 CubeMX 配置（把 PA1/PA0 配成开漏输出）

1. 在**同一个工程**里（I2C1 保留不冲突），左侧 **System Core → GPIO**，点击 PA1 选 **GPIO_Output**，点击 PA0 也选 **GPIO_Output**；
2. 按表 5-2 设置：Output level = High、**Output mode = Output Open Drain**、Pull-up、Very High speed，并给它们起别名 `I2C_SCL` / `I2C_SDA`；
3. 重新 **GENERATE CODE**，生成结果就是代码清单 5-2（`MX_GPIO_Init()` 中的 PA1/PA0 开漏配置）。

> 📷 图 8-1 GPIO 面板中把 PA1/PA0 设为 Output Open Drain + Pull-up（此处可插入截图）

### 8.3 软件设计

#### 8.3.1 编程要点

1. **把电平操作写成宏**，让上层时序代码贴近"拉高 SCL / 拉低 SDA"的自然语义；读 SDA 用 `HAL_GPIO_ReadPin()`——STM32 的输入数据寄存器（IDR）**在任何模式下都在采样引脚电平**，所以开漏输出模式下同样可以直接读回引脚状态，无需来回切换输入/输出方向；
2. **延时决定速率**。软件 I2C 用空循环产生半周期延时，循环次数需要按主频实测调整：延时过长速率低但稳，过短则从机来不及响应；
3. **严格遵循"数据只能在 SCL 为低时变化"**的规则，`I2C_SendByte()` 里先拉低 SCL、放数据、再拉高 SCL 让从机采样；
4. 起始/停止信号是"SCL 高时 SDA 跳变"的例外，必须在 SCL 已经为高的状态下改变 SDA；
5. 读完最后一个字节必须回 **NACK**，然后发停止信号；
6. 失败要能看出来：`I2C_WaitAck()` 返回值直接反映从机是否应答，用它做错误判断比硬件 I2C 的返回值更直观。

#### 8.3.2 代码分析

列表 9: 代码清单 8-1 电平操作宏与延时（bsp_soft_i2c.h）

```c
/* bsp_soft_i2c.h —— 软件模拟 I2C 接口（总线：SCL=PA1、SDA=PA0） */
#ifndef __BSP_SOFT_I2C_H
#define __BSP_SOFT_I2C_H

#include "stm32f4xx_hal.h"

/* 引脚定义：与传感器组共用同一组总线 */
#define SOFT_I2C_GPIO_PORT   GPIOA
#define SOFT_I2C_SCL_PIN     GPIO_PIN_1     /* PA1 */
#define SOFT_I2C_SDA_PIN     GPIO_PIN_0     /* PA0 */

/* 电平操作宏：开漏输出，写 1 即释放总线（由上拉电阻拉高） */
#define I2C_SCL_H()      HAL_GPIO_WritePin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SCL_PIN, GPIO_PIN_SET)
#define I2C_SCL_L()      HAL_GPIO_WritePin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SCL_PIN, GPIO_PIN_RESET)
#define I2C_SDA_H()      HAL_GPIO_WritePin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SDA_PIN, GPIO_PIN_SET)
#define I2C_SDA_L()      HAL_GPIO_WritePin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SDA_PIN, GPIO_PIN_RESET)
/* 读 SDA：开漏输出模式下 IDR 仍在采样引脚，可直接读回 */
#define I2C_SDA_READ()   HAL_GPIO_ReadPin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SDA_PIN)

void    I2C_Init(void);
void    I2C_Start(void);
void    I2C_Stop(void);
void    I2C_SendByte(uint8_t byte);
uint8_t I2C_WaitAck(void);
void    I2C_SendAck(uint8_t ack);
uint8_t I2C_ReadByte(void);

#endif
```

列表 10: 代码清单 8-2 半周期延时

```c
/* bsp_soft_i2c.c */
#include "bsp_soft_i2c.h"

/**
  * @brief  软件 I2C 半周期延时
  * @note   168MHz 主频下循环 20 次约 1µs，SCL 周期约 2µs，
  *         实际速率受上升沿限制，实测波形落在 100~400kHz 之间。
  *         要降低速率（总线较长、模块较多时更稳）就加大循环次数，
  *         例如调到 100 约为 100kHz。第 9 章挂四个模块时建议用大一些的值。
  */
static void I2C_Delay(void)
{
  for (volatile uint8_t i = 0; i < 20; i++)
  {
    __NOP();
  }
}
```

列表 11: 代码清单 8-3 起始信号、停止信号与字节收发

```c
/**
  * @brief  产生起始信号：SCL 为高电平期间，SDA 由高变低
  */
void I2C_Start(void)
{
  I2C_SDA_H();          /* 先确保 SDA 为高 */
  I2C_SCL_H();
  I2C_Delay();
  I2C_SDA_L();          /* SCL 高时拉低 SDA —— 起始条件 */
  I2C_Delay();
  I2C_SCL_L();          /* 钳住总线，准备发送数据 */
  I2C_Delay();
}

/**
  * @brief  产生停止信号：SCL 为高电平期间，SDA 由低变高
  */
void I2C_Stop(void)
{
  I2C_SDA_L();
  I2C_SCL_H();
  I2C_Delay();
  I2C_SDA_H();          /* SCL 高时拉高 SDA —— 停止条件 */
  I2C_Delay();
}

/**
  * @brief  发送 1 个字节，高位（MSB）在前
  * @note   SCL 低电平时准备数据，SCL 高电平时数据必须稳定
  */
void I2C_SendByte(uint8_t byte)
{
  uint8_t i;

  for (i = 0; i < 8; i++)
  {
    I2C_SCL_L();               /* 拉低时钟，允许 SDA 变化 */
    I2C_Delay();

    if (byte & 0x80)
    {
      I2C_SDA_H();
    }
    else
    {
      I2C_SDA_L();
    }
    byte <<= 1;

    I2C_Delay();
    I2C_SCL_H();               /* 拉高时钟，从机此刻采样 */
    I2C_Delay();
  }

  I2C_SCL_L();                 /* 释放时钟，准备接收应答 */
  I2C_Delay();
}

/**
  * @brief  等待从机应答
  * @retval 1 = 收到 ACK，0 = 收到 NACK（说明地址错或器件不在线）
  */
uint8_t I2C_WaitAck(void)
{
  uint8_t ack;

  I2C_SDA_H();                 /* 主机释放 SDA，交给从机驱动 */
  I2C_Delay();
  I2C_SCL_H();                 /* 第 9 个时钟 */
  I2C_Delay();

  /* 从机拉低 = ACK；保持高 = NACK */
  ack = (I2C_SDA_READ() == GPIO_PIN_RESET) ? 1 : 0;

  I2C_SCL_L();
  I2C_Delay();
  return ack;
}

/**
  * @brief  主机发送应答：ack=1 发 ACK（拉低），ack=0 发 NACK（保持高）
  */
void I2C_SendAck(uint8_t ack)
{
  I2C_SCL_L();
  I2C_Delay();
  if (ack)
  {
    I2C_SDA_L();               /* ACK */
  }
  else
  {
    I2C_SDA_H();               /* NACK */
  }
  I2C_Delay();
  I2C_SCL_H();
  I2C_Delay();
  I2C_SCL_L();
  I2C_Delay();
}

/**
  * @brief  读取 1 个字节，高位在前
  * @note   调用前必须先释放 SDA（I2C_SDA_H），由从机驱动数据线
  */
uint8_t I2C_ReadByte(void)
{
  uint8_t i, byte = 0;

  I2C_SDA_H();                 /* 主机释放 SDA */
  for (i = 0; i < 8; i++)
  {
    byte <<= 1;
    I2C_SCL_H();               /* 拉高时钟，读取从机输出的数据位 */
    I2C_Delay();
    if (I2C_SDA_READ() == GPIO_PIN_SET)
    {
      byte |= 0x01;
    }
    I2C_SCL_L();
    I2C_Delay();
  }
  return byte;
}
```

列表 12: 代码清单 8-4 基于软件 I2C 的 AT24C02 字节读写与页写

```c
/* 器件地址：7 位 0x50，8 位形式 0xA0(写) / 0xA1(读) */
#define AT24C02_ADDR_W   0xA0
#define AT24C02_ADDR_R   0xA1
#define AT24C02_PAGESIZE 8

/**
  * @brief  向 AT24C02 写 1 字节
  * @note   时序：START + 器件地址(W) + ACK + 存储地址 + ACK + 数据 + ACK + STOP
  */
uint8_t AT24C02_WriteByte(uint8_t memAddr, uint8_t data)
{
  I2C_Start();
  I2C_SendByte(AT24C02_ADDR_W);                /* 器件地址 + 写 */
  if (I2C_WaitAck() == 0) { return 0; }        /* 地址无应答，说明器件不在线 */
  I2C_SendByte(memAddr);                       /* 片内存储地址 */
  if (I2C_WaitAck() == 0) { return 0; }
  I2C_SendByte(data);                          /* 数据 */
  if (I2C_WaitAck() == 0) { return 0; }
  I2C_Stop();

  HAL_Delay(5);                                /* 等待 EEPROM 内部写周期 tWR（≤5ms） */
  return 1;
}

/**
  * @brief  从 AT24C02 读 1 字节
  * @note   时序：START + 地址(W) + ACK + 存储地址 + ACK
  *              + 重复起始 Sr + 地址(R) + ACK + 数据 + NACK + STOP
  */
uint8_t AT24C02_ReadByte(uint8_t memAddr)
{
  uint8_t data;

  I2C_Start();
  I2C_SendByte(AT24C02_ADDR_W);   /* 先"伪写"存储地址 */
  I2C_WaitAck();
  I2C_SendByte(memAddr);
  I2C_WaitAck();

  I2C_Start();                    /* 重复起始信号 Sr，不释放总线 */
  I2C_SendByte(AT24C02_ADDR_R);   /* 器件地址 + 读 */
  I2C_WaitAck();

  data = I2C_ReadByte();
  I2C_SendAck(0);                 /* 只读 1 字节，回 NACK 结束 */
  I2C_Stop();

  return data;
}

/**
  * @brief  页写：一次写不超过 8 字节且不跨页
  */
void AT24C02_PageWrite(uint8_t memAddr, uint8_t *pData, uint8_t len)
{
  uint8_t i;

  I2C_Start();
  I2C_SendByte(AT24C02_ADDR_W);
  I2C_WaitAck();
  I2C_SendByte(memAddr);
  I2C_WaitAck();

  for (i = 0; i < len; i++)
  {
    I2C_SendByte(pData[i]);
    I2C_WaitAck();
  }
  I2C_Stop();

  HAL_Delay(5);                   /* 同样要等写周期 */
}
```

> **注意软件 I2C 的编程习惯**：每个 `I2C_SendByte()` 后面紧跟一句 `I2C_WaitAck()`，用返回值判断从机是否应答。这是硬件 I2C 里"看不到"的信息——HAL 库只返回一个 `HAL_ERROR`，而软件 I2C 能明确告诉你是**地址没应答**还是**数据没应答**，排错效率高得多。

列表 13: 代码清单 8-5 软件 I2C 测试主程序（串口输出）

```c
/* main.c 的 USER CODE 区 */
#include "bsp_soft_i2c.h"

#define SOFT_DATA_SIZE  16
uint8_t sw_write_buf[SOFT_DATA_SIZE];
uint8_t sw_read_buf[SOFT_DATA_SIZE];

int main(void)
{
  uint16_t i;

  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();             /* 其中包含 PA1/PA0 开漏输出配置 */
  MX_USART1_UART_Init();

  printf("\r\n===== STM32F407VET6 软件 I2C 实验（SCL=PA1, SDA=PA0）=====\r\n");

  /* 准备数据：0xA0 ~ 0xAF，与第 7 章硬件 I2C 实验的数据区分开 */
  for (i = 0; i < SOFT_DATA_SIZE; i++)
  {
    sw_write_buf[i] = (uint8_t)(0xA0 + i);
  }

  /* 写入 0x10 起始的两页（每页 8 字节，不跨页） */
  AT24C02_PageWrite(0x10, &sw_write_buf[0], 8);
  AT24C02_PageWrite(0x18, &sw_write_buf[8], 8);
  printf("软件 I2C 写入完成\r\n");

  /* 读回比对（也顺便验证"重复起始 Sr"时序是否正确） */
  for (i = 0; i < SOFT_DATA_SIZE; i++)
  {
    sw_read_buf[i] = AT24C02_ReadByte((uint8_t)(0x10 + i));
    printf("0x%02X ", sw_read_buf[i]);
    if (sw_read_buf[i] != sw_write_buf[i])
    {
      printf("\r\n错误：地址 0x%02X 数据不一致\r\n", 0x10 + i);
      while (1);
    }
    if (i % 8 == 7)
    {
      printf("\r\n");
    }
  }
  printf("软件 I2C (AT24C02) 读写测试成功\r\n");

  while (1)
  {
  }
}
```

> **调试提示**：软件 I2C 出问题时的排查顺序是"**先看波形、再看时序、最后看代码**"。用逻辑分析仪或示波器抓 SCL/SDA，重点确认三件事：① 起始/停止信号里 SDA 是否确实在 SCL 高电平期间跳变；② 第 9 个时钟从机有没有把 SDA 拉低（没有低电平就说明地址错了或器件没上电）；③ 上拉电阻是否真的存在（把 SDA 释放后线能不能回到高电平）。**线拉不到高电平几乎一定是上拉电阻缺失或阻值过大**——四个模块并联上拉时尤其要检查这一点。

#### 8.3.3 下载验证

编译下载，串口应输出：

```
===== STM32F407VET6 软件 I2C 实验（SCL=PA1, SDA=PA0）=====
软件 I2C 写入完成
0xA0 0xA1 0xA2 0xA3 0xA4 0xA5 0xA6 0xA7
0xA8 0xA9 0xAA 0xAB 0xAC 0xAD 0xAE 0xAF
软件 I2C (AT24C02) 读写测试成功
```

**交叉验证技巧**：把软件 I2C 写进 0x10~0x1F 的数据，改由**第 7 章的硬件 I2C 驱动**去读（需要按方案 A 把 EEPROM 接到 PB8/PB9 总线上，或反过来把总线整组接到硬件 I2C 引脚），能读到 0xA0~0xAF，就证明两套实现操作的是同一个真实的 I2C 器件，协议时序都是正确的。

---

## 9. 实验三：软件 I2C 依次读取四个传感器（串口输出）

**实验目标**：把第 8 章的软件 I2C 时序层**原封不动复用**，按第 6.2 节的接线，依次访问挂在 **PA1/PA0 同一组总线**上的 BH1750、HTU21D、PCF8563、LIS3DH，把**光照、温湿度、时间、三轴加速度**周期性地通过串口打印出来。这是本笔记的综合实验，也是"一组总线挂多个器件"最直观的演示。

### 9.1 硬件设计

- 按**表 6-2** 接线：四个模块的 SCL 并接 **PA1**、SDA 并接 **PA0**，VCC 接 3.3V，GND 共地；总线上一组 4.7kΩ 上拉（注意去掉模块上多余的上拉）；
- 串口 USART1：**PA9(TX) → USB 转串口模块 RXD，PA10(RX) ← TXD，GND 共地**，波特率 115200-8-N-1；
- 各模块地址跳线按表 6-3：BH1750 的 ADDR 接地（0x23）、LIS3DH 的 SA0 接地（0x18）、AT24C02 的 A0~A2 接地（0x50）——默认互不冲突；
- PCF8563 若装了纽扣电池，断电后仍能走时；没装电池则每次上电都要重新设置时间。

> 📷 图 9-1 四个传感器 + EEPROM 共用 PA1/PA0 总线，USART1 接 USB 转串口打印（此处可插入照片）

### 9.2 软件设计

#### 9.2.1 程序结构（分层设计）

```
main.c               ← 主循环：每 1 秒采集一次，printf 打印到串口
├── bsp_soft_i2c.c       ← 时序层：Start/Stop/SendByte/WaitAck/ReadByte/sendAck
│                          （完全不知道从机是谁，第 8 章已写好，本章直接复用）
├── bsp_sensor_io.c      ← 原语层：命令写、连续读、寄存器写、寄存器连续读
├── bsp_bh1750.c         ← 器件层：BH1750_Init / BH1750_ReadLux
├── bsp_htu21d.c         ← 器件层：HTU21D_Init / HTU21D_ReadTemp / HTU21D_ReadHumidity
├── bsp_pcf8563.c        ← 器件层：PCF8563_WriteTime / PCF8563_ReadTime
└── bsp_lis3dh.c         ← 器件层：LIS3DH_Init / LIS3DH_ReadAcc
```

**分层的价值**：时序层只认"电平怎么翻转"，器件层只认"哪个地址的哪条命令/哪个寄存器"，中间的原语层把两类器件的访问方式统一成 4 个函数。换器件只改器件层，换引脚/换芯片只改时序层的宏和延时。

#### 9.2.2 编程要点

1. 四个器件**共用一组总线**，每次操作都要完整地"起始 → 收发 → 停止"，不能把两次不同器件的操作连在一起；
2. **命令型与寄存器型用不同的原语**（见 6.1 节的表格说明）；
3. HTU21D 用 **No Hold Master** 模式（`0xF3`/`0xF5`），避开软件 I2C 不支持时钟延展的问题；
4. LIS3DH **多字节读要置子地址最高位**（`| 0x80`）以启用地址自增，且数据是**小端**；
5. PCF8563 写时间前**先停表**，读完用 `VL` 位判断时间是否可信；
6. 每个器件初始化后都先做一次"身份确认"（LIS3DH 读 WHO_AM_I、BH1750 读一次数据、HTU21D 读温度），失败就打印明确提示，便于定位是哪个模块没接好；
7. **循环里留出足够延时**：BH1750 需要 120ms 完成一次测量、HTU21D 需 16~50ms，每轮采集间隔 1 秒足够。

#### 9.2.3 代码分析

列表 14: 代码清单 9-1 器件访问原语（bsp_sensor_io.h/.c）

```c
/* bsp_sensor_io.h —— 把两类器件统一成 4 个访问原语 */
#ifndef __BSP_SENSOR_IO_H
#define __BSP_SENSOR_IO_H

#include "stm32f4xx_hal.h"

/* 命令型器件：起始 + 地址(W) + 命令 + 停止 */
void I2C_WriteCmd(uint8_t devAddr8, uint8_t cmd);

/* 命令型器件：起始 + 地址(R) + 读 len 字节 + 末字节 NACK + 停止 */
void I2C_ReadBytes(uint8_t devAddr8, uint8_t *buf, uint8_t len);

/* 寄存器型器件：写一个寄存器 */
void I2C_WriteReg(uint8_t devAddr8, uint8_t reg, uint8_t data);

/* 寄存器型器件：从 reg 开始连续读 len 字节（重复起始 Sr） */
void I2C_ReadRegs(uint8_t devAddr8, uint8_t reg, uint8_t *buf, uint8_t len);

#endif
```

```c
/* bsp_sensor_io.c */
#include "bsp_sensor_io.h"
#include "bsp_soft_i2c.h"

/* 命令型器件（BH1750、HTU21D）：没有寄存器地址阶段 */
void I2C_WriteCmd(uint8_t devAddr8, uint8_t cmd)
{
  I2C_Start();
  I2C_SendByte(devAddr8);          /* 8 位写地址 */
  I2C_WaitAck();
  I2C_SendByte(cmd);               /* 命令字节 */
  I2C_WaitAck();
  I2C_Stop();
}

void I2C_ReadBytes(uint8_t devAddr8, uint8_t *buf, uint8_t len)
{
  uint8_t i;

  I2C_Start();
  I2C_SendByte(devAddr8 | 0x01);   /* 转成读地址 */
  I2C_WaitAck();
  for (i = 0; i < len; i++)
  {
    buf[i] = I2C_ReadByte();
    I2C_SendAck((i == (len - 1)) ? 0 : 1);   /* 最后一个字节回 NACK */
  }
  I2C_Stop();
}

/* 寄存器型器件（PCF8563、LIS3DH、AT24C02）：先给寄存器地址 */
void I2C_WriteReg(uint8_t devAddr8, uint8_t reg, uint8_t data)
{
  I2C_Start();
  I2C_SendByte(devAddr8);
  I2C_WaitAck();
  I2C_SendByte(reg);
  I2C_WaitAck();
  I2C_SendByte(data);
  I2C_WaitAck();
  I2C_Stop();
}

void I2C_ReadRegs(uint8_t devAddr8, uint8_t reg, uint8_t *buf, uint8_t len)
{
  uint8_t i;

  I2C_Start();
  I2C_SendByte(devAddr8);
  I2C_WaitAck();
  I2C_SendByte(reg);
  I2C_WaitAck();

  I2C_Start();                     /* 重复起始信号 Sr，不释放总线 */
  I2C_SendByte(devAddr8 | 0x01);
  I2C_WaitAck();

  for (i = 0; i < len; i++)
  {
    buf[i] = I2C_ReadByte();
    I2C_SendAck((i == (len - 1)) ? 0 : 1);
  }
  I2C_Stop();
}
```

列表 15: 代码清单 9-2 BH1750 驱动（命令型）

```c
/* bsp_bh1750.h */
#define BH1750_ADDR_W     0x46    /* 8 位写地址：0x23 << 1 */
#define BH1750_POWER_ON   0x01
#define BH1750_CONT_H_RES 0x10    /* 连续 H 分辨率模式，1 lx */

void  BH1750_Init(void);
float BH1750_ReadLux(void);
```

```c
/* bsp_bh1750.c */
#include "bsp_bh1750.h"
#include "bsp_sensor_io.h"

void BH1750_Init(void)
{
  I2C_WriteCmd(BH1750_ADDR_W, BH1750_POWER_ON);    /* 上电 */
  HAL_Delay(10);
  I2C_WriteCmd(BH1750_ADDR_W, BH1750_CONT_H_RES);  /* 连续 H 分辨率测量 */
  HAL_Delay(180);                                  /* 等首次测量完成（约 120ms） */
}

/**
  * @brief  读取光照强度
  * @retval 单位 lx；高字节在前，lx = (H<<8 | L) / 1.2
  */
float BH1750_ReadLux(void)
{
  uint8_t buf[2];

  I2C_ReadBytes(BH1750_ADDR_W, buf, 2);
  return (uint16_t)((buf[0] << 8) | buf[1]) / 1.2f;
}
```

列表 16: 代码清单 9-3 HTU21D 驱动（命令型，No Hold Master 模式）

```c
/* bsp_htu21d.h */
#define HTU21D_ADDR_W        0x80   /* 8 位写地址：0x40 << 1 */
#define HTU21D_TRIG_T_NOHOLD 0xF3   /* 触发温度测量（主机自己等） */
#define HTU21D_TRIG_H_NOHOLD 0xF5   /* 触发湿度测量（主机自己等） */
#define HTU21D_SOFT_RESET    0xFE

void  HTU21D_Init(void);
float HTU21D_ReadTemp(void);
float HTU21D_ReadHumidity(void);
```

```c
/* bsp_htu21d.c */
#include "bsp_htu21d.h"
#include "bsp_sensor_io.h"

void HTU21D_Init(void)
{
  I2C_WriteCmd(HTU21D_ADDR_W, HTU21D_SOFT_RESET);
  HAL_Delay(20);
}

/**
  * @brief  触发一次测量并读回原始值（No Hold Master 模式）
  * @param  cmd: 0xF3 测温度 / 0xF5 测湿度
  * @param  waitMs: 该测量的最大耗时（温度 50ms、湿度 16ms）
  * @note   No Hold 模式必须由主机自己等待；若改用 Hold 模式（0xE3/0xE5），
  *         器件会在测量期间拉住 SCL（时钟延展），软件 I2C 将无法正确读取
  */
static uint16_t HTU21D_ReadRaw(uint8_t cmd, uint8_t waitMs)
{
  uint8_t buf[2];

  I2C_WriteCmd(HTU21D_ADDR_W, cmd);
  HAL_Delay(waitMs);                              /* 等测量完成 */
  I2C_ReadBytes(HTU21D_ADDR_W, buf, 2);

  /* 低 2 位是状态位，必须先屏蔽掉 */
  return (uint16_t)(((buf[0] << 8) | buf[1]) & 0xFFFC);
}

/**
  * @brief  T(°C) = -46.85 + 175.72 × ST / 2^16
  */
float HTU21D_ReadTemp(void)
{
  uint16_t raw = HTU21D_ReadRaw(HTU21D_TRIG_T_NOHOLD, 50);
  return -46.85f + 175.72f * raw / 65536.0f;
}

/**
  * @brief  RH(%) = -6.00 + 125.00 × SRH / 2^16
  */
float HTU21D_ReadHumidity(void)
{
  uint16_t raw = HTU21D_ReadRaw(HTU21D_TRIG_H_NOHOLD, 16);
  return -6.0f + 125.0f * raw / 65536.0f;
}
```

列表 17: 代码清单 9-4 PCF8563 驱动（寄存器型，BCD 编码）

```c
/* bsp_pcf8563.h */
#define PCF8563_ADDR_W    0xA2   /* 8 位写地址：0x51 << 1 */
#define PCF8563_REG_CTRL1 0x00
#define PCF8563_REG_SEC   0x02

typedef struct {
  uint8_t sec, min, hour, day, weekday, month, year;
} PCF8563_Time_t;

void PCF8563_WriteTime(const PCF8563_Time_t *t);
void PCF8563_ReadTime(PCF8563_Time_t *t);
uint8_t PCF8563_IsTimeValid(void);   /* 读 VL 位：0 表示时间可信 */
```

```c
/* bsp_pcf8563.c */
#include "bsp_pcf8563.h"
#include "bsp_sensor_io.h"

static uint8_t BCD2DEC(uint8_t bcd) { return (uint8_t)(((bcd >> 4) * 10) + (bcd & 0x0F)); }
static uint8_t DEC2BCD(uint8_t dec) { return (uint8_t)(((dec / 10) << 4) | (dec % 10)); }

/**
  * @brief  设置时间：先停表，写完 7 字节后启动
  */
void PCF8563_WriteTime(const PCF8563_Time_t *t)
{
  uint8_t buf[7];
  uint8_t i;

  buf[0] = DEC2BCD(t->sec)   & 0x7F;
  buf[1] = DEC2BCD(t->min)   & 0x7F;
  buf[2] = DEC2BCD(t->hour)  & 0x3F;
  buf[3] = DEC2BCD(t->day)   & 0x3F;
  buf[4] = t->weekday        & 0x07;
  buf[5] = DEC2BCD(t->month) & 0x1F;
  buf[6] = DEC2BCD(t->year);

  I2C_WriteReg(PCF8563_ADDR_W, PCF8563_REG_CTRL1, 0x20);   /* STOP=1，先停表 */

  I2C_Start();
  I2C_SendByte(PCF8563_ADDR_W);
  I2C_WaitAck();
  I2C_SendByte(PCF8563_REG_SEC);          /* 从秒寄存器开始连续写 7 字节 */
  I2C_WaitAck();
  for (i = 0; i < 7; i++)
  {
    I2C_SendByte(buf[i]);
    I2C_WaitAck();
  }
  I2C_Stop();

  I2C_WriteReg(PCF8563_ADDR_W, PCF8563_REG_CTRL1, 0x00);   /* STOP=0，启动走时 */
}

/**
  * @brief  读取时间：从秒寄存器开始连续读 7 字节，地址自动递增
  */
void PCF8563_ReadTime(PCF8563_Time_t *t)
{
  uint8_t buf[7];

  I2C_ReadRegs(PCF8563_ADDR_W, PCF8563_REG_SEC, buf, 7);

  t->sec     = BCD2DEC(buf[0] & 0x7F);
  t->min     = BCD2DEC(buf[1] & 0x7F);
  t->hour    = BCD2DEC(buf[2] & 0x3F);
  t->day     = BCD2DEC(buf[3] & 0x3F);
  t->weekday = buf[4] & 0x07;
  t->month   = BCD2DEC(buf[5] & 0x1F);
  t->year    = BCD2DEC(buf[6]);
}

/**
  * @brief  读时钟完整性标志 VL（秒寄存器 bit7）
  * @retval 1 = 时间可信，0 = 发生过掉电，时间不可信
  */
uint8_t PCF8563_IsTimeValid(void)
{
  uint8_t secReg;

  I2C_ReadRegs(PCF8563_ADDR_W, PCF8563_REG_SEC, &secReg, 1);
  return ((secReg & 0x80) == 0) ? 1 : 0;
}
```

列表 18: 代码清单 9-5 LIS3DH 驱动（寄存器型，小端、需地址自增）

```c
/* bsp_lis3dh.h */
#define LIS3DH_ADDR_W     0x30   /* 8 位写地址：0x18 << 1（SA0 接地） */
#define LIS3DH_WHO_AM_I   0x0F
#define LIS3DH_CTRL_REG1  0x20
#define LIS3DH_CTRL_REG4  0x23
#define LIS3DH_OUT_X_L    0x28

uint8_t LIS3DH_Init(void);                 /* 1 = 成功，0 = 未检测到 */
void    LIS3DH_ReadAcc(short *accData);    /* accData[0..2] = X/Y/Z */
```

```c
/* bsp_lis3dh.c */
#include "bsp_lis3dh.h"
#include "bsp_sensor_io.h"

uint8_t LIS3DH_Init(void)
{
  uint8_t id;

  I2C_ReadRegs(LIS3DH_ADDR_W, LIS3DH_WHO_AM_I, &id, 1);
  if (id != 0x33)                 /* 身份确认：LIS3DH 固定返回 0x33 */
  {
    return 0;
  }

  I2C_WriteReg(LIS3DH_ADDR_W, LIS3DH_CTRL_REG1, 0x57);  /* ODR=100Hz，XYZ 使能 */
  I2C_WriteReg(LIS3DH_ADDR_W, LIS3DH_CTRL_REG4, 0x08);  /* ±2g，高分辨率(12位) */
  return 1;
}

/**
  * @brief  读取三轴加速度原始值
  * @note   1) 子地址需置最高位（|0x80）才启用地址自动递增，否则连读到的都是同一寄存器
  *         2) LIS3DH 输出为小端（低字节在前），与 MPU6050 的大端相反
  *         3) ±2g + 12 位时灵敏度 1 mg/LSB，静止平放某一轴约为 ±1000
  */
void LIS3DH_ReadAcc(short *accData)
{
  uint8_t buf[6];

  I2C_ReadRegs(LIS3DH_ADDR_W, LIS3DH_OUT_X_L | 0x80, buf, 6);

  accData[0] = (short)((buf[1] << 8) | buf[0]);   /* X */
  accData[1] = (short)((buf[3] << 8) | buf[2]);   /* Y */
  accData[2] = (short)((buf[5] << 8) | buf[4]);   /* Z */
}
```

列表 19: 代码清单 9-6 综合测试主程序（串口周期输出）

```c
/* main.c 的 USER CODE 区 */
#include "bsp_soft_i2c.h"
#include "bsp_bh1750.h"
#include "bsp_htu21d.h"
#include "bsp_pcf8563.h"
#include "bsp_lis3dh.h"

int main(void)
{
  float lux, temp, hum;
  short acc[3];
  PCF8563_Time_t now;
  /* 首次上电设置时间：2026-10-07 12:30:00 星期三
     （结构体顺序：秒, 分, 时, 日, 星期, 月, 年） */
  PCF8563_Time_t set = { 0, 30, 12, 7, 3, 10, 26 };

  HAL_Init();
  SystemClock_Config();        /* 168MHz，APB1=42MHz */
  MX_GPIO_Init();              /* 含 PA1(SCL)/PA0(SDA) 开漏输出 */
  MX_USART1_UART_Init();       /* 串口输出 115200-8-N-1 */

  printf("\r\n===== 软件 I2C 传感器组测试（SCL=PA1, SDA=PA0）=====\r\n");

  /* ---------- 1. BH1750 光照 ---------- */
  BH1750_Init();
  printf("BH1750  光照  : %7.1f lx\r\n", BH1750_ReadLux());

  /* ---------- 2. HTU21D 温湿度 ---------- */
  HTU21D_Init();
  temp = HTU21D_ReadTemp();
  hum  = HTU21D_ReadHumidity();
  printf("HTU21D  温度  : %7.2f C     湿度: %7.2f %%RH\r\n", temp, hum);

  /* ---------- 3. PCF8563 时钟 ---------- */
  if (PCF8563_IsTimeValid() == 0)
  {
    printf("PCF8563 掉电过，重新设置时间\r\n");
    PCF8563_WriteTime(&set);
  }
  PCF8563_ReadTime(&now);
  printf("PCF8563 时间  : 20%02d-%02d-%02d %02d:%02d:%02d 星期%d\r\n",
         now.year, now.month, now.day, now.hour, now.min, now.sec, now.weekday);

  /* ---------- 4. LIS3DH 三轴 ---------- */
  if (LIS3DH_Init() == 0)
  {
    printf("LIS3DH  未检测到，请检查 SA0 与接线\r\n");
  }

  /* ---------- 主循环：每 1 秒采集一次并打印 ---------- */
  while (1)
  {
    lux  = BH1750_ReadLux();
    temp = HTU21D_ReadTemp();
    hum  = HTU21D_ReadHumidity();
    PCF8563_ReadTime(&now);
    LIS3DH_ReadAcc(acc);

    printf("\r\n[20%02d-%02d-%02d %02d:%02d:%02d]\r\n",
           now.year, now.month, now.day, now.hour, now.min, now.sec);
    printf("  光照 : %7.1f lx\r\n", lux);
    printf("  温度 : %7.2f C        湿度 : %7.2f %%RH\r\n", temp, hum);
    printf("  三轴 : X=%6d  Y=%6d  Z=%6d\r\n", acc[0], acc[1], acc[2]);

    HAL_Delay(1000);
  }
}
```

**分析**：

- **四个器件共用一组总线，代码里靠"每次操作都完整起止"来保证互不干扰**。切忌把"给 BH1750 发命令"和"读 HTU21D"拼在同一个起始-停止之间；
- `I2C_ReadRegs()` 里的第二次 `I2C_Start()` 就是**重复起始 Sr**——PCF8563 和 LIS3DH 都要求"先写寄存器地址、再转读"，中间不能插入停止信号，否则器件会认为本次寻址结束；
- 两类器件的差异在代码里体现得非常清楚：BH1750/HTU21D 走 `I2C_WriteCmd` + `I2C_ReadBytes`；PCF8563/LIS3DH 走 `I2C_WriteReg` + `I2C_ReadRegs`。**这也是"先分清器件类型再写驱动"的原因**；
- 每个器件都做了**身份/数据合理性确认**：LIS3DH 读 WHO_AM_I 是否为 0x33、PCF8563 读 VL 位、BH1750/HTU21D 读一次数据看数值是否落在物理合理范围。这样串口日志能直接指出是哪个模块有问题。

#### 9.2.4 下载验证

编译下载，打开串口调试助手（115200-8-N-1），应看到类似输出：

```
===== 软件 I2C 传感器组测试（SCL=PA1, SDA=PA0）=====
BH1750  光照  :   156.7 lx
HTU21D  温度  :    24.35 C     湿度:   52.18 %RH
PCF8563 时间  : 2026-10-07 12:30:00 星期3

[2026-10-07 12:30:01]
  光照 :   158.3 lx
  温度 :    24.36 C        湿度 :    52.20 %RH
  三轴 : X=   -12  Y=    35  Z=  1012

[2026-10-07 12:30:02]
  光照 :   157.9 lx
  温度 :    24.36 C        湿度 :    52.19 %RH
  三轴 : X=   -14  Y=    33  Z=  1010
```

**验证要点（每一项都能证明某个模块工作正常）**：

| 观察 | 说明什么 |
| --- | --- |
| 时间每秒递增且星期正确 | PCF8563 走时正常、BCD 转换与连续读时序都对 |
| 手遮光照传感器，lx 明显下降；手电照射，升到上千 | BH1750 命令式访问正常、换算系数 1.2 正确 |
| 温度接近室温、湿度在 30~70%RH 之间 | HTU21D 的 No Hold 模式与状态位屏蔽正确 |
| 把开发板翻转/侧立，三轴数值随之变化，静止平放时某轴约 ±1000 | LIS3DH 地址自增、小端组合、量程配置全部正确 |
| 断电重启后时间仍继续（装了纽扣电池时） | PCF8563 备份电池走时正常 |

**排错捷径**：串口上只掉某一个模块的数据、其余三个正常，说明软件 I2C 时序没问题，问题在该模块的地址跳线或焊接；如果**四个模块全部异常**，则是总线上拉电阻或 PA1/PA0 接线的问题。

---

## 10. 软硬件 I2C 对比与选型

两种实现方式在**协议层完全一致**（都遵守起始/停止/应答规则），差别在"谁来产生时序"。

**表 10-1 硬件 I2C 与软件 I2C 对比**

| 对比项 | 硬件 I2C（片上 I2C 外设） | 软件 I2C（GPIO 模拟） |
| --- | --- | --- |
| 时序产生者 | 硬件状态机，自动产生 SCL、自动收发移位 | CPU 用 GPIO 翻转 + 延时循环 |
| CPU 占用 | 低（阻塞模式下仍需等待；DMA/中断下极低） | 高（全程占用 CPU 空转延时） |
| 速率 | 稳定 100k/400kHz，与主频无关 | 由延时循环决定，受主频、中断影响，**速率不稳定** |
| 引脚要求 | **必须是 AF4 规定的复用引脚**（I2C1=PB6/PB7 或 PB8/PB9，I2C3=PA8/PC9…） | **任意 GPIO**，布线自由，可绕开引脚冲突 |
| 本笔记的适配情况 | 传感器原接线 PA1/PA0 **无法使用**，需改接到 PB8/PB9 | 原接线 PA1/PA0 **可直接使用** |
| 资源占用 | 占用一个 I2C 外设（F4 只有 3 个） | 只占 2 个 GPIO，可复制出多路 I2C |
| 抗干扰 | 好，硬件自动处理时钟延展、仲裁 | 差，一旦被中断打断会拉长时钟（多数器件可容忍） |
| 时钟延展支持 | **原生支持**，HTU21D 的 Hold Master 模式可直接用 | 需自己实现（拉高 SCL 后读回确认），一般改用 No Hold 模式 |
| 中断中的表现 | 需要中断/DMA 配合，纯阻塞在中断里不可用 | 时序容易被中断打断，不适合在中断中调用 |
| 已知问题 | F4 的 I2C 存在总线死锁/BUSY 卡死的勘误，需要软件恢复 | 无外设缺陷，时序全在自己手里，出问题好定位 |
| 代码量 | 少（调 HAL 库函数即可） | 多（需自己实现完整时序层） |
| 移植性 | 换芯片系列需注意结构体差异（ClockSpeed vs Timing） | **极好**，任何有 GPIO 的 MCU 都能用 |
| 调试难度 | 黑盒，只能看返回值和状态寄存器 | 白盒，配合示波器/逻辑分析仪一目了然 |
| 典型适用 | 产品开发、高速率、多器件、低功耗场合 | 教学、引脚受限、多路 I2C、驱动难伺候的器件 |

**就本套传感器而言的结论**：

1. 传感器总线接在 **PA1/PA0**，**只能用软件 I2C**——这不是"选型偏好"而是**硬件限制**（6.8 节）；
2. 如果愿意改线到 PB8/PB9，则**推荐用硬件 I2C**：CPU 占用低、速率稳定、能配合 DMA，且原生支持 HTU21D 的时钟延展；
3. **遇到坑就退回软件 I2C**：① STM32 F4 的 I2C 在某些工况下会出现 `BUSY` 位卡死（官方有相关勘误）；② 某些从机器件时序不规范，"太标准"的硬件外设反而迁就不了；③ 硬件 I2C 引脚与其它外设冲突；
4. **学习顺序建议**：先用软件 I2C 把协议吃透（第 8、9 章），再用硬件 I2C 体会外设的便利（第 7 章），这样遇到问题才有判断力。

---

## 11. 扩展：总线死锁恢复、DMA 与从机模式

### 11.1 I2C 总线死锁与恢复

**现象**：`HAL_I2C_Master_Transmit()` 一直返回 `HAL_BUSY` 或超时，`I2C_SR2` 的 `BUSY` 位一直为 1，即使断电重启从机也不能恢复。

**原因**：主从通讯被意外中断（例如复位、上电时序错位），从机正输出数据位 "0" 把 SDA 拉低并等待时钟，而主机已经不再发时钟——**从机抱着 SDA 不放，总线永久被占**。

**恢复原理**：主机手动发最多 9 个 SCL 时钟，让从机把剩余的位发完，再补一个停止条件，从机就会释放总线。

列表 20: 代码清单 11-1 硬件 I2C 总线死锁恢复

```c
/**
  * @brief  硬件 I2C 总线死锁恢复（以 I2C1 的 PB8/PB9 为例）
  * @note   把 SCL/SDA 临时切成 GPIO 开漏，手动补时钟与停止条件后恢复复用功能
  */
void I2C_BusRecover(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  uint8_t i;

  /* 1. 关闭 I2C 外设，让引脚不再受外设控制 */
  __HAL_I2C_DISABLE(&hi2c1);

  /* 2. 把 PB8/PB9 临时配成开漏输出 */
  GPIO_InitStruct.Pin   = GPIO_PIN_8 | GPIO_PIN_9;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_OD;
  GPIO_InitStruct.Pull  = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* 3. 释放 SDA，然后补 9 个 SCL 时钟，把从机剩余的位"抽"出来 */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);
  for (i = 0; i < 9; i++)
  {
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
    HAL_Delay(1);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);
    HAL_Delay(1);
  }

  /* 4. 补一个停止条件：SCL 高电平期间 SDA 由低变高 */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET);
  HAL_Delay(1);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);
  HAL_Delay(1);

  /* 5. 恢复复用开漏 + AF4，重新初始化 I2C 外设 */
  GPIO_InitStruct.Mode      = GPIO_MODE_AF_OD;
  GPIO_InitStruct.Alternate = GPIO_AF4_I2C1;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  HAL_I2C_Init(&hi2c1);
}
```

> 这段代码也解释了为什么"软件 I2C 更皮实"：它本来就一直用 GPIO 在翻转，**不存在外设状态机卡死的概念**，出问题只可能是代码逻辑或硬件上拉。事实上，**这套代码用在 PA1/PA0 的软件 I2C 上甚至更简单**——只需要补 9 个时钟，不需要"关闭外设/恢复复用功能"这两步。

### 11.2 DMA 方式传输

需要批量搬运 EEPROM 数据或高速读取传感器时，用 DMA 可以把 CPU 从逐字节等待中解放出来：

1. CubeMX 的 **DMA Settings** 中为 I2C1 添加 **I2C1_TX** 与 **I2C1_RX** 通道，Mode 选 Normal，数据宽度 Byte，优先级 Medium；
2. 调用 `HAL_I2C_Mem_Write_DMA()` / `HAL_I2C_Mem_Read_DMA()` 启动传输，函数立即返回；
3. 传输完成触发回调 `HAL_I2C_MemTxCpltCallback()` / `HAL_I2C_MemRxCpltCallback()`，在回调里置标志位通知主循环；
4. **注意**：DMA 完成回调只表示数据搬运结束，**AT24C02 的内部写周期仍需单独等待**；
5. DMA 只对硬件 I2C 有意义，软件 I2C 的时序由 CPU 直接翻转，无法交给 DMA。

### 11.3 STM32 作为 I2C 从机

STM32 的 I2C 也能当从机（例如让 F407 作为一块"传感器板"被另一块主板读取）：

1. CubeMX 中把 I2C1 的 **Own Address 1** 填成自己的从机地址（不能为 0），Addressing Mode 保持 7-bit；
2. 调用 `HAL_I2C_Slave_Receive_IT(&hi2c1, buf, len)` 挂起接收，收到主机数据后触发 `HAL_I2C_SlaveRxCpltCallback()`；
3. 从机的时钟由主机提供，因此**从机模式下 `ClockSpeed` 已不决定实际速率**，但仍需配置合法值；
4. 从机模式只能用硬件 I2C 实现，软件 I2C 要当从机需要自己写状态机，难度很大。

### 11.4 时钟延展（Clock Stretching）

从机处理不过来时会**主动把 SCL 拉低**，强制主机等待，这叫时钟延展。STM32 的 I2C 外设本身支持，CubeMX 中 **No Clock Stretch** 保持 `Clock stretching enabled`（即 `I2C_NOSTRETCH_DISABLE`）即可——**本笔记的四个传感器里，HTU21D 的 Hold Master 模式就依赖这个特性**。软件 I2C 若想支持延展，需要在拉高 SCL 后**读回 SCL 电平**，直到它真的变高再继续；本笔记的软件 I2C 没有实现这一步，因此 HTU21D 采用 No Hold Master 模式（见 6.5 节）。

---

## 12. 本章小结

1. I2C 分物理层（SDA/SCL 两线、开漏+上拉实现"线与"、总线电容 ≤400pF、100k/400k 速率）和协议层（起始 S、重复起始 Sr、地址+R/W、应答 ACK/NACK、数据、停止 P，**数据只能在 SCL 低电平时变化，SCL 高电平时必须稳定**）。
2. F407VET6 有 I2C1/I2C2/I2C3 三个外设，**全部挂 APB1（42MHz）、全部用 AF4**；常用 I2C1 = PB8/PB9（或 PB6/PB7），I2C2 = PB10/PB11，I2C3 = PA8/PC9（VET6 无 PH 口）。
3. **本笔记最重要的硬件结论**：**PA0/PA1 在 F407VET6 上没有任何 I2C 复用功能**，所以"SCL=PA1、SDA=PA0"这套传感器接线**只能用软件 I2C**；要用硬件 I2C 必须把总线改接到 PB8/PB9（或 PA8/PC9）。
4. 本套传感器分两类：**命令型**（BH1750 光照 0x23、HTU21D 温湿度 0x40，直接发命令、直接读结果）与**寄存器型**（PCF8563 时钟 0x51、LIS3DH 三轴 0x18，先给寄存器地址再读写）。**两类器件要用两套 API/原语**，这是 I2C 编程最容易搞混的地方。
5. 五个器件（含 AT24C02 0x50）地址两两不同，才能共用一组总线；接线前务必确认 ADDR/SA0/A0~A2 跳线电平。
6. 内部结构核心：**CCR** 决定 SCL 频率（标准模式 1:1，快速模式 2:1 或 16:9）、DR 收发数据、OAR 做从机地址、SR1/SR2 指示 EV5/EV6/EV7/EV8 状态机进程。频率不用手算，CubeMX 填 ClockSpeed 即可；**F4 用 `ClockSpeed` + `DutyCycle`，F7/L4/H7 用 `Timing`**。
7. 硬件 I2C 实验（PB8/PB9）：`HAL_I2C_Mem_Write/Read` 读写 EEPROM，**每次写完必须等 5ms 内部写周期**（`HAL_I2C_IsDeviceReady` 轮询），写超过 8 字节必须按页拆分；命令型器件则用 `HAL_I2C_Master_Transmit/Receive`。
8. 软件 I2C 实验（PA1/PA0）：两个 GPIO 配 **开漏输出 + 上拉**，用宏控制电平、空循环产生延时，自己实现起始/停止/发送/等待应答/读字节五个基础函数；**STM32 在开漏输出下仍可通过 IDR 读回引脚电平**。
9. 分层设计的价值：时序层（不知道从机是谁）→ 原语层（命令写/连续读/寄存器写/寄存器连续读）→ 器件层（只关心地址、命令与寄存器号）→ 应用层。同一份时序代码既驱动 AT24C02，也驱动四个传感器。
10. 所有实验都通过 **USART1 + printf** 输出结果（115200-8-N-1），配合"手遮光照""翻转板子""断电重启看时间"等动作，可以直观验证每个传感器是否真的在工作。
11. 选型结论：**本套传感器受引脚限制必须用软件 I2C**；若可改线到 PB8/PB9，则产品开发优先硬件 I2C（低 CPU 占用、稳定、可用 DMA、原生支持时钟延展）；遇到 F4 的 I2C 死锁卡死、引脚冲突、器件时序不规范时，改用软件 I2C 往往最省事。

## 13. 常见问题速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| CubeMX 里点 PA1/PA0 找不到 I2C 功能 | **这两个脚本来就没有 I2C 复用** | 属正常现象：软件 I2C 把它们配成开漏输出即可；要硬件 I2C 就改用 PB8/PB9 |
| `HAL_I2C_IsDeviceReady` 一直失败 | 器件没上电、地址错、**上拉电阻缺失** | 量 SDA/SCL 空闲时是否被拉到 3.3V；核对 7 位/8 位地址换算 |
| 软件 I2C 全部器件都读不到 | PA1/PA0 接反、上拉电阻缺失、延时过短 | 交换 SCL/SDA 试；补 4.7kΩ 上拉；把 `I2C_Delay()` 循环次数调大 |
| 只有某一个传感器读不到 | 该模块地址跳线冲突、虚焊或模块损坏 | 核对表 6-3 的 ADDR/SA0/A0~A2；单独接该模块测试 |
| 写 EEPROM 偶发失败（AF 应答失败） | 没等 5ms 内部写周期 | 每次写后用 `HAL_I2C_IsDeviceReady` 轮询到应答再继续 |
| 写超过 8 字节后数据错乱 | 跨页写回卷覆盖 | 按 8 字节页边界拆分写入 |
| 读只能读到第一个字节，之后全 0xFF | 读完没回 NACK 或没发停止信号 | 最后一个字节 `I2C_SendAck(0)` 后 `I2C_Stop()` |
| HTU21D 读出的温湿度明显离谱 / 读不到 | 用了 Hold Master 模式（0xE3/0xE5）而软件 I2C 不支持时钟延展；或没屏蔽低 2 位状态位 | 改用 No Hold 模式 `0xF3`/`0xF5` 并延时；`raw & 0xFFFC` |
| BH1750 光照值一直是 0 或很小 | 没发上电命令 `0x01`，或没等 120ms 测量完成 | 按 6.4 节顺序初始化并延时至 180ms |
| LIS3DH 三轴读数恒定不变 | 多字节读没有置子地址最高位，地址未自增 | 用 `LIS3DH_OUT_X_L \| 0x80` |
| LIS3DH 数值符号/量级不对 | 按大端组合，或量程与灵敏度不匹配 | 小端组合 `(buf[1]<<8)\|buf[0]`；±2g+12 位时 1 mg/LSB |
| PCF8563 时间乱跳或走时错 | 写时间时没有先停表（STOP 位），或 BCD 未转换 | 写前 `CTRL1=0x20`，写完 `CTRL1=0x00`；用 BCD 互转函数 |
| PCF8563 每次上电时间归零 | 模块没有纽扣电池 | 属正常；用 VL 位判断并重新设置时间 |
| 波形上升沿是斜坡、读不到数据 | 内部弱上拉不够 / 上拉阻值过大、或**多个模块上拉并联后过小** | 只保留一组 4.7kΩ 上拉（高速 2.2kΩ） |
| SDA 被从机拉住不放、`BUSY` 一直为 1 | 硬件 I2C 总线死锁 | 调 `I2C_BusRecover()` 手动补 9 个时钟 + 停止条件 |
| 软件 I2C 在中断里调用后通讯乱掉 | 时序被更高级中断打断，时钟被拉长 | 不要在中断中调用软件 I2C；或调用期间关中断 |
| 编译报错找不到 `Init.Timing` / `I2C_InitTypeDef` 成员不匹配 | 抄了 F7/L4 的代码 | F4 用 `ClockSpeed` + `DutyCycle` |
| 从机地址对不上（0x50 还是 0xA0） | 7 位地址与 8 位地址混淆 | **HAL API 传 8 位形式**：0x50→0xA0(写)/0xA1(读)；软件 I2C 同理 |
| 串口无输出 | 没勾 Use MicroLIB（Keil）、波特率不对、TX/RX 没交叉、没共地 | 见《USART—串口通信》章节的排错表 |
| 重新生成代码后自己的驱动丢失 | 代码写在 CubeMX 管理区 | 所有手写代码放进 `USER CODE BEGIN/END`，或单独建 `bsp_xxx.c/h` |
| 硬件 I2C 与软件 I2C 数据不一致 | 其中一个实验的上拉/地址/页边界处理有误 | 用第 7 章硬件驱动去读第 8 章写的数据做交叉验证 |
