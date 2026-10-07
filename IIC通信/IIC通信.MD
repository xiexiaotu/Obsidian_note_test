# IIC—软硬件 I2C 通信（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F4xx 中文数据手册》I2C 引脚复用表、《RM0090 STM32F407 参考手册》I2C 章节、《AT24C02 数据手册》、《MPU-6050 寄存器手册》。
> **学习提示**：配合参考手册中 I2C_CR1/CR2、I2C_CCR、I2C_TRISE、I2C_OAR1/OAR2、I2C_SR1/SR2、I2C_DR 寄存器的说明一起阅读，效果更佳，特别是涉及寄存器位定义和状态机事件（EV5/EV6/EV7/EV8）的部分。
> **特别说明**：本笔记内容以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 STM32 HAL 库。本笔记**同时覆盖硬件 I2C 与软件 I2C 两种实现方式**：前者使用芯片内部 I2C 外设，后者用两个普通 GPIO 模拟时序。

---

## 1. I2C 通讯协议简介

I2C 通讯协议（Inter-Integrated Circuit）是由 Philips 公司开发的一种**同步、半双工、多主多从**的串行总线协议。因为它只需要两根信号线就能挂载几十个器件，布线极简、扩展性强，所以被大量用于连接 EEPROM、传感器（MPU6050、温度、气压）、触摸屏、RTC、OLED 屏等芯片。

和芯片分为内核层与片上外设一样，理解通讯协议最基本的方法仍然是**分层**：把它分为**物理层**和**协议层**。

- **物理层**：规定通讯系统中机械、电子部分的特性，确保原始比特能在物理媒体上传输——相当于规定"用嘴巴还是用肢体交流"。
- **协议层**：规定通讯逻辑，统一收发双方的数据打包、解包标准——相当于规定"用中文还是英文交流"。

### 1.1 物理层

I2C 总线只需两根线：

- **SDA（Serial Data）**：双向数据线，主机和从机都通过它收发数据；
- **SCL（Serial Clock）**：时钟线，由主机产生，用于同步数据位的传输。

I2C 物理层的几个关键特性：

1. **开漏输出 + 上拉电阻（线与逻辑）**。总线上所有器件的 SDA/SCL 引脚都是**开漏（OD）**结构，只能把线拉低，不能主动拉高；高电平由**上拉电阻**提供。这样任何器件拉低总线都能让整条线变低，实现"线与"，天然支持多主机冲突检测与仲裁。**这是 I2C 最本质的一条电气规则，也是软件 I2C 必须把 GPIO 配成开漏输出的原因。**
2. **多设备与地址寻址**。一条总线上可以挂多个从机，每个从机有唯一的器件地址（7 位或 10 位），主机通过发送地址来选择与哪个从机通讯。
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
- 如果主机想在不释放总线的情况下改变传输方向（例如写寄存器地址后立刻读数据），可以再发一次起始信号，称为**重复起始信号 Sr（Repeated Start）**。AT24C02 的随机读就必须用 Sr。

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

> **工程上极易混淆的一点**：同一个器件地址常有两种写法。以 AT24C02 为例，7 位地址是 `1010000b = 0x50`，而"8 位形式"（把地址左移一位、低位拼上 R/W）是 `0xA0`（写）/ `0xA1`（读）。**STM32 HAL 库的 API 用的是 8 位形式**，即 `HAL_I2C_Mem_Write(&hi2c1, 0xA0, ...)`。

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

1. **主机读从机数据时**，收到最后一个字节后主机要回 **NACK**，告诉从机"不要再发了"，然后发停止信号；
2. **主机寻址从机失败时**，从机不回应答，主机读到的是 NACK，可据此判断器件不存在（HAL 库会返回 `HAL_ERROR`）。

---

## 2. STM32F407VET6 的 I2C 简介

STM32F407VET6 共有 **3 个 I2C 外设**：I2C1、I2C2、I2C3，全部挂在 **APB1 总线**上（F407 在 168MHz 系统时钟下 APB1 = 42MHz）。这里要特别强调：**STM32F407 的 I2C 引脚复用全部使用 AF4**，选引脚时不要和 USART 的 AF7、SPI 的 AF5 混了。

I2C 外设主要特性：

- 支持 **100 kbit/s 标准模式**与 **400 kbit/s 快速模式**；
- 支持 **7 位和 10 位**器件地址，可编程的自身地址（做从机时用）；
- 支持 **DMA** 传输，降低 CPU 占用；
- 支持 **SMBus 2.0**（ARP、超时、警报等，I2C 通讯用不到）；
- 支持 **PEC（Packet Error Checking）** 数据包校验；
- 支持**时钟延展（Clock Stretching）**与**多主机仲裁**；
- 支持多种中断：起始位 SB、地址匹配 ADDR、发送空 TXE、字节传输完成 BTF、接收非空 RXNE、错误（AF/BERR/ARLO/OVR/TIMEOUT）。

F407VET6 各 I2C 的引脚映射（CubeMX 选引脚时直接查这张表）：

**表 2-1 STM32F407VET6 I2C 资源与引脚映射（LQFP100 可用引脚）**

| 外设 | 总线 | SCL 引脚 | SDA 引脚 | 复用 AF | 备注 |
| --- | --- | --- | --- | --- | --- |
| I2C1 | APB1（42MHz） | PB6 / PB8 | PB7 / PB9 | AF4 | 最常用，本笔记实验选 PB8/PB9 |
| I2C2 | APB1（42MHz） | PB10 / PF1 | PB11 / PF0 | AF4 | PF0/PF1 只在 100 脚以上封装才有 |
| I2C3 | APB1（42MHz） | PA8 | PC9 | AF4 | I2C3 的另一组引脚在 PH7/PH8，**VET6 没有 PH 口**，只能用 PA8/PC9 |

> 说明：I2C1 的 SCL 可选 PB6 或 PB8、SDA 可选 PB7 或 PB9，两组引脚任选一组即可，**不能交叉**（不能 PB6 配 PB9）。I2C2 与 I2C1 都能用 PB10/PB11 附近资源，硬件设计时要检查引脚冲突。
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

**主机发送流程**（例如读 EEPROM 时先写寄存器地址）：

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
| Addressing Mode | `AddressingMode` | `I2C_ADDRESSINGMODE_7BIT` | 绝大多数器件是 7 位 |
| Dual Address Mode | `DualAddressMode` | `I2C_DUALADDRESS_DISABLE` | 一般不用 |
| Own Address 2 | `OwnAddress2` | 0 | 仅 7 位 |
| General Call | `GeneralCallMode` | `I2C_GENERALCALL_DISABLE` | 一般不用 |
| No Clock Stretch | `NoStretchMode` | `I2C_NOSTRETCH_DISABLE` | 主机模式下建议保持允许延展 |

> **重要提醒**：`I2C_InitTypeDef` 的成员随 STM32 系列而变。**F1/F2/F4 用 `ClockSpeed` + `DutyCycle`（填写"要多少 kHz"，硬件自己算 CCR）**；而 F7/L4/H7 等较新系列改成了 **`Timing`**（填写一个算好的 32 位时序值）。网上很多 F4 教程里出现 `Init.Timing = 0x60201E2B` 的写法，那是 F7/L4 的代码，直接搬到 F407 上会**编译报错或时序全错**，看教程时务必先确认芯片系列。

而引脚、时钟这些**与具体 MCU 硬件绑定**的配置，由 `HAL_I2C_MspInit()` 完成（HAL 弱函数，CubeMX 自动重写在 `stm32f4xx_hal_msp.c`），这就是 HAL 库"协议抽象"与"硬件抽象"分层的精髓。

常用 API 一览：

**表 4-2 HAL I2C 常用 API**

| API | 用途 | 说明 |
| --- | --- | --- |
| `HAL_I2C_Master_Transmit()` | 主机发送 | 只管发数据流，不涉及寄存器地址 |
| `HAL_I2C_Master_Receive()` | 主机接收 | 配合上面的函数实现"写地址再读" |
| `HAL_I2C_Mem_Write()` | 写器件寄存器/存储单元 | **内含"写地址 + 重复起始 + 写数据"完整时序**，读写 EEPROM、传感器寄存器首选 |
| `HAL_I2C_Mem_Read()` | 读器件寄存器/存储单元 | 同上，内含 Sr 时序 |
| `HAL_I2C_IsDeviceReady()` | 探测从机是否应答 | 返回 `HAL_OK` 说明器件在线，可用于等待 EEPROM 内部写周期 |
| `HAL_I2C_GetState()` | 读句柄状态 | 典型值 `HAL_I2C_STATE_READY` |
| `HAL_I2C_Master_Transmit_IT()` 等 | 中断方式 | 完成触发 `HAL_I2C_MasterTxCpltCallback` |
| `HAL_I2C_Master_Transmit_DMA()` 等 | DMA 方式 | 大数据量、低 CPU 占用 |
| `HAL_I2C_Slave_Receive_IT()` 等 | 从机方式 | 让 STM32 充当 I2C 从机 |

> `Mem_AddressSize` 参数填 `I2C_MEMADD_SIZE_8BIT`（AT24C02、MPU6050）或 `I2C_MEMADD_SIZE_16BIT`（更大容量的 EEPROM，如 AT24C256）。

---

## 5. STM32CubeMX 配置工程（硬件 I2C）

以下以一个全新工程演示从零配置 I2C1 的完整步骤。

### 5.1 新建工程与芯片选择

1. CubeMX 欢迎页 → **New Project**，在 *Select MCU* 搜索框输入 `STM32F407VET6`，选中 LQFP100 封装，确认进入工程。

> 📷 图 5-1 新建工程、搜索并选中 STM32F407VET6（此处可插入截图）

### 5.2 系统时钟（RCC + Clock Configuration）

1. **RCC** → HSE 选择 **Crystal/Ceramic Resonator**（外部 8MHz 晶振）。
2. **Clock Configuration**：PLL 源选 HSE，PLL_M=8、PLL_N=336、PLL_P=2，系统时钟 **SYSCLK = 168MHz**；APB1 分频 ÷4 → **42MHz**（I2C1/2/3 的时钟 PCLK1）。
3. 若外部晶振不是 8MHz，按板子实际晶振调整 PLL_M。

> **注意**：APB1 时钟直接决定 SCL 的实际频率。如果 APB1 配成 36MHz 而不是 42MHz，生成的 `CCR` 值会随之变化，但只要你在 CubeMX 里填的是"400000"，HAL 会按实际 PCLK1 重算，最终 SCL 仍是 400kHz——**这正是用 CubeMX 配置比手写寄存器安全的地方**。

### 5.3 配置 I2C1

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

### 5.4 工程生成设置

1. **Project Manager → Project**：填工程名、选择工程存放位置，工具链选 **MDK-ARM (V5)** 或 STM32CubeIDE。
2. **Project Manager → Code Generator** 建议勾选 *Generate peripheral initialization as a pair of .c/.h files per peripheral*，生成 `i2c.c/h`，把自己写的驱动与 CubeMX 管理区隔离开。
3. 右上角 **GENERATE CODE**。

生成后重点关注三处代码：

- `i2c.c`：`MX_I2C1_Init()` —— 协议参数初始化；
- `stm32f4xx_hal_msp.c`：`HAL_I2C_MspInit()` —— 时钟/GPIO 配置；
- `stm32f4xx_it.c`：`I2C1_EV_IRQHandler()` / `I2C1_ER_IRQHandler()` —— 中断入口（勾选 NVIC 后生成）。

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

列表 2: 代码清单 5-2 CubeMX 生成的协议层初始化

```c
/* i2c.c */
I2C_HandleTypeDef hi2c1;

static void MX_I2C1_Init(void)
{
  hi2c1.Instance             = I2C1;
  hi2c1.Init.ClockSpeed      = 400000;                        /* 400kHz */
  hi2c1.Init.DutyCycle       = I2C_DUTYCYCLE_2;               /* 快速模式 2:1 */
  hi2c1.Init.OwnAddress1     = 0;                             /* 只做主机 */
  hi2c1.Init.AddressingMode  = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2     = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode   = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
}
```

> **纪律提醒**：重新 GENERATE CODE 只会覆盖 `MX_..._Init` 等 CubeMX 管理区域，用户代码写在 `USER CODE BEGIN/END` 注释块内即不会被冲掉。自己写的 EEPROM/MPU6050 驱动建议单独放 `bsp_i2c_ee.c/h`，不写进 `i2c.c`。

---

## 6. 实验一：硬件 I2C 读写 AT24C02 EEPROM

**实验目标**：使用 STM32 片内 I2C1 外设读写板载 AT24C02，向 EEPROM 写入一串递增数据并读回比对，通过串口打印结果、用 LED 指示成功或失败。这是硬件 I2C 的标准入门实验，能同时验证时序、地址、应答和 HAL 库用法。

### 6.1 硬件设计

AT24C02 是 2Kbit（**256 字节**）的 I2C EEPROM，SCL/SDA 分别接 STM32 的 PB8/PB9（两根线都要**外部上拉 4.7kΩ** 到 3.3V），WP 引脚接地（允许写）或接高电平（写保护，本实验接地）。

**表 6-1 AT24C02 关键参数**

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| 容量 | 256 字节（2Kbit） | 地址范围 0x00~0xFF |
| 页大小 | **8 字节** | 跨页写会"回卷"覆盖，必须分页处理 |
| 7 位器件地址 | `1010000b = 0x50` | 由 A0/A1/A2 决定，本板全接地 |
| 8 位地址（HAL 用） | `0xA0`（写）/ `0xA1`（读） | HAL API 传这个值 |
| 写周期 tWR | 最大 **5 ms** | 每次写操作后必须等待，期间器件不应答 |
| 写保护 | WP 引脚 | 接高电平则整片只读 |

**地址计算**：AT24C02 的 7 位地址高 4 位固定为 `1010`，低 3 位由 A2/A1/A0 引脚电平决定。本板 A2=A1=A0=0，因此：

```
7 位地址 = 1010 000b = 0x50
8 位写地址 = 0x50 << 1 | 0 = 0xA0
8 位读地址 = 0x50 << 1 | 1 = 0xA1
```

> 📷 图 6-1 AT24C02 与 STM32 的接线（SDA/SCL 上拉电阻、WP 接地）

### 6.2 软件设计

#### 6.2.1 编程要点

1. CubeMX 完成 I2C1（400kHz、7 位地址）配置，PB8/PB9 复用开漏 + AF4，生成代码；
2. 用 `HAL_I2C_Mem_Write()` 写字节日志，它内部会自动完成"起始 → 发送器件地址 → 发送存储地址 → 发送数据 → 停止"的完整时序；
3. **每写完一页/一字节，必须等待 EEPROM 内部写周期**：用 `HAL_I2C_IsDeviceReady()` 轮询，直到器件重新应答为止，否则后续操作会失败；
4. 写超过 8 字节的数据必须**按页拆分**，避免跨页回卷；
5. 读数据用 `HAL_I2C_Mem_Read()`，它内部使用**重复起始信号 Sr**，先写存储地址再读数据。

#### 6.2.2 代码分析

列表 3: 代码清单 6-1 AT24C02 硬件 I2C 驱动（bsp_i2c_ee.h）

```c
/* bsp_i2c_ee.h —— AT24C02 基于硬件 I2C1 的驱动接口 */
#ifndef __BSP_I2C_EE_H
#define __BSP_I2C_EE_H

#include "stm32f4xx_hal.h"

#define EEPROM_ADDRESS   0xA0    /* 8 位地址：0x50<<1 | 写位 */
#define EEPROM_PAGESIZE  8       /* AT24C02 页大小，写周期不可跨页 */
#define EEPROM_MAX_TRIALS 3      /* 探测器件在线时的重试次数 */
#define EEPROM_TIMEOUT   100     /* 每步超时 ms */

HAL_StatusTypeDef AT24C02_WriteByte(uint16_t memAddr, uint8_t data);
HAL_StatusTypeDef AT24C02_WriteBuffer(uint16_t memAddr, uint8_t *pData, uint16_t len);
HAL_StatusTypeDef AT24C02_ReadBuffer(uint16_t memAddr, uint8_t *pData, uint16_t len);
uint8_t AT24C02_Check(void);

#endif
```

列表 4: 代码清单 6-2 AT24C02 字节写与写周期等待（bsp_i2c_ee.c）

```c
/* bsp_i2c_ee.c —— USER CODE 区内实现，重新生成代码不会丢失 */
#include "bsp_i2c_ee.h"
#include "i2c.h"       /* 提供 hi2c1 */

/* 等待 EEPROM 内部写周期结束：期间器件不响应，IsDeviceReady 探到即返回 */
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
```

列表 5: 代码清单 6-3 任意长度写入（自动按页拆分）

```c
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

列表 6: 代码清单 6-4 读数据与器件探测

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

列表 7: 代码清单 6-5 测试主程序（main.c 的 USER CODE 区）

```c
/* main.c 的 USER CODE BEGIN Includes 内 */
#include "bsp_i2c_ee.h"

#define DATA_SIZE  32
uint8_t ee_write_buf[DATA_SIZE];
uint8_t ee_read_buf[DATA_SIZE];

int main(void)
{
  uint16_t i;

  HAL_Init();
  SystemClock_Config();      /* 168MHz */
  MX_GPIO_Init();
  MX_USART1_UART_Init();     /* 用于打印结果，见《USART—串口通信》章节 */
  MX_I2C1_Init();            /* I2C1 400kHz */

  printf("\r\n===== STM32F407VET6 硬件 I2C 读写 AT24C02 =====\r\n");

  if (AT24C02_Check() == 0)
  {
    printf("错误：未检测到 AT24C02，请检查上拉电阻与接线\r\n");
    while (1);
  }

  /* 1. 准备数据：0,1,2,…,31 */
  for (i = 0; i < DATA_SIZE; i++)
  {
    ee_write_buf[i] = (uint8_t)i;
  }

  /* 2. 写入 EEPROM（从 0x00 开始） */
  if (AT24C02_WriteBuffer(0x00, ee_write_buf, DATA_SIZE) != HAL_OK)
  {
    printf("错误：EEPROM 写入失败\r\n");
    while (1);
  }
  printf("写入完成，共 %d 字节\r\n", DATA_SIZE);

  /* 3. 读回并逐字节比对 */
  if (AT24C02_ReadBuffer(0x00, ee_read_buf, DATA_SIZE) != HAL_OK)
  {
    printf("错误：EEPROM 读取失败\r\n");
    while (1);
  }

  for (i = 0; i < DATA_SIZE; i++)
  {
    printf("0x%02X ", ee_read_buf[i]);
    if (ee_read_buf[i] != ee_write_buf[i])
    {
      printf("\r\n错误：地址 0x%02X 数据不一致（写 0x%02X，读 0x%02X）\r\n",
             i, ee_write_buf[i], ee_read_buf[i]);
      while (1);
    }
    if (i % 16 == 15)
    {
      printf("\r\n");
    }
  }
  printf("I2C(AT24C02) 读写测试成功\r\n");

  while (1)
  {
  }
}
```

**分析**：

- `HAL_I2C_Mem_Write()` 一个函数就覆盖了"起始 → 器件地址+W → 存储地址 → 数据 → 停止"整个时序，比早期标准库需要手写 `I2C_Send7bitAddress()`、`I2C_SendData()` 简洁得多；
- **本实验最容易踩的坑是写周期等待**。AT24C02 收到停止信号后进入 5ms 的内部编程周期，此期间它**不响应任何寻址**。若立即发起下一次写，会得到 `AF`（应答失败），HAL 返回 `HAL_ERROR`。用 `HAL_I2C_IsDeviceReady()` 轮询探测正好等价于"等待器件空闲"；
- 32 字节写入被自动拆成 4 次页写（0x00、0x08、0x10、0x18 各 8 字节），每次写完都等待 5ms，所以肉眼看不到明显延迟。

#### 6.2.3 下载验证

编译下载到开发板，打开串口调试助手（115200-8-N-1），上电应看到：

```
===== STM32F407VET6 硬件 I2C 读写 AT24C02 =====
写入完成，共 32 字节
0x00 0x01 0x02 … 0x0F
0x10 0x11 0x12 … 0x1F
I2C(AT24C02) 读写测试成功
```

**验证"真的写进 EEPROM 了"**：把开发板**断电再上电**（或按复位键），数据从 0x00 读出来仍然是 0x00 0x01 0x02…，说明数据断电不丢失，确实写入了 EEPROM 而不是只存在于 RAM 里。

---

## 7. 实验二：软件 I2C（GPIO 模拟时序）读写 AT24C02

**实验目标**：完全**不使用 STM32 的 I2C 外设**，只用两个普通 GPIO（推挽改开漏）模拟 SCL/SDA 的时序，实现同一套 AT24C02 读写功能。做完这个实验，你会对 I2C 协议的理解从"会调库"上升到"懂时序"，遇到任何 I2C 器件都能自己写驱动。

### 7.1 硬件设计

- SCL 接 **PB6**，SDA 接 **PB7**（选这两个脚是为了和硬件 I2C 的 PB8/PB9 错开，方便同一块板子上两个实验都可以接线；任意两个空闲 GPIO 均可）；
- 两根线**同样需要 4.7kΩ 外部上拉电阻**——这一点软硬件 I2C 完全一致；
- AT24C02 的 A0/A1/A2 接地、WP 接地，器件地址仍是 0xA0。

> **为什么软件 I2C 的 GPIO 必须配成"开漏输出"而不是"推挽输出"？**
> 因为 I2C 是"线与"总线：如果 STM32 用推挽输出把 SDA 拉高（强驱动 3.3V），而此时从机正想把 SDA 拉低来回应答，两个引脚就会直接对打，轻则通讯失败，重则**烧毁引脚**。开漏输出只能拉低、不能主动拉高，高电平交给上拉电阻，这才是 I2C 正确的电气姿势。

### 7.2 CubeMX 配置（把两个 GPIO 配成开漏输出）

1. 在**同一个工程**里（保留 I2C1 也可，不冲突），左侧 **System Core → GPIO**，点击 PB6，选择 **GPIO_Output**；点击 PB7，同样选 **GPIO_Output**。
2. 选中 PB6，在下方 **GPIO mode and Configuration** 面板中设置：

**表 7-1 软件 I2C 的 GPIO 参数（PB6=SCL、PB7=SDA 相同配置）**

| 配置项 | 取值 | 说明 |
| --- | --- | --- |
| GPIO output level | High | 初始化为高电平，总线处于空闲态 |
| GPIO mode | **Output Open Drain** | 开漏，I2C 的硬性要求 |
| GPIO Pull-up/Pull-down | Pull-up | 配合外部上拉，双保险 |
| Maximum output speed | Very High | 时序更陡，高速率下波形更规整 |
| User Label | `I2C_SCL` / `I2C_SDA` | 起个别名，代码可读 |

3. 重新 **GENERATE CODE**，CubeMX 会在 `gpio.c` 的 `MX_GPIO_Init()` 中生成 PB6/PB7 的初始化。

> 📷 图 7-1 GPIO 面板中把 PB6/PB7 设为 Output Open Drain + Pull-up（此处可插入截图）

列表 8: 代码清单 7-1 CubeMX 为软件 I2C 生成的 GPIO 初始化

```c
/* gpio.c */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOB_CLK_ENABLE();

  /* 软件 I2C 的 SCL / SDA：开漏输出 + 上拉，初始高电平（总线空闲） */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_SET);

  GPIO_InitStruct.Pin   = GPIO_PIN_6 | GPIO_PIN_7;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_OD;   /* 开漏，I2C 必须 */
  GPIO_InitStruct.Pull  = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
}
```

### 7.3 软件设计

#### 7.3.1 编程要点

1. **把电平操作写成宏**，让上层时序代码贴近"拉高 SCL / 拉低 SDA"的自然语义；读 SDA 用 `HAL_GPIO_ReadPin()`——STM32 的输入数据寄存器（IDR）**在任何模式下都在采样引脚电平**，所以开漏输出模式下同样可以直接读回引脚状态，无需来回切换输入/输出方向；
2. **延时决定速率**。软件 I2C 用空循环产生半周期延时，循环次数需要按主频实测调整：延时过长速率低但稳，过短则从机来不及响应；
3. **严格遵循"数据只能在 SCL 为低时变化"**的规则，`I2C_SendByte()` 里先拉低 SCL、放数据、再拉高 SCL 让从机采样；
4. 起始/停止信号是"SCL 高时 SDA 跳变"的例外，必须在 SCL 已经为高的状态下改变 SDA；
5. 读完最后一个字节必须回 **NACK**，然后发停止信号。

#### 7.3.2 代码分析

列表 9: 代码清单 7-2 电平操作宏与延时（bsp_soft_i2c.h）

```c
/* bsp_soft_i2c.h —— 软件模拟 I2C 接口 */
#ifndef __BSP_SOFT_I2C_H
#define __BSP_SOFT_I2C_H

#include "stm32f4xx_hal.h"

/* 引脚定义：SCL = PB6，SDA = PB7 */
#define SOFT_I2C_GPIO_PORT   GPIOB
#define SOFT_I2C_SCL_PIN     GPIO_PIN_6
#define SOFT_I2C_SDA_PIN     GPIO_PIN_7

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

列表 10: 代码清单 7-3 半周期延时

```c
/* bsp_soft_i2c.c */
#include "bsp_soft_i2c.h"

/**
  * @brief  软件 I2C 半周期延时
  * @note   168MHz 主频下循环 20 次约 1µs，SCL 周期约 2µs ≈ 500kHz 上限，
  *         实际速率受上升沿限制，实测波形落在 100~400kHz 之间。
  *         要降低速率（更稳）就加大循环次数，例如调到 100 变为约 100kHz。
  */
static void I2C_Delay(void)
{
  for (volatile uint8_t i = 0; i < 20; i++)
  {
    __NOP();
  }
}
```

列表 11: 代码清单 7-4 起始信号、停止信号与字节收发

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
  * @retval 1 = 收到 ACK，0 = 收到 NACK
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

列表 12: 代码清单 7-5 基于软件 I2C 的 AT24C02 读写

```c
/* 器件地址：7 位 0x50，8 位形式 0xA0(写) / 0xA1(读) */
#define AT24C02_ADDR_W   0xA0
#define AT24C02_ADDR_R   0xA1
#define AT24C02_PAGESIZE 8

/**
  * @brief  向 AT24C02 写 1 字节
  * @note   时序：START + 器件地址(W) + ACK + 存储地址 + ACK + 数据 + ACK + STOP
  */
void AT24C02_WriteByte(uint8_t memAddr, uint8_t data)
{
  I2C_Start();
  I2C_SendByte(AT24C02_ADDR_W);   /* 器件地址 + 写 */
  I2C_WaitAck();
  I2C_SendByte(memAddr);          /* 片内存储地址 */
  I2C_WaitAck();
  I2C_SendByte(data);             /* 数据 */
  I2C_WaitAck();
  I2C_Stop();

  HAL_Delay(5);                   /* 等待 EEPROM 内部写周期 tWR（≤5ms） */
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

列表 13: 代码清单 7-6 软件 I2C 测试主程序

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
  MX_GPIO_Init();             /* 其中包含 PB6/PB7 开漏输出配置 */
  MX_USART1_UART_Init();

  printf("\r\n===== STM32F407VET6 软件 I2C 读写 AT24C02 =====\r\n");

  /* 准备数据：0xA0 ~ 0xAF，与硬件 I2C 实验的数据区分开 */
  for (i = 0; i < SOFT_DATA_SIZE; i++)
  {
    sw_write_buf[i] = (uint8_t)(0xA0 + i);
  }

  /* 写入 0x10 起始的两页（每页 8 字节，不跨页） */
  AT24C02_PageWrite(0x10, &sw_write_buf[0], 8);
  AT24C02_PageWrite(0x18, &sw_write_buf[8], 8);
  printf("软件 I2C 写入完成\r\n");

  /* 读回比对 */
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

> **调试提示**：软件 I2C 出问题时的排查顺序是"**先看波形、再看时序、最后看代码**"。用逻辑分析仪或示波器抓 SCL/SDA，重点确认三件事：① 起始/停止信号里 SDA 是否确实在 SCL 高电平期间跳变；② 第 9 个时钟从机有没有把 SDA 拉低（没有低电平就说明地址错了或器件没上电）；③ 上拉电阻是否真的存在（把 SDA 释放后线能不能回到高电平）。**线拉不到高电平几乎一定是上拉电阻缺失或阻值过大。**

#### 7.3.3 下载验证

编译下载，串口应输出：

```
===== STM32F407VET6 软件 I2C 读写 AT24C02 =====
软件 I2C 写入完成
0xA0 0xA1 0xA2 0xA3 0xA4 0xA5 0xA6 0xA7
0xA8 0xA9 0xAA 0xAB 0xAC 0xAD 0xAE 0xAF
软件 I2C (AT24C02) 读写测试成功
```

**交叉验证技巧**：把软件 I2C 写进 0x10~0x1F 的数据，改由**实验一的硬件 I2C 驱动**去读（地址一致、数据也在同一片 EEPROM 里），能读到 0xA0~0xAF，就证明两套实现操作的是同一个真实的 I2C 器件，协议时序都是正确的。

---

## 8. 实验三：软件 I2C 驱动 MPU6050（验证通用性）

**实验目标**：把上一节的软件 I2C 时序层（`I2C_Start/SendByte/WaitAck/ReadByte`）原封不动复用，只换上层"寄存器读写"，就能驱动完全不同的器件 MPU6050，读取 `WHO_AM_I` 寄存器确认器件存在，并周期读取三轴加速度。这体现了 I2C 驱动的分层设计：**时序层与器件层分离**。

### 8.1 硬件设计

MPU6050 的 SCL/SDA 同样接 PB6/PB7（与上一节共用总线，两个器件地址不同，互不干扰，**这正是 I2C 总线的价值**）。AD0 引脚接地时，7 位地址为 `0x68`，8 位写地址为 `0xD0`。

> **注意**：MPU6050 属于 400kHz 器件，用软件 I2C 时若延时过短导致速率过高会读不出数据，可把 `I2C_Delay()` 的循环次数调大降低速率。同时 MPU6050 模块自带上拉电阻，与 AT24C02 的上拉并联后阻值会变小，总线上拉会更强，一般仍可正常工作。

### 8.2 软件设计

列表 14: 代码清单 8-1 MPU6050 寄存器读写（复用软件 I2C 时序层）

```c
/* bsp_mpu6050.h */
#define MPU6050_ADDR_W        0xD0   /* 0x68<<1 | 0 */
#define MPU6050_ADDR_R        0xD1
#define MPU6050_RA_WHO_AM_I   0x75   /* 器件 ID 寄存器，固定返回 0x68 */
#define MPU6050_RA_PWR_MGMT_1 0x6B   /* 电源管理 1 */
#define MPU6050_RA_SMPLRT_DIV 0x19   /* 采样率分频 */
#define MPU6050_RA_CONFIG     0x1A   /* 配置（DLPF） */
#define MPU6050_RA_GYRO_CONFIG 0x1B  /* 陀螺仪量程 */
#define MPU6050_RA_ACCEL_CONFIG 0x1C /* 加速度量程 */
#define MPU6050_RA_ACCEL_XOUT_H 0x3B /* 加速度数据起始寄存器 */
```

列表 15: 代码清单 8-2 通用寄存器读写与初始化

```c
/* bsp_mpu6050.c */
#include "bsp_soft_i2c.h"
#include "bsp_mpu6050.h"

/**
  * @brief  写器件寄存器：START + 地址(W) + ACK + 寄存器号 + ACK + 数据 + ACK + STOP
  */
void MPU6050_WriteReg(uint8_t reg, uint8_t data)
{
  I2C_Start();
  I2C_SendByte(MPU6050_ADDR_W);
  I2C_WaitAck();
  I2C_SendByte(reg);
  I2C_WaitAck();
  I2C_SendByte(data);
  I2C_WaitAck();
  I2C_Stop();
}

/**
  * @brief  读器件寄存器：写寄存器号后用 Sr 转读方向
  */
uint8_t MPU6050_ReadReg(uint8_t reg)
{
  uint8_t data;

  I2C_Start();
  I2C_SendByte(MPU6050_ADDR_W);
  I2C_WaitAck();
  I2C_SendByte(reg);
  I2C_WaitAck();

  I2C_Start();                 /* 重复起始 Sr */
  I2C_SendByte(MPU6050_ADDR_R);
  I2C_WaitAck();

  data = I2C_ReadByte();
  I2C_SendAck(0);              /* 只读 1 字节，回 NACK */
  I2C_Stop();

  return data;
}

/**
  * @brief  连续读取多个寄存器（地址自动递增，用于读三轴数据）
  */
void MPU6050_ReadRegs(uint8_t reg, uint8_t *buf, uint8_t len)
{
  uint8_t i;

  I2C_Start();
  I2C_SendByte(MPU6050_ADDR_W);
  I2C_WaitAck();
  I2C_SendByte(reg);
  I2C_WaitAck();

  I2C_Start();
  I2C_SendByte(MPU6050_ADDR_R);
  I2C_WaitAck();

  for (i = 0; i < len; i++)
  {
    buf[i] = I2C_ReadByte();
    I2C_SendAck((i == (len - 1)) ? 0 : 1);   /* 最后一字节回 NACK */
  }
  I2C_Stop();
}

/**
  * @brief  初始化 MPU6050
  */
void MPU6050_Init(void)
{
  HAL_Delay(50);                                  /* 上电稳定 */
  MPU6050_WriteReg(MPU6050_RA_PWR_MGMT_1, 0x00);  /* 解除休眠 */
  MPU6050_WriteReg(MPU6050_RA_SMPLRT_DIV, 0x07);  /* 采样率 1kHz/(1+7)=125Hz */
  MPU6050_WriteReg(MPU6050_RA_CONFIG, 0x06);      /* DLPF 5Hz */
  MPU6050_WriteReg(MPU6050_RA_ACCEL_CONFIG, 0x00);/* ±2g */
  MPU6050_WriteReg(MPU6050_RA_GYRO_CONFIG, 0x18); /* ±2000°/s */
  HAL_Delay(100);
}

/**
  * @brief  读取器件 ID
  * @retval 1 = 器件正常，0 = 未检测到
  */
uint8_t MPU6050_ReadID(void)
{
  uint8_t id = MPU6050_ReadReg(MPU6050_RA_WHO_AM_I);
  return (id == 0x68) ? 1 : 0;
}

/**
  * @brief  读取三轴加速度原始值（高字节在前，有符号 16 位）
  */
void MPU6050_ReadAcc(short *accData)
{
  uint8_t buf[6];

  MPU6050_ReadRegs(MPU6050_RA_ACCEL_XOUT_H, buf, 6);
  accData[0] = (short)((buf[0] << 8) | buf[1]);   /* X */
  accData[1] = (short)((buf[2] << 8) | buf[3]);   /* Y */
  accData[2] = (short)((buf[4] << 8) | buf[5]);   /* Z */
}
```

列表 16: 代码清单 8-3 主程序

```c
int main(void)
{
  short acc[3];

  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_USART1_UART_Init();

  printf("\r\n===== 软件 I2C 驱动 MPU6050 =====\r\n");

  MPU6050_Init();
  if (MPU6050_ReadID() == 0)
  {
    printf("错误：未检测到 MPU6050，请检查接线与上拉电阻\r\n");
    while (1);
  }
  printf("MPU6050 检测正常\r\n");

  while (1)
  {
    MPU6050_ReadAcc(acc);
    printf("ACC: X=%6d  Y=%6d  Z=%6d\r\n", acc[0], acc[1], acc[2]);
    HAL_Delay(500);
  }
}
```

**分析**：

- 上下层的分工非常清晰：`bsp_soft_i2c.c` 只负责"起止、收发字节、应答"，**完全不知道从机是谁**；`bsp_mpu6050.c` 只负责"往哪个寄存器写什么"，**完全不关心电平怎么翻转**。换器件时只改上层，换引脚/换芯片（比如搬到 STM32F103）时只改时序层的宏和延时；
- 静止平放时，Z 轴约等于 +1g 对应的原始值（±2g 量程下 16384 LSB/g，即约 16384），X、Y 接近 0，这就是判断"读到的数据是否可信"的常识性依据；
- 同一份 `bsp_soft_i2c.c` 稍加改动即可驱动 OLED、温度传感器、EEPROM 等任何 I2C 器件，这就是掌握软件 I2C 的回报。

---

## 9. 软硬件 I2C 对比与选型

两种实现方式在**协议层完全一致**（都遵守起始/停止/应答规则），差别在"谁来产生时序"。

**表 9-1 硬件 I2C 与软件 I2C 对比**

| 对比项 | 硬件 I2C（片上 I2C 外设） | 软件 I2C（GPIO 模拟） |
| --- | --- | --- |
| 时序产生者 | 硬件状态机，自动产生 SCL、自动收发移位 | CPU 用 GPIO 翻转 + 延时循环 |
| CPU 占用 | 低（阻塞模式下仍需等待；DMA/中断下极低） | 高（全程占用 CPU 空转延时） |
| 速率 | 稳定 100k/400kHz，与主频无关 | 由延时循环决定，受主频、中断影响，**速率不稳定** |
| 引脚要求 | 必须是外设规定的复用引脚（AF4） | **任意 GPIO**，布线自由，可绕开引脚冲突 |
| 资源占用 | 占用一个 I2C 外设（F4 只有 3 个） | 只占 2 个 GPIO，可复制出多路 I2C |
| 抗干扰 | 好，硬件自动处理时钟延展、仲裁 | 差，一旦被中断打断会拉长时钟（多数器件可容忍） |
| 中断中的表现 | 需要中断/DMA 配合，纯阻塞在中断里不可用 | 时序容易被中断打断，不适合在中断中调用 |
| 已知问题 | F4 的 I2C 存在总线死锁/BUSY 卡死的勘误，需要软件恢复 | 无外设缺陷，时序全在自己手里，出问题好定位 |
| 代码量 | 少（调 HAL 库函数即可） | 多（需自己实现完整时序层） |
| 移植性 | 换芯片系列需注意结构体差异（ClockSpeed vs Timing） | **极好**，任何有 GPIO 的 MCU 都能用 |
| 调试难度 | 黑盒，只能看返回值和状态寄存器 | 白盒，配合示波器/逻辑分析仪一目了然 |
| 典型适用 | 产品开发、高速率、多器件、低功耗场合 | 教学、引脚受限、多路 I2C、驱动难伺候的器件 |

**选型建议**：

- **优先用硬件 I2C**：产品开发中，硬件 I2C 配合 DMA 是标准做法，CPU 占用低、速率稳定、代码量少；
- **遇到坑就用软件 I2C**：① STM32 F4 的 I2C 在某些工况下会出现 `BUSY` 位卡死（官方有相关勘误），若一时无法恢复，换成软件 I2C 立刻绕开；② 硬件 I2C 引脚与其它外设冲突（例如两个 I2C 器件需要挂到不同总线但只有一个 I2C 外设可用）；③ 某些从机器件时序不规范，硬件外设"太标准"反而不兼容，用软件 I2C 可以慢慢把时序调宽以迁就它；
- **学习阶段两个都要写一遍**：先写软件 I2C 把协议吃透，再用硬件 I2C 体会外设的便利，这样遇到问题才有判断力。

---

## 10. 扩展：总线死锁恢复、DMA 与从机模式

### 10.1 I2C 总线死锁与恢复

**现象**：`HAL_I2C_Master_Transmit()` 一直返回 `HAL_BUSY` 或超时，`I2C_SR2` 的 `BUSY` 位一直为 1，即使断电重启从机也不能恢复。

**原因**：主从通讯被意外中断（例如复位、上电时序错位），从机正输出数据位 "0" 把 SDA 拉低并等待时钟，而主机已经不再发时钟——**从机抱着 SDA 不放，总线永久被占**。

**恢复原理**：主机手动发最多 9 个 SCL 时钟，让从机把剩余的位发完，再补一个停止条件，从机就会释放总线。

列表 17: 代码清单 10-1 硬件 I2C 总线死锁恢复

```c
/**
  * @brief  硬件 I2C 总线死锁恢复
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

> 这段代码也解释了为什么"软件 I2C 更皮实"：它本来就一直用 GPIO 在翻转，**不存在外设状态机卡死的概念**，出问题只可能是代码逻辑或硬件上拉。

### 10.2 DMA 方式传输

需要批量搬运 EEPROM 数据（或高速读取传感器）时，用 DMA 可以把 CPU 从逐字节等待中解放出来：

1. CubeMX 的 **DMA Settings** 中为 I2C1 添加 **I2C1_TX** 与 **I2C1_RX** 通道，Mode 选 Normal，数据宽度 Byte，优先级 Medium；
2. 调用 `HAL_I2C_Mem_Write_DMA()` / `HAL_I2C_Mem_Read_DMA()` 启动传输，函数立即返回；
3. 传输完成触发回调 `HAL_I2C_MemTxCpltCallback()` / `HAL_I2C_MemRxCpltCallback()`，在回调里置标志位通知主循环；
4. **注意**：DMA 完成回调只表示数据搬运结束，**AT24C02 的内部写周期仍需单独等待**。

### 10.3 STM32 作为 I2C 从机

STM32 的 I2C 也能当从机（例如让 F407 作为一块"传感器板"被另一块主板读取）：

1. CubeMX 中把 I2C1 的 **Own Address 1** 填成自己的从机地址（不能为 0），Addressing Mode 保持 7-bit；
2. 调用 `HAL_I2C_Slave_Receive_IT(&hi2c1, buf, len)` 挂起接收，收到主机数据后触发 `HAL_I2C_SlaveRxCpltCallback()`；
3. 从机的时钟由主机提供，因此**从机模式下 `ClockSpeed` 已不决定实际速率**，但仍需配置合法值。

### 10.4 时钟延展（Clock Stretching）

部分从机（如某些 EEPROM、传感器）处理不过来时会**主动把 SCL 拉低**，强制主机等待，这叫时钟延展。STM32 的 I2C 外设本身支持，CubeMX 中 **No Clock Stretch** 保持 `Clock stretching enabled`（即 `I2C_NOSTRETCH_DISABLE`）即可。软件 I2C 若想支持延展，需要在拉高 SCL 后**读回 SCL 电平**，直到它真的变高再继续——大多数简单驱动省略了这一步，遇到需要延展的器件就会失败。

---

## 11. 本章小结

1. I2C 分物理层（SDA/SCL 两线、开漏+上拉实现"线与"、总线电容 ≤400pF、100k/400k 速率）和协议层（起始 S、重复起始 Sr、地址+R/W、应答 ACK/NACK、数据、停止 P，**数据只能在 SCL 低电平时变化，SCL 高电平时必须稳定**）。
2. F407VET6 有 I2C1/I2C2/I2C3 三个外设，**全部挂 APB1（42MHz）、全部用 AF4**；常用 I2C1 = PB8/PB9（或 PB6/PB7），I2C2 = PB10/PB11，I2C3 = PA8/PC9（VET6 无 PH 口）。
3. 内部结构核心：**CCR** 决定 SCL 频率（标准模式 1:1，快速模式 2:1 或 16:9）、DR 收发数据、OAR 做从机地址、SR1/SR2 指示 EV5/EV6/EV7/EV8 状态机进程。频率不用手算，CubeMX 填 ClockSpeed 即可。
4. **F4 用 `I2C_InitTypeDef.ClockSpeed` + `DutyCycle`，F7/L4/H7 用 `Timing`**，照抄教程时务必确认芯片系列。
5. 硬件 I2C 实验（AT24C02）：`HAL_I2C_Mem_Write/Read` 一把梭，**关键是每次写完必须等 5ms 内部写周期**（用 `HAL_I2C_IsDeviceReady` 轮询），写超过 8 字节必须按页拆分。
6. 软件 I2C 实验：两个 GPIO 配 **开漏输出 + 上拉**，用宏控制电平、空循环产生延时，自己实现起始/停止/发送/等待应答/读字节五个基础函数，就能驱动任何 I2C 器件；**STM32 在开漏输出下仍可通过 IDR 读回引脚电平**。
7. 分层的价值：软件 I2C 的"时序层"与"器件层"分离，同一份时序代码既驱动 AT24C02 又驱动 MPU6050。
8. 选型结论：产品优先硬件 I2C（低 CPU 占用、稳定、可用 DMA）；遇到 F4 的 I2C 死锁卡死、引脚冲突、器件时序不规范时，改用软件 I2C 往往最省事。

## 12. 常见问题速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| `HAL_I2C_IsDeviceReady` 一直失败 | 器件没上电、地址错、**上拉电阻缺失** | 量 SDA/SCL 空闲时是否被拉到 3.3V；核对 7 位/8 位地址换算 |
| 写 EEPROM 偶发失败（AF 应答失败） | 没等 5ms 内部写周期 | 每次写后用 `HAL_I2C_IsDeviceReady` 轮询到应答再继续 |
| 写超过 8 字节后数据错乱 | 跨页写回卷覆盖 | 按 8 字节页边界拆分写入 |
| 读只能读到第一个字节，之后全 0xFF | 读完没回 NACK 或没发停止信号 | 最后一个字节 `I2C_SendAck(0)` 后 `I2C_Stop()` |
| 波形上升沿是斜坡、读不到数据 | 内部弱上拉不够 / 上拉阻值过大 | 加 4.7kΩ（高速用 2.2kΩ）外部上拉 |
| SDA 被从机拉住不放、`BUSY` 一直为 1 | 总线死锁 | 调 `I2C_BusRecover()` 手动补 9 个时钟 + 停止条件 |
| 软件 I2C 在中断里调用后通讯乱掉 | 时序被更高级中断打断，时钟被拉长 | 不要在中断中调用软件 I2C；或调用期间关中断 |
| 编译报错找不到 `Init.Timing` / `I2C_InitTypeDef` 成员不匹配 | 抄了 F7/L4 的代码 | F4 用 `ClockSpeed` + `DutyCycle` |
| 从机地址对不上（0x50 还是 0xA0） | 7 位地址与 8 位地址混淆 | **HAL API 传 8 位形式**：0x50→0xA0(写)/0xA1(读) |
| 重新生成代码后自己的驱动丢失 | 代码写在 CubeMX 管理区 | 所有手写代码放进 `USER CODE BEGIN/END`，或单独建 `bsp_xxx.c/h` |
| 多器件挂在同一总线上互相干扰 | 器件地址冲突 | 用 A0/A1/A2 引脚改地址，确保总线上地址唯一 |
| 硬件 I2C 与软件 I2C 数据不一致 | 其中一个实验的上拉/地址/页边界处理有误 | 用实验一的硬件驱动去读实验二写的数据做交叉验证 |
