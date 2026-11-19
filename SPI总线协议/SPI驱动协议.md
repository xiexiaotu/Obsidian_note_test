# SPI 驱动协议——SPI1 分时复用读写 W25Q64 FLASH 与 TF 卡（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F4xx 中文数据手册》SPI 引脚复用表、《RM0090 STM32F407 参考手册》SPI/I2S 章节、《W25Q64FV 数据手册》（指令集与时序）、《SD Specifications Part 1 Physical Layer Simplified Specification》（SPI 模式），以及野火《STM32 HAL 库开发实战指南——基于霸天虎开发板》**第 24 章 SPI-读写串行 FLASH**（本章的协议讲解、指令表与驱动写法以此为基础改写，并扩展到"一条 SPI1 驱动两个器件"）。
> **学习提示**：配合参考手册中 `SPI_CR1`（CPOL/CPHA/MSTR/BR/SPE/SSI/DFF）、`SPI_CR2`（中断与 DMA 使能）、`SPI_SR`（TXE/RXNE/BSY/OVR/MODF）三个寄存器的说明一起阅读，效果更佳。
> **特别说明**：本笔记以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 **STM32 HAL 库**，所有实验结果**通过 USART1 + printf 输出到串口助手**（115200-8-N-1）。
> **本项目的两件被驱动对象与引脚**：
> ① **W25Q64**（8MB 串行 NOR FLASH）：`PA15`=CS、`PB3`=SCK、`PB4`=MISO、`PB5`=MOSI；
> ② **TF 卡（microSD）**：`PA4`=CS、`PA5`=SCK、`PA6`=MISO、`PA7`=MOSI。
> **两个器件全部挂在 SPI1 上（统一 AF5）**——这是本项目的核心约束，也是全篇的技术主线。
> **重要预警**：SPI1 的 SCK 输出信号**只能从 PA5 或 PB3 二者之一引出去**，绝不可能同时从两组引脚输出。所以"都用 SPI1"在工程上的正确落地方式是 **SPI1 分时复用（Time-Division Multiplexing）**：同一时刻只让一组引脚接上 SPI1，用谁就把谁接上。本笔记在"任务一的环节二"把这道题彻底讲透，并在"任务五"给出 **SPI1 分时复用总线层**的完整实现。**请务必按顺序读，不要跳到代码。**

---

> **笔记结构说明（五级组织法）**
> 本笔记按 **项目（一级标题）→ 任务（二级标题）→ 环节（三级标题）→ 技能点（四级标题）→ 知识点（五级标题）** 逐层拆解。
> ① 一级只有 1 个，就是"项目"本身；
> ② 二级是 10 个可独立验收的"任务"，按"**认知 → 建工程 → 造总线层 → 驱动 FLASH → 驱动 TF 卡 → 集成收尾**"由浅入深排列；
> ③ 三级本应叫"工序"，但本项目是"先设计、再编码、后验证"的软件开发流程，叫工序（偏制造语境）不够贴切，**故全文统一用"环节"替代"工序"**；
> ④ 四级"技能点"回答"**这一步要会做什么**"，五级"知识点"回答"**为什么这么做**"。

---

## 项目全景：一图看懂本笔记的任务链

```
                    ┌──────────────────────────────────────────────┐
   项目 SPI-STORAGE │  用一条 SPI1，分时驱动两片存储器件             │
                    └───────────────────┬──────────────────────────┘
                                        │
   任务一 导入与拆解 ──────────────────►│  需求 → 引脚约束 → 分时复用定案
   任务二 协议认知   ──────────────────►│  四根线 + 四种模式 + 速率账
   任务三 外设认知   ──────────────────►│  框图 + 寄存器 + HAL 句柄
   任务四 工程搭建   ──────────────────►│  CubeMX：SPI1 + 双片选 + USART1
   任务五 SPI1 总线层 ─────────────────►│  ★ AF 切换 + 模式切换（核心）
   任务六 FLASH 驱动 ──────────────────►│  指令集 + 擦 + 写 + 读（完整代码）
   任务七 FLASH 联调 ──────────────────►│  读 ID + 回环校验 + 掉电保持
   任务八 TF 卡驱动  ──────────────────►│  CMD0→CMD8→ACMD41→CMD58（完整代码）
   任务九 TF 卡读写  ──────────────────►│  CMD17 读块 / CMD24 写块
   任务十 集成与收尾 ──────────────────►│  共存调度 + 容错 + 验收清单
```

**表 0-1 本项目任务清单与验收标准**

| 任务 | 名称 | 一句话目标 | 验收标准 |
| --- | --- | --- | --- |
| 一 | 项目导入与需求拆解 | 把需求翻译成引脚、外设与验收指标 | 产出 SPI1 分时复用的引脚分配表 |
| 二 | SPI 协议认知 | 说清物理层与协议层 | 能画出模式 0/3 的时序并说明采样沿 |
| 三 | STM32 SPI 外设认知 | 看懂框图、寄存器与 HAL 封装 | 能默写主机收发四步流程 |
| 四 | CubeMX 工程搭建 | 生成可编译的工程骨架 | CubeMX 无引脚告警、编译 0 错误 |
| 五 | **SPI1 分时复用总线层** | 用一套 API 在两组引脚间安全切换 | 切换前后读 ID 均正确 |
| 六 | W25Q64 驱动开发 | 提供**完整可编译**的驱动文件 | `bsp_w25q64.c` 全部函数实现 |
| 七 | W25Q64 联调验证 | 串口打印回环与掉电校验结果 | 校验一致、断电后数据完好 |
| 八 | TF 卡 SPI 初始化 | 把卡从 SD 模式切到 SPI 模式 | `TF_Init()` 返回 0 并识别寻址方式 |
| 九 | TF 卡扇区读写 | 单块读、单块写 | 512 字节回环校验一致 |
| 十 | 项目集成与收尾 | 双器件共存、容错、可维护 | 交替读写 100 次全部正确 |

---

## 任务一　项目导入与需求拆解

> **本任务的目标**：先不动代码，把"要做成什么样"想清楚。**嵌入式项目里 80% 的返工来自引脚与外设没提前核对**，这一步做好了，后面写代码是顺水推舟。

### 环节一　读任务书：把功能需求翻译成验收标准

#### 技能点 1　明确"通得上、写得进、掉电不丢"三条验收线

##### 知识点 1　功能需求的三个层次

一个"能读写 FLASH"的项目，需求其实分三层，很多初学者只做到第一层就以为完工了：

**表 1-1 需求的三层拆解**

| 层次 | 需求描述 | 对应验收动作 | 常见"假完成" |
| --- | --- | --- | --- |
| 第一层：**通得上** | 总线能收到芯片应答 | 读 JEDEC ID 与手册比对 | ID 读出来是 `0xFF`，靠"重插一下"蒙过去 |
| 第二层：**写得进、读得出** | 数据能落到存储介质并能原样取回 | 写一段数据 → 读回 → 逐字节比对 | 只打印了"写入成功"，没做回环比对 |
| 第三层：**掉电不丢** | 断电重启后数据仍然在 | 写完断电 10s 再上电读取 | 写进了 RAM 缓冲区，压根没落盘 |

> **为什么强调第三层**：FLASH 的全部价值就在"非易失"。本项目的验收脚本必须包含"**断电重启后重新读一遍**"这一步——它能一次性筛掉"缓存没落盘""擦除没生效""写保护位没清"这三类隐蔽 bug。

##### 知识点 2　两块存储介质的角色分工

W25Q64 是**裸 FLASH 芯片**，TF 卡是**带控制器的可插拔存储卡**，二者看似都是"存数据"，工程定位完全不同：

**表 1-2 W25Q64 与 TF 卡的分工**

| 维度 | W25Q64（片外 NOR FLASH） | TF 卡（microSD） |
| --- | --- | --- |
| 介质本质 | 裸 NOR FLASH 阵列 | NAND FLASH + **卡内控制器**（含坏块管理与磨损均衡） |
| 容量 | 8 MB，焊接在板上 | 常见 8GB~512GB，可插拔更换 |
| 访问单位 | 1 字节可读，写必须按页（256B），擦必须按扇区（4KB） | 一律 512 字节一个"块" |
| 协议 | **纯 SPI 硬件时序**，无状态机 | **SPI 物理层 + 一套命令状态机** |
| 谁管坏块 | **用户程序自己管** | 卡内控制器管，用户看不到 |
| 典型用途 | 存参数、字库、图片（小容量高频读写） | 存文件、录音、图片（大容量，配文件系统） |

> **一句话记住分工**：**W25Q64 适合"程序自己直接管地址"的场景，TF 卡适合"交给文件系统管"的场景。**
> **两者的难度差一个数量级**：W25Q64 只要发对指令就能工作；TF 卡上电后是个"懵的"状态机，必须用 CMD0/CMD8/ACMD41/CMD58 一路"唤醒+协商"才能读写数据。**这是本笔记把 FLASH 放在 TF 卡前面的原因。**

#### 技能点 2　从需求里提取硬约束

##### 知识点 1　引脚是硬约束

在 STM32 上，"用哪个引脚"往往在画板那一刻就焊死了，软件改不了；而"跑多快"是可以在代码里调的。所以拆解需求时，**先锁死引脚，再谈速率**。

本项目的硬约束清单：

1. **W25Q64 固定接 PA15、PB3、PB4、PB5**；
2. **TF 卡固定接 PA4、PA5、PA6、PA7**；
3. **两个器件都只能走 SPI1**——用户已定，不考虑 SPI2/SPI3；
4. **调试口必须保留**——否则程序跑飞了没法下载，这条比前三条更"硬"。

##### 知识点 2　容量的算法：8MB 从哪来

W25Q64 的名字里藏着容量：**64 = 64 Mbit**，换算成字节要除以 8：

```
W25Q64 容量 = 64 Mbit ÷ 8 = 8 MByte = 8 × 1024 × 1024 = 8 388 608 字节
```

由容量派生出存储组织的全部数字（**这张表要背下来，写驱动时会反复用**）：

**表 1-3 W25Q64 的存储组织**

| 单位 | 大小 | 数量 | 首地址范围 | 用途 |
| --- | --- | --- | --- | --- |
| 页（Page） | 256 B | 32 768 页 | 0x000000 ~ 0x7FFF00 | **写操作的最小单位**（页写一次最多 256B） |
| 扇区（Sector） | 4 KB | 2 048 个 | 0x000000 ~ 0x7FF000 | **擦除的最小单位**（扇区擦除指令 0x20） |
| 块（Block） | 64 KB | 128 个 | 0x000000 ~ 0x7F0000 | 大块擦除（块擦除指令 0xD8），1 块 = 16 扇区 |
| 整片（Chip） | 8 MB | 1 片 | 0x000000 ~ 0x7FFFFF | 整片擦除（0xC7），耗时几十秒 |

> **为什么要 24 位地址**：8MB = 2²³ 字节，用 A23~A0 共 24 位地址刚好覆盖（最高地址 0x7FFFFF）。所以 W25Q64 的地址一律按 **3 字节、高位在前** 发送。

---

### 环节二　直面核心矛盾：两个器件如何共用一个 SPI1

#### 技能点 1　先看清 F407 的 SPI 资源

##### 知识点 1　STM32F407VET6 的 SPI 引脚映射

F407 有 **3 个 SPI 外设**：SPI1 挂在 **APB2（PCLK2 = 84MHz）**，SPI2/SPI3 挂在 **APB1（PCLK1 = 42MHz）**。SCK 的最高频率是所在总线时钟的 1/2，所以 **SPI1 最快 42MHz，SPI2/SPI3 最快 21MHz**。

**表 1-4 STM32F407VET6 的 SPI 引脚映射（LQFP100 可用引脚）**

| 外设 | 所在总线 | 最高 SCK | NSS（片选） | SCK | MISO | MOSI |
| --- | --- | --- | --- | --- | --- | --- |
| **SPI1** | APB2（84MHz） | 42 MHz | **PA4 / PA15** | **PA5 / PB3** | **PA6 / PB4** | **PA7 / PB5** |
| SPI2 | APB1（42MHz） | 21 MHz | PB12 / PB9 | PB13 / PB10 | PB14 / PB11 / PC2 | PB15 / PB12 / PC3 |
| SPI3 | APB1（42MHz） | 21 MHz | PA15 / PA4 | PB3 / PC10 | PB4 / PC11 | PB5 / PC12 |

> **注意 SPI1 那一行写了两组引脚**：第一组 `PA4/PA5/PA6/PA7`，第二组 `PA15/PB3/PB4/PB5`。**本项目的两个器件恰好各占一组**——这正是矛盾的根源，也是解法的钥匙。

##### 知识点 2　AF5：两组引脚共用同一个复用编号

STM32 的引脚是"复用"的：同一个物理引脚，靠寄存器里写入的 **AF 编号** 决定它此刻听谁指挥。F407 上 **SPI1/SPI2/SPI4/SPI5/SPI6 全部是 AF5**（只有 SPI3 是 AF6）。

所以本项目**两组引脚都写 AF5**，这一点不会错。真正的问题是：**共用一个外设，但引脚位置不同**。

#### 技能点 2　为什么"都用 SPI1"不能简单并接

##### 知识点 1　一个 SPI 外设只有一套 SCK 输出

这是全篇最重要的一条硬件事实：

> **SPI1 外设内部只有一路 `SPI1_SCK` 信号。这个信号经过 GPIO 的复用选择器，最终只能被送到 `PA5` 或 `PB3` 中的一个引脚上，不可能同时送到两个。**

```
                     ┌──────────────┐
   SPI1 外设内部      │  SCK  ───────┼──┐
   （每个信号只有     │  MISO ───────┼──┤  AF5 复用选择器
     一路物理线路）   │  MOSI ───────┼──┤  （每个引脚独立选）
                     └──────────────┘  │
                          ┌────────────┴────────────┐
                          ▼                         ▼
                     PA5 (AF5)                 PB3 (AF5)
                        │                         │
                    TF 卡 SCK                 W25Q64 SCK
```

**"两组都配成 AF5 就行了"是错的**：SCK/MOSI 是输出，信号也许能同时广播到两个脚（取决于具体实现），但 **MISO 是输入**——`SPI1_MISO` 的输入选择器**只能从其中一个引脚取样**。两个器件同时往各自的 MISO 上驱动数据时，主机读到的就是"取样脚"上的值，另一组数据完全丢失；更糟的是两条 MISO 若被并联（某些开发板确实这么走线），两个推挽输出会**直接对打**。

**这不是配置问题，是硬件结构决定的。**

##### 知识点 2　四种方案的可行性分析

**表 1-5 让两个器件共用 SPI1 的四种方案**

| 方案 | 做法 | 可行性 | 代价 |
| --- | --- | --- | --- |
| A：两组引脚同时配 AF5 | PA5/PB3 都设 AF5 | ❌ **不可行** | MISO 输入冲突，读回数据随机甚至对打 |
| **B：分时复用 SPI1** | **用谁就把谁接上（切 AF + 切模式）** | ✅ **本项目采用** | 每次切换约 2~5µs；两器件不能真正并行 |
| C：加外部模拟开关 | 74HC4053 / 74HC139 切换总线 | ⚠️ 可行但需改板 | 增加芯片、成本、故障点 |
| D：一个挪到 SPI3 | W25Q64 走 SPI3（PB3~PB5 支持 AF6） | ✅ 但违背需求 | 用户明确要求都用 SPI1，不采用 |

> **方案 B 的本质**：把"硬件并行"换成"软件分时"。**同一时刻总线上只有一组引脚是活的**，另一组被"拔掉"（引脚切到模拟态），因此绝不会冲突。

#### 技能点 3　分时复用的两件事：切引脚 + 切模式

##### 知识点 1　要切的第一个东西：GPIO 复用

把一组引脚"接上"SPI1，就是把它配成 **`GPIO_MODE_AF_PP` + `GPIO_AF5_SPI1`**；把它"拔下来"，最干净的做法是配成 **`GPIO_MODE_ANALOG`**：

> **为什么用模拟态而不是"随便配成输入/输出"**：模拟模式会**同时断开引脚的输出驱动器和输入施密特触发器**，引脚既不驱动也不感知任何电平，是 STM32 上"彻底隔离一个引脚"的标准做法。相比之下，配成输出会持续驱动（可能与外部器件对打），配成浮空输入会让引脚悬空（可能引入噪声与额外功耗）。

**表 1-6 两组引脚的切换目标**

| 目标器件 | PA4 | **PA5/PA6/PA7** | PA15 | **PB3/PB4/PB5** |
| --- | --- | --- | --- | --- |
| **接 TF 卡** | 输出高（CS，始终 GPIO） | **AF5（接上）** | 输出高（CS，始终 GPIO） | **模拟（拔下）** |
| **接 W25Q64** | 输出高（CS，始终 GPIO） | **模拟（拔下）** | 输出高（CS，始终 GPIO） | **AF5（接上）** |

> **两个片选引脚（PA4、PA15）永远保持 GPIO 输出高**，不参与切换。它们像两个"闸门"：**谁不被选中，谁的闸门就关着**。这是分时复用安全的第一道保险。

##### 知识点 2　要切的第二个东西：SPI 模式（CPOL/CPHA）

这是很多人会漏掉的一环——**两个器件的工作模式不一样**：

**表 1-7 两个器件的 SPI 参数对比**

| 参数 | W25Q64 | TF 卡（SPI 模式） | 是否一致 |
| --- | --- | --- | --- |
| 数据帧 | 8 位 | 8 位 | ✅ 一致 |
| 位序 | MSB 先行 | MSB 先行 | ✅ 一致 |
| **CPOL** | **High（模式 3）** | **Low（模式 0）** | ❌ **不一致** |
| **CPHA** | **2 Edge** | **1 Edge** | ❌ **不一致** |
| 时钟 | 最高 104MHz（0x03 读约 50MHz） | 最高 25MHz（初始化 ≤400kHz） | 取交集 |

> **CPOL/CPHA 不同，意味着每次切换器件都必须重写 `SPI_CR1` 的 CPOL/CPHA 位。** 而**修改 CR1 的前提是 `SPE = 0`（外设先关掉）**——这就是分时复用必须"关→改→开"三步走的原因。

##### 知识点 3　切换的完整动作序列

```
        ┌──────────────────────────────────────────────┐
        │ ① __HAL_SPI_DISABLE()   SPE=0，允许改 CR1     │
        │ ② 两个 CS 都拉高        保证两侧器件都"取消选中" │
        │ ③ 旧组引脚 → ANALOG     拔掉旧器件             │
        │ ④ 新组引脚 → AF5        接上新器件             │
        │ ⑤ 改 CPOL / CPHA / 分频  写入 hspi1.Init       │
        │ ⑥ HAL_SPI_Init()        把新参数写进 CR1       │
        │ ⑦ __HAL_SPI_ENABLE()    SPE=1，恢复通讯        │
        └──────────────────────────────────────────────┘
```

> **顺序不能乱**：**必须先拉高 CS 再动引脚**。如果先切引脚、后拉 CS，中间会有一小段时间"旧器件的 CS 还低着、但它的 SCK 已经变成模拟态悬空"，器件可能把悬空电平当成时钟采到脏数据，内部状态机错位。

---

### 环节三　释放 JTAG 占用的引脚

#### 技能点 1　定位"三个被借走的引脚"

##### 知识点 1　PA15 / PB3 / PB4 复位后不是普通 IO

很多人卡在这里：CubeMX 里明明把 SPI1 配好了，烧录后 FLASH 毫无反应，读 ID 恒为 `0xFF`。**根因往往不是 SPI 配置错，而是这三个引脚上电后默认是 JTAG 调试口。**

**表 1-8 被 JTAG 默认占用的引脚**

| 引脚 | 复位默认功能 | 本项目要用它做 | 是否冲突 |
| --- | --- | --- | --- |
| PA13 | JTMS / **SWDIO** | 保留（调试用） | 保留 |
| PA14 | JTCK / **SWCLK** | 保留（调试用） | 保留 |
| **PA15** | **JTDI** | W25Q64 的 CS | ⚠️ **冲突，必须释放** |
| **PB3** | **JTDO / TRACESWO** | SPI1_SCK（第二组） | ⚠️ **冲突，必须释放** |
| **PB4** | **NJTRST** | SPI1_MISO（第二组） | ⚠️ **冲突，必须释放** |
| PB5 | 无（默认普通 IO） | SPI1_MOSI（第二组） | 不冲突 |

##### 知识点 2　SWD 与 JTAG 的取舍

STM32F4 的调试接口支持两种协议，二者共用 PA13/PA14：

- **JTAG（5 线）**：需要 TMS/TCK/TDI/TDO/nTRST 共 5 根，占用 PA13/PA14/**PA15/PB3/PB4**；
- **SWD（2 线）**：只用 SWDIO(PA13)/SWCLK(PA14) 两根，**不占用 PA15/PB3/PB4**。

结论很直接：**本项目必须选 Serial Wire（SWD）**。

> ⚠️ **特别注意**：CubeMX 的 Debug 选项里还有一个 **Trace Asynchronous Sw**，它会把 PB3 单独留下来当 TRACESWO 输出。**本项目不能选它**，否则 PB3 依然被占，SPI1 第二组的时钟线没地方接。

#### 技能点 2　在 CubeMX 中完成释放

##### 知识点 1　SYS → Debug → Serial Wire

1. 左侧 **System Core → SYS**；
2. **Debug** 下拉框选 **Serial Wire**；
3. 此时芯片图上 PA13/PA14 会被标成 `SYS_JTMS-SWDIO` / `SYS_JTCK-SWCLK`，而 PA15/PB3/PB4 **重新变成可自由分配的浅色**。

> 📷 图 1-1 SYS → Debug → Serial Wire 设置界面（此处可插入截图）

##### 知识点 2　没释放时的典型现象

**表 1-9 JTAG 未释放时的现象与判别**

| 现象 | 判别方法 | 结论 |
| --- | --- | --- |
| 读 JEDEC ID 恒为 `0xFF` | 用示波器看 PB3 有无时钟 | 无时钟 → PB3 被 TRACESWO 占用 |
| 读 JEDEC ID 恒为 `0x00` | 量 PB4 电平 | MISO 被 JTAG 驱动为固定电平 |
| 编译下载后程序"跑飞" | 检查是否误用了 PA13/PA14 | SWD 引脚被重配成普通 IO，调试器失联 |
| CubeMX 里 PB3 选不到 SPI1 相关功能 | 看 SYS 的 Debug 设置 | 选成了 JTAG 或 Trace Asynchronous Sw |

> **排错口诀**：**"Pinout 里点不亮，先看 SYS 里选了什么"**。

---

### 环节四　编制引脚分配表与接线检查

#### 技能点 1　引脚分配表

##### 知识点 1　最终引脚分配（全部 AF5）

**表 1-10 本项目的最终引脚分配表（写进 CubeMX 之前先核对这张表）**

| 器件 | 信号 | STM32 引脚 | CubeMX 初配 | 运行期切换 | 复用编号 |
| --- | --- | --- | --- | --- | --- |
| W25Q64 | CS#（片选） | **PA15** | GPIO_Output（High） | 不切换 | — |
| W25Q64 | CLK | **PB3** | GPIO_Output（Low） | ↔ **AF5** | **AF5** |
| W25Q64 | DO（MISO） | **PB4** | GPIO_Output（Low） | ↔ **AF5** | **AF5** |
| W25Q64 | DI（MOSI） | **PB5** | GPIO_Output（Low） | ↔ **AF5** | **AF5** |
| TF 卡 | CS | **PA4** | GPIO_Output（High） | 不切换 | — |
| TF 卡 | SCK | **PA5** | **AF5**（SPI1） | ↔ 模拟态 | **AF5** |
| TF 卡 | MISO | **PA6** | **AF5**（SPI1） | ↔ 模拟态 | **AF5** |
| TF 卡 | MOSI | **PA7** | **AF5**（SPI1） | ↔ 模拟态 | **AF5** |
| 调试 | SWDIO / SWCLK | PA13 / PA14 | SYS | 不切换 | — |

> **为什么 CubeMX 里 SPI1 配在 PA5/PA6/PA7 而不是 PB3/PB4/PB5**：CubeMX **只允许给一个外设分配一组引脚**。我们选 TF 卡那组作为"SPI1 的主位置"（它物理上只能是 SPI1），另一组 PB3/PB4/PB5 在 CubeMX 里先配成**普通 GPIO 输出**，**运行期由我们自己的总线层接管**（改成 AF5 或模拟态），CubeMX 不会再管它们。

##### 知识点 2　W25Q64 的接法（含 WP# 与 HOLD#）

**表 1-11 W25Q64 引脚接法**

| W25Q64 引脚 | 全称 | 接到 | 说明 |
| --- | --- | --- | --- |
| CS# | Chip Select | **PA15** | 片选，低有效 |
| CLK | Serial Clock | **PB3** | 时钟 |
| DI（IO0） | Data In | **PB5** | 主机→FLASH（MOSI） |
| DO（IO1） | Data Out | **PB4** | FLASH→主机（MISO） |
| **WP#** | Write Protect | **3.3V**（10kΩ 上拉） | 低电平写保护；**不接会随机写失败** |
| **HOLD#** | Hold | **3.3V**（10kΩ 上拉） | 低电平暂停通讯；不接可能读到乱码 |
| VCC | 电源 | 3.3V + 100nF 去耦 | 不可接 5V |
| GND | 地 | GND | 与 MCU 共地 |

> **这两根脚为什么必须拉高**：`WP#` 悬空时引脚电平不确定，芯片可能进入写保护而**悄悄丢弃写入命令**（不报错、只表现为"读回来还是 0xFF"）；`HOLD#` 悬空时可能被误触发暂停。**新手 90% 的"写不进去"都出在这两根脚上。**

##### 知识点 3　TF 卡的接法

**表 1-12 TF 卡（SPI 模式）引脚接法**

| TF 卡引脚 | SPI 模式下的名称 | 接到 | 说明 |
| --- | --- | --- | --- |
| DAT2（1 脚） | — | 悬空或上拉 | SPI 模式不用 |
| CD/DAT3（2 脚） | **CS** | **PA4** | 片选，低有效；**建议 10kΩ 上拉** |
| CMD（3 脚） | **MOSI** | **PA7** | 主机→卡；建议 10kΩ 上拉 |
| VSS（4 脚） | GND | GND | 共地 |
| VDD（5 脚） | 电源 | **3.3V** + 10µF‖100nF | **严禁 5V**，会烧卡 |
| CLK（6 脚） | **SCK** | **PA5** | 时钟 |
| VSS（7 脚） | GND | GND | 共地 |
| DAT0（8 脚） | **MISO** | **PA6** | 卡→主机；**必须 10kΩ 上拉** |

> **MISO 上拉在本项目里格外重要**：因为分时复用，FLASH 工作时 TF 卡的 MISO 是"被拔下"的状态。上拉电阻能让这条线在空闲时稳定为高，**不会因为浮空而干扰到正在工作的 FLASH 组**。

#### 技能点 2　电气与接线检查清单

##### 知识点 1　上电前必查的五件事

1. **电平**：W25Q64 与 TF 卡都是 **3.3V 器件**，不要接开发板的 5V 排针；
2. **共地**：TF 卡座、FLASH、MCU 必须共地；
3. **上拉**：`WP#`、`HOLD#` 拉 3.3V；TF 卡的 CS/MOSI/**MISO** 各 10kΩ 上拉；
4. **去耦**：两颗器件电源脚就近各放 100nF，TF 卡再并 10µF，抑制插拔浪涌；
5. **不要动调试口**：PA13/PA14 保持给 SWD。

##### 知识点 2　分时复用特有的走线要求

因为两组引脚会"轮流工作"，走线上有个额外要求：

- **两组信号线不要长距离并行捆绑**：PA5/PA6/PA7 与 PB3/PB4/PB5 如果并排走 10cm 以上，切换瞬间的电容耦合会让正在工作的那组产生毛刺；
- **两组线之间夹一根地线**是最省事的做法；
- **片选线（PA4、PA15）各自靠近自己的器件**，避免被对方信号串扰误触发。

> 📷 图 1-2 本项目的实际接线照片（此处可插入实物图）

---

## 任务二　SPI 协议认知（物理层与协议层）

> **本任务的目标**：把 SPI 从"四根线"讲到"四种模式"。**协议层的功夫全在时序图上，看懂一张图，后面所有驱动都是它的展开。**

### 环节一　物理层：四根线如何搭起一条总线

#### 技能点 1　认识四根信号线

##### 知识点 1　SCK / MOSI / MISO 的角色

SPI（Serial Peripheral Interface，串行外围设备接口）由 Motorola 提出，是一条**高速、全双工、同步**的串行总线。它用三根总线加若干根片选线：

**表 2-1 SPI 的四根信号线**

| 信号 | 全称 | 方向 | 作用 |
| --- | --- | --- | --- |
| **SCK** | Serial Clock | 主机 → 从机 | 时钟，**由主机产生**，决定通讯速率 |
| **MOSI** | Master Out Slave In | 主机 → 从机 | 主机发、从机收 |
| **MISO** | Master In Slave Out | 从机 → 主机 | 从机发、主机收 |
| **NSS** | Slave Select（也叫 CS、SS） | 主机 → 从机 | 片选，**低电平选中** |

一句话区分 SPI 与 I2C 的寻址方式：**I2C 靠"地址"找器件，SPI 靠"片选线"点器件**。

##### 知识点 2　NSS：SPI 里没有"地址"这个词

**SPI 协议本身不定义任何地址字段**。主机要跟哪个从机说话，就把那根从机的 NSS 拉低。这带来两个直接后果：

1. **一个从机需要一根独立的 NSS 线**：挂 4 个从机，主机就要多花 4 根 IO（SCK/MOSI/MISO 可以并联共用）；
2. **NSS 的边沿就是通讯的起止信号**：`NSS 由高变低 = 起始`，`NSS 由低变高 = 停止`。

```
NSS  ‾‾‾‾\_______________________________________________/‾‾‾‾‾
          ▲ 起始（选中）                        ▲ 停止（取消选中）
SCK  ________/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\________________
MOSI ______X D7 X D6 X D5 X D4 X D3 X D2 X D1 X D0 X________
MISO ______X D7 X D6 X D5 X D4 X D3 X D2 X D1 X D0 X________
```

> **本项目有两条片选（PA4、PA15）**——这正是"多从机"的标准形态。正常的多从机是共用一组 SCK/MOSI/MISO，**而本项目因为引脚分属两组，连 SCK/MOSI/MISO 也要分时切换**，这是本项目比常规多从机多出来的一层复杂度。

#### 技能点 2　推挽输出与电气特性

##### 知识点 1　SPI 与 I2C 的电气差异

| 特性 | SPI | I2C |
| --- | --- | --- |
| 输出结构 | **推挽**（CMOS 互补） | **开漏 + 上拉电阻** |
| 驱动能力 | 强，可高速翻转 | 弱，靠电阻拉高，上升沿受限 |
| 需要上拉吗 | 不需要（但建议加上拉防浮空） | **必须** |
| 多设备挂同一根线 | 靠片选隔离 | 靠地址隔离 |
| 典型速率 | 数十 MHz | 100k ~ 400k |

> **一句话理解**：**I2C 是"开漏总线、大家共享、靠地址点名"，SPI 是"推挽点对点、靠片选放行"。** 所以 SPI 更快但更费引脚。

##### 知识点 2　本项目的 MISO 为什么必须上拉

正常 SPI 多从机时，未被选中的从机会把 MISO 置为**高阻**（释放总线），由被选中的那个从机驱动。此时若总线上没有上拉，MISO 在"两个从机都不驱动"的瞬间会浮空。

本项目情况更特殊：**分时复用会把另一组引脚切成模拟态**，相当于从物理上"拔掉"。这时：

- 被拔掉那组的 MISO 若浮空，可能通过 PCB 寄生电容耦合到相邻的活线上；
- **加 10kΩ 上拉**后，被拔掉的 MISO 稳定为高电平，既不影响对方，也让"卡不在"能被统一识别为 `0xFF`。

---

### 环节二　协议层：起始、采样与停止

#### 技能点 1　读懂一次完整传输

##### 知识点 1　NSS 拉低即起始、拉高即停止

一次 SPI 事务（transaction）的完整骨架：

1. **主机拉低目标从机的 NSS** —— 起始；
2. 主机产生 SCK 时钟，同时把数据一位一位地从 MOSI 送出、从 MISO 收回；
3. **数据在 SCK 的某个边沿被采样**（哪个边沿由 CPHA 决定）；
4. 传完约定字节数后，**主机拉高 NSS** —— 停止。

**每一次字节传输 = 8 个 SCK 周期**。

##### 知识点 2　全双工：发与收同步进行

这是 SPI 最容易被误解、也最容易写错驱动的一点：

> **SPI 没有"只读"这个动作。主机的每一个时钟周期，都在"同时"发送 1 位、接收 1 位。**

所以"读一个字节"在硬件上的真实动作是：**主机发送一个任意字节（惯用 `0xFF`）以产生 8 个时钟，从机借此把这 8 位数据移出来**。

```c
/* 这就是为什么"读"要发一个 Dummy 字节 */
#define SPI_DUMMY_BYTE   0xFF

uint8_t SPI_ReadByte(void)
{
  uint8_t dummy = SPI_DUMMY_BYTE;
  uint8_t rx    = 0;
  HAL_SPI_TransmitReceive(&hspi1, &dummy, &rx, 1, 100);  /* 发 dummy，收真数据 */
  return rx;
}
```

> **Dummy 字节为什么常用 `0xFF`**：从机在 MISO 上输出数据时，MOSI 上的值通常被它忽略；用 `0xFF`（全 1）可以在总线空闲时保持 MOSI 高电平，与"空闲态"一致，副作用最小。

#### 技能点 2　理解 CPOL 与 CPHA：四种模式的由来

##### 知识点 1　时钟极性与时钟相位

- **CPOL（Clock Polarity，时钟极性）**：**空闲时** SCK 是高还是低。`CPOL=0` 空闲为低，`CPOL=1` 空闲为高；
- **CPHA（Clock Phase，时钟相位）**：数据在**第几个边沿**被采样。`CPHA=0` 在**奇数边沿**采样，`CPHA=1` 在**偶数边沿**采样。

> **注意"奇数边沿"不等于"上升沿"**：当 CPOL=0 时奇数边沿是上升沿，当 CPOL=1 时奇数边沿是下降沿。**所以采样沿不是由上升/下降决定的，而是由"第几个边沿"决定的**——这是野火第 24 章特别强调、也是初学者最容易记混的一句。

**表 2-2 SPI 的四种模式**

| 模式 | CPOL | CPHA | 空闲时 SCK | 采样时刻 | 数据切换时刻 | 本项目用于 |
| --- | --- | --- | --- | --- | --- | --- |
| **模式 0** | 0 | 0 | 低电平 | 奇数边沿（上升沿） | 偶数边沿（下降沿） | **TF 卡** |
| 模式 1 | 0 | 1 | 低电平 | 偶数边沿（下降沿） | 奇数边沿（上升沿） | — |
| 模式 2 | 1 | 0 | 高电平 | 奇数边沿（下降沿） | 偶数边沿（上升沿） | — |
| **模式 3** | 1 | 1 | 高电平 | 偶数边沿（上升沿） | 奇数边沿（下降沿） | **W25Q64** |

**模式 0 的时序（TF 卡用）**：

```
NSS   ‾‾‾\_________________________________________/‾‾‾
SCK   ______/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\________
            ↑ ↑ ↑ ↑                        （CPOL=0，空闲低）
MOSI  ──X═D7═X═D6═X═ … ═X═D0═X──────────
          ↑ 在上升沿采样（CPHA=0，奇数边沿）
```

**模式 3 的时序（W25Q64 用）**：

```
NSS   ‾‾‾\_________________________________________/‾‾‾
SCK   ‾‾‾\___/‾‾‾\___/‾‾‾\___/‾‾‾\___/‾‾‾\___/‾‾‾\___
           ↑   ↑   ↑   ↑                 （CPOL=1，空闲高）
MOSI  ──X═D7═X═D6═X═ … ═X═D0═X──────────
            ↑ 在上升沿采样（CPHA=1，偶数边沿）
```

##### 知识点 2　两端必须同模式

> **主机与从机必须工作在同一个模式，否则读出来的数据永远是错的。**

**表 2-3 模式不匹配时的典型症状**

| 主机 | 从机 | 现象 |
| --- | --- | --- |
| 模式 3 | 模式 0 | 数据位整体错开半个时钟，读 ID 得到"像但不完全像"的值 |
| 模式 0 | 模式 3 | 首字节丢失或末字节丢一位 |
| 任一 | 任一 | 偶尔能通、偶尔不通（时序处于临界） |

> **本项目为什么必须"切模式"**：W25Q64 同时支持模式 0 和模式 3，**而 TF 卡在 SPI 模式下只支持模式 0**。本项目沿用野火第 24 章的做法，**用模式 3 驱动 FLASH**（实测更稳），用模式 0 驱动 TF 卡，因此**总线层必须负责切换**。
> 若你希望两个器件统一用模式 0，只需把总线层里 FLASH 分支的 `CLKPolarity` 改成 `SPI_POLARITY_LOW`、`CLKPhase` 改成 `SPI_PHASE_1EDGE` 即可——**W25Q64 对两种模式都支持**。

---

### 环节三　横向对比与速率账

#### 技能点 1　三条总线的选型逻辑

##### 知识点 1　SPI / I2C / UART 对照表

**表 2-4 常用三种板级总线的对比**

| 维度 | SPI | I2C | UART |
| --- | --- | --- | --- |
| 同步方式 | **同步**（有 SCK） | **同步**（有 SCL） | **异步**（无时钟） |
| 双工方式 | **全双工** | 半双工 | 全双工 |
| 线数 | 4 根起（每从机多 1 根 CS） | 2 根 | 2 根 + GND |
| 拓扑 | 一主多从（片选） | 多主多从（地址+仲裁） | 点对点 |
| 速率 | 数 MHz ~ 数十 MHz | 100k ~ 400k | 9.6k ~ 数 M |
| 典型器件 | FLASH、LCD、SD 卡、无线模块 | EEPROM、传感器、RTC | 调试口、GPS、蓝牙 |

**选型口诀**：**要快选 SPI，要省引脚选 I2C，要跨设备远距离/接电脑选 UART。**

#### 技能点 2　算清速率账：21MHz 有多快

##### 知识点 1　SCK 频率与字节速率的关系

SPI 每 8 个 SCK 周期传 1 字节，所以：

```
字节速率 = SCK 频率 ÷ 8
```

本项目**只有一个 SPI1**，全部时钟来自 **APB2 = 84MHz**：

| 使用场景 | 分频 | SCK | 字节速率 | 说明 |
| --- | --- | --- | --- | --- |
| W25Q64 工作 | ÷4 | **21 MHz** | ≈ 2.6 MB/s | 对 0x03 读指令余量充足 |
| TF 卡初始化 | ÷256 | **328 kHz** | ≈ 41 KB/s | **SD 规范要求 ≤400kHz** |
| TF 卡工作 | ÷4 | **21 MHz** | ≈ 2.6 MB/s | SD SPI 模式上限 25MHz |
| （可选）W25Q64 提速 | ÷2 | 42 MHz | ≈ 5.2 MB/s | 建议改用 Fast Read(0x0B) |

> **TF 卡为什么初始化阶段必须降到 328kHz**：SD 规范规定，**卡在上电初始化期间（识别、协商阶段）SCK 不得超过 400kHz**。÷256 得 328kHz，刚好卡在红线以下。

##### 知识点 2　分时复用的切换开销

每次切换总线要做 6 个引脚重配 + 1 次 SPI 重初始化，实测约 **2~5µs**。放在整笔事务里占比很小：

| 事务 | 耗时 | 切换开销占比 |
| --- | --- | --- |
| 读 1 个 JEDEC ID（4 字节） | 约 2µs（总线） | 切换只做 1 次，占比偏大但绝对值可忽略 |
| 读 512 字节 TF 块 | 约 250µs | ≈ 1.6% |
| 擦除 4KB 扇区 | 约 45ms | ≈ 0.01% |
| 写 256 字节页 | 约 700µs | ≈ 0.5% |

> **结论：切换开销可以忽略，但要遵守一条纪律——在整笔事务内部不要切换。** 如果每发一个字节都切一次总线，效率会掉到原来的十分之一。所以本笔记的驱动设计成"**每个公开函数入口切换一次**"。

##### 知识点 3　把时间算到擦除与编程上：FLASH 慢在哪

新手常以为"SPI 21MHz 很快，写 8MB 也就 3 秒"。**错的**。FLASH 的瓶颈从来不在总线，而在**芯片内部的擦除与编程**：

**表 2-5 写满 8MB 的时间账**

| 环节 | 单位耗时（典型值） | 数量 | 合计 |
| --- | --- | --- | --- |
| 总线传输（21MHz） | 8MB ÷ 2.6MB/s | 1 次 | ≈ **3.2 s** |
| 页编程（256B/页） | 0.7 ms | 32 768 页 | ≈ **23 s** |
| 扇区擦除（4KB） | 45 ms | 2 048 个 | ≈ **92 s** |
| 整片擦除 | — | 1 次 | ≈ **20 s**（一次性） |

> **结论**：**写 FLASH 的时间 99% 花在"等芯片内部干活"上。** 这直接决定了驱动里必须有"忙等待"（查状态寄存器 BUSY 位）。

---

## 任务三　STM32 SPI 外设认知

> **本任务的目标**：从"协议"下沉到"外设"。协议规定"信号长什么样"，外设决定"寄存器怎么配"。**看懂框图 → 记住寄存器 → 理解 HAL 封装**，三步走完后，CubeMX 里每个勾选项你都知道它在改哪个位。

### 环节一　功能框图：按信号流拆解

#### 技能点 1　画出 SPI 内部四大模块

##### 知识点 1　框图的四个部分

```
                    ┌───────────────────────────────────────────────┐
   地址/数据总线 ──►│  ┌─────────┐   ┌──────────┐   ┌────────────┐  │
                    │  │ 控制逻辑 │──►│ 波特率    │──►│  SCK 输出  │──┼──► SCK
                    │  │ CR1/CR2 │   │ 发生器    │   └────────────┘  │
                    │  └────┬────┘   └──────────┘                    │
                    │       │                                        │
                    │       ▼                                        │
                    │  ┌─────────┐      ┌──────────────────────┐    │
   数据寄存器 DR ◄──┼──┤ 发送缓冲 │─────►│  移位寄存器（8/16 位）│───┼──► MOSI
                    │  │ 接收缓冲 │◄─────┤   （MSB/LSB 先行）    │◄──┼─── MISO
                    │  └─────────┘      └──────────────────────┘    │
                    │                                                │
                    │  ┌──────────────────────────────────────┐     │
                    │  │  NSS 逻辑（硬件 NSS 或软件 SSI）      │─────┼──► NSS
                    │  └──────────────────────────────────────┘     │
                    └───────────────────────────────────────────────┘
```

四个模块与寄存器的对应关系：

**表 3-1 SPI 框图的四大模块**

| 模块 | 职责 | 相关寄存器位 |
| --- | --- | --- |
| **通讯引脚** | SCK/MOSI/MISO/NSS 的电气与复用 | 由 GPIO 的 AFR 决定，不在 SPI 寄存器里 |
| **时钟控制逻辑** | 从 f_pclk 分频出 SCK | `CR1.BR[2:0]`、`CR1.CPOL`、`CR1.CPHA`、`CR1.MSTR` |
| **数据控制逻辑** | 移位寄存器与收发缓冲 | `CR1.DFF`（8/16 位）、`CR1.LSBFIRST`、`DR` |
| **整体控制逻辑** | 状态机、中断、DMA、NSS | `CR1.SPE/SSI/SSM`、`CR2.*`、`SR.*` |

> **本项目要特别盯住"通讯引脚"这一块**：框图上 SCK/MISO/MOSI 每个信号只有**一条线**出来。这条线怎么接到两组不同的 GPIO 上，就是任务五要解决的分时复用问题。**框图在这里已经给了答案：一个信号只能接一个地方。**

##### 知识点 2　数据是怎么"流"过去的

以发送 1 字节 `0xA5 = 1010 0101` 为例：

1. CPU 把 `0xA5` 写进 **DR**（数据寄存器），硬件把它送进**发送缓冲**；
2. 波特率发生器产生 SCK，**移位寄存器**在每个时钟沿把最高位（MSB 先行时）挪到 MOSI 上；
3. 8 个时钟后，`0xA5` 全部送出，**`SR.TXE` 置 1**（发送缓冲空了）；
4. 与此同时，MISO 上的 8 位数据被同一个移位寄存器**同步收进来**，送进接收缓冲，**`SR.RXNE` 置 1**；
5. CPU 读 DR 取走收到的字节。

> **为什么"发"和"收"共用一个移位寄存器**：这正是全双工的实现方式——**一根时钟沿，同时把一位推出去、把一位收进来**。

#### 技能点 2　掌握 SCK 的分频关系

##### 知识点 1　BR[2:0] 的分频表

SCK 频率完全由 `CR1` 里的 `BR[2:0]` 三位决定，**只能是 2 的整数次幂分频**：

**表 3-2 BR[2:0] 分频对照（本项目 SPI1 挂 APB2 = 84MHz）**

| BR[2:0] | 分频 | HAL 宏 | SPI1 实际 SCK | 本项目用途 |
| --- | --- | --- | --- | --- |
| 000 | ÷2 | `SPI_BAUDRATEPRESCALER_2` | 42 MHz | （可选）FLASH 提速 |
| 001 | ÷4 | `SPI_BAUDRATEPRESCALER_4` | **21 MHz** | **FLASH 工作 / TF 卡工作** |
| 010 | ÷8 | `SPI_BAUDRATEPRESCALER_8` | 10.5 MHz | 调试降速 |
| 011 | ÷16 | `SPI_BAUDRATEPRESCALER_16` | 5.25 MHz | 调试降速 |
| 100 | ÷32 | `SPI_BAUDRATEPRESCALER_32` | 2.625 MHz | — |
| 101 | ÷64 | `SPI_BAUDRATEPRESCALER_64` | 1.3125 MHz | — |
| 110 | ÷128 | `SPI_BAUDRATEPRESCALER_128` | 656 kHz | — |
| 111 | ÷256 | `SPI_BAUDRATEPRESCALER_256` | **328 kHz** | **TF 卡初始化** |

> **本项目只有一个 SPI1，所以分频值只有这一列**。这也带来一个好处：**不用再像"SPI1+SPI3"那样记两个基准时钟**。

##### 知识点 2　选分频的三条实践规则

1. **先查从机的上限**：W25Q64 标准读（03h）最高约 50MHz，TF 卡 SPI 模式最高 25MHz。本项目统一取 21MHz，两者都满足；
2. **初始化降速，通信提速**：TF 卡识别阶段必须 ≤400kHz，识别完再切 21MHz；
3. **留余量**：**调试期先降到 1~5MHz 跑通，再逐步提高**，比一上来就顶到 21MHz 撞运气要快得多。

---

### 环节二　寄存器与 HAL 句柄：两套语言对照

#### 技能点 1　读透 SPI_InitTypeDef

##### 知识点 1　结构体成员与含义

HAL 库把 SPI 的配置收进一个结构体（定义于 `stm32f4xx_hal_spi.h`）：

```c
typedef struct {
  uint32_t Mode;                /* 主/从模式：SPI_MODE_MASTER / SPI_MODE_SLAVE */
  uint32_t Direction;           /* 通讯方向：2LINES / 2LINES_RXONLY / 1LINE */
  uint32_t DataSize;            /* 数据帧长度：8BIT / 16BIT */
  uint32_t CLKPolarity;         /* 时钟极性 CPOL：LOW / HIGH */
  uint32_t CLKPhase;            /* 时钟相位 CPHA：1EDGE / 2EDGE */
  uint32_t NSS;                 /* 片选方式：SOFT / HARD */
  uint32_t BaudRatePrescaler;   /* 波特率分频 */
  uint32_t FirstBit;            /* MSB / LSB 先行 */
  uint32_t TIMode;              /* TI 模式（基本不用） */
  uint32_t CRCCalculation;      /* CRC 校验开关 */
  uint32_t CRCPolynomial;       /* CRC 多项式 */
} SPI_InitTypeDef;
```

**表 3-3 CubeMX 配置项 ↔ 结构体成员 ↔ 本项目取值**

| CubeMX 配置项 | 结构体成员 | 本项目取值（FLASH / TF 卡） | 说明 |
| --- | --- | --- | --- |
| Mode | `Mode` | Master / Master | 两块存储都是从机 |
| Direction | `Direction` | 2 Lines Full Duplex | 全双工 |
| Data Size | `DataSize` | 8 Bits | 两者都是 8 位帧 |
| Clock Polarity (CPOL) | `CLKPolarity` | **High / Low** | FLASH 模式 3、TF 卡模式 0 |
| Clock Phase (CPHA) | `CLKPhase` | **2 Edge / 1 Edge** | 同上 |
| NSS Signal Type | `NSS` | **Software** | 都用 GPIO 片选 |
| Prescaler | `BaudRatePrescaler` | **4 / 256（初值）** | TF 卡初始化必须降速 |
| First Bit | `FirstBit` | MSB First | 两者都是高位先行 |
| CRC Calculation | `CRCCalculation` | Disabled | 不用 SPI 硬件 CRC |

##### 知识点 2　两个容易被忽略的坑

> **坑一：`DataSize` 设成 16 位后，MISO 会"多发一个字节"**。因为 16 位帧需要 16 个时钟。**W25Q64 与 TF 卡都必须用 8 位帧**。
>
> **坑二：`SPI_CRCCALCULATION_DISABLE` 时 `CRCPolynomial` 的赋值无效**。本项目 CRC 关掉，这行可删可留。

#### 技能点 2　看懂 HAL 的四个收发 API

##### 知识点 1　阻塞式 API 一览

**表 3-4 本项目会用到的 SPI HAL API**

| API | 方向 | 用途 | 本项目的使用场景 |
| --- | --- | --- | --- |
| `HAL_SPI_Transmit()` | 只发 | 发送 N 字节，接收内容被丢弃 | 发送命令字节、连续写数据 |
| `HAL_SPI_Receive()` | 只收 | 内部自动发 0xFF 产生时钟 | 连续读数据（TF 卡 512 字节块） |
| **`HAL_SPI_TransmitReceive()`** | 收发 | **同时**发送与接收等长数据 | **单字节收发的地基** |
| `HAL_SPI_Transmit_IT()` / `_DMA()` | 只发 | 中断/DMA 方式 | 大块数据搬运（本笔记用阻塞式讲原理） |

`HAL_SPI_TransmitReceive()` 的原型与返回值：

```c
HAL_StatusTypeDef HAL_SPI_TransmitReceive(SPI_HandleTypeDef *hspi,
                                          uint8_t *pTxData,   /* 发送缓冲指针 */
                                          uint8_t *pRxData,   /* 接收缓冲指针 */
                                          uint16_t Size,      /* 字节数 */
                                          uint32_t Timeout);  /* 超时 ms */
```

> **为什么单字节收发必须是 `TransmitReceive`**：SPI 是全双工，**只有产生时钟才能收到数据**。`HAL_SPI_Transmit()` 虽然也产生时钟、也会把数据收进 DR，但**它不会把接收内容返回给你**，取走就丢了。所以要"发一个字节同时收一个字节"，必须用 `TransmitReceive`。

##### 知识点 2　超时参数为什么必须填

`Timeout` 是阻塞式 API 的**生命线**。如果从机没接好、或者 MISO 被拉死，函数会一直等 `TXE`/`RXNE`，**没有超时就是死等**——现象是"程序卡死，串口不再输出，但板子没复位"。

```c
/* 有超时：最多等 100ms，失败返回 HAL_TIMEOUT，程序能继续走 */
HAL_StatusTypeDef st = HAL_SPI_TransmitReceive(&hspi1, &tx, &rx, 1, 100);
if (st != HAL_OK) {
  /* 可以在这里打印错误、点亮红灯、计数重试 */
}
```

> **HAL_MAX_DELAY 是"永不超时"**：调试期绝对不要在 SPI 上用 `HAL_MAX_DELAY`，否则一颗没焊好的 flash 会让整个程序静默卡死。

---

### 环节三　HAL 驱动流程与事件标志

#### 技能点 1　主机收发的四步流程

##### 知识点 1　从寄存器视角看一次传输

**表 3-5 SPI 主要状态标志**

| 标志 | 全称 | 含义 | 用法 |
| --- | --- | --- | --- |
| **TXE** | Transmit buffer Empty | 发送缓冲空，可以写下一个字节 | 写 DR 前等它为 1 |
| **RXNE** | Receive buffer Not Empty | 接收缓冲非空，可以读数据 | 读 DR 前等它为 1 |
| **BSY** | Busy | 移位寄存器正在传输 | 关外设前等它为 0 |
| **OVR** | Overrun | 接收溢出（没及时读走） | 出错标志，需清 |
| **MODF** | Mode Fault | NSS 被外部拉低导致主从冲突 | 多主机场景才需关注 |

**主机发送一个字节的四步**：

```
① 等 TXE = 1   →  发送缓冲空，可以写
② 写 DR        →  数据进入发送缓冲，移位寄存器开始工作
③ 等 RXNE = 1  →  一帧传完（发完 8 位，同时收完 8 位）
④ 读 DR        →  取走收到的字节（哪怕不要，也要读，否则 OVR）
```

> **第 ④ 步是最容易漏的一步**：接收缓冲只有一个位置，不读走，下一个字节到来时就溢出（OVR 置 1）。**HAL 的 `HAL_SPI_Transmit()` 内部已经帮你读了**，但自己写寄存器版本时千万别忘。

##### 知识点 2　HAL 已经把四步封装好了

```c
/* 发送 1 字节并同时接收 1 字节 —— 本项目所有单字节收发的统一入口 */
uint8_t SPI1_ReadWriteByte(uint8_t txData)
{
  uint8_t rxData = 0xFF;
  HAL_SPI_TransmitReceive(&hspi1, &txData, &rxData, 1, 100);
  return rxData;
}

/* 只发不收（命令字节）—— 同样要产生时钟，内部会读走 */
void SPI1_WriteByte(uint8_t txData)
{
  HAL_SPI_Transmit(&hspi1, &txData, 1, 100);
}
```

> **`SPI1_ReadWriteByte` 是全篇最重要的一行代码**：W25Q64 的读 ID、读状态、页写、读数据，TF 卡的 CMD/R1/数据块，**全部建立在它之上**。

#### 技能点 2　错误处理与常见故障

##### 知识点 1　三类典型错误

**表 3-6 SPI 常见故障与判别**

| 现象 | 最可能原因 | 判别与处理 |
| --- | --- | --- |
| 返回值恒 `HAL_TIMEOUT` | 从机没接、SCK 出不去、CS 没拉低 | 先量 SCK 有无波形；再看 CS 是否真的变低 |
| 读到全 `0xFF` | MISO 悬空（上拉把线拉高）或被从机释放 | 检查 MISO 接线与 CS 时序 |
| 读到全 `0x00` | MISO 被短接到地，或 CS 一直有效导致数据错位 | 量 MISO 静态电平；查 CS 是否在每次事务前拉高 |
| 首字节正确、后续错 | 发送时没读 DR（OVR 溢出） | 改用 `TransmitReceive` |
| 偶发误码 | 速率过高、走线过长、无去耦 | 降速到 5MHz 试；加 100nF |

##### 知识点 2　CS 的时序纪律

**两器件都有同一个要求：每次"命令"必须是一次独立的 CS 低-高循环。**

```c
/* 正确：一条命令一次 CS 周期 */
W25Q64_CS_LOW();
SPI1_ReadWriteByte(0x9F);      /* JEDEC ID 指令 */
id[0] = SPI1_ReadWriteByte(0xFF);
id[1] = SPI1_ReadWriteByte(0xFF);
id[2] = SPI1_ReadWriteByte(0xFF);
W25Q64_CS_HIGH();              /* 拉高结束，芯片复位内部状态机 */

/* 错误：多条命令共用一个 CS 周期 */
W25Q64_CS_LOW();
SPI1_ReadWriteByte(0x06);      /* 写使能 */
SPI1_ReadWriteByte(0x20);      /* 扇区擦除 —— 芯片会把它当成写使能命令的后续字节！ */
W25Q64_CS_HIGH();
```

> **为什么 CS 拉高这么重要**：芯片内部是**靠 CS 的上升沿来判定"这条命令结束了"**。CS 不拉高，芯片会一直认为数据还在继续，把下一条命令的字节当成上一条的参数吞掉。

---

## 任务四　STM32CubeMX 工程搭建

> **本任务的目标**：把前三个任务的结论落到工程上。**CubeMX 是本项目的"配置中心"，做对了后面全是填空；做错了（尤其引脚冲突和时钟），后面全是玄学。**

### 环节一　建立工程与配置系统时钟

#### 技能点 1　新建工程并选定芯片

##### 知识点 1　从芯片型号到封装

1. CubeMX 欢迎页 → **New Project**；
2. 在 **Part Number** 搜索框输入 `STM32F407VET6`；
3. 结果列表里确认封装为 **LQFP100**；
4. 双击进入工程，界面切换到 **Pinout & Configuration**。

> 📷 图 4-1 新建工程、搜索并选中 STM32F407VET6（此处可插入截图）

##### 知识点 2　工程命名与路径

**Project Manager → Project** 页填写：

| 配置项 | 建议值 | 说明 |
| --- | --- | --- |
| Project Name | `SPI_Storage` | 不要用中文、空格 |
| Project Location | 全英文路径 | 中文路径会导致 Keil 报奇怪的错 |
| Application Structure | Advanced | 便于分目录管理 |
| Toolchain / IDE | MDK-ARM V5 或 STM32CubeIDE | 按自己手上工具选 |
| Firmware Package | 用本地已装的版本 | 避免联网下载失败 |

#### 技能点 2　配置 RCC 与时钟树

##### 知识点 1　168MHz 标准配置

1. **System Core → RCC**：High Speed Clock (HSE) 选 **Crystal/Ceramic Resonator**；
2. 切到 **Clock Configuration** 页：
   - Input frequency = **8 MHz**；
   - PLL Source Mux = **HSE**；
   - PLLM = **8**（8MHz ÷ 8 = 1MHz 进 VCO）；
   - PLLN = **336**（1MHz × 336 = 336MHz）；
   - PLLP = **2**（336 ÷ 2 = **168MHz** = SYSCLK）；
   - System Clock Mux = **PLLCLK**；
   - AHB Prescaler = **/1** → HCLK = 168MHz；
   - APB1 Prescaler = **/4** → PCLK1 = 42MHz；
   - **APB2 Prescaler = /2 → PCLK2 = 84MHz（SPI1 的时钟源，全篇速率都从这里推）**。

> **这一页是后面所有速率计算的地基**：SPI1 工作时的 21MHz（÷4）、TF 卡初始化的 328kHz（÷256），全部由 **PCLK2 = 84MHz** 推出来。

##### 知识点 2　验证时钟配置

配完后，Clock Configuration 页下方会显示各总线的实际频率。**核对这三个数**：

```
SYSCLK   = 168 MHz
PCLK1    =  42 MHz
PCLK2    =  84 MHz   ← SPI1 用这个
```

若显示 "Max frequency exceeded" 红字，说明某处分频不够。**F407 的 APB2 上限是 84MHz，SPI1 的最高 SCK 是 42MHz（÷2）。**

> 📷 图 4-2 Clock Configuration 时钟树配置（此处可插入截图）

---

### 环节二　配置调试口与 GPIO

#### 技能点 1　释放 JTAG 引脚（承接任务一环节三）

##### 知识点 1　SYS 配置的连锁反应

1. **System Core → SYS**；
2. **Debug** 选 **Serial Wire**；
3. 观察芯片图：PA13/PA14 变为绿色（已分配 SYS_JTMS-SWDIO / SYS_JTCK-SWCLK），而 **PA15/PB3/PB4 恢复为可分配状态**；
4. **Timebase Source** 保持 **SysTick**（HAL_Delay 依赖它）。

> **操作顺序很重要**：**一定要先配 SYS，再去点 PA15/PB3/PB4**。反过来的话，CubeMX 会因为 JTAG 占用而拒绝，或者给你一个带警告的黄色引脚。

##### 知识点 2　配置完的自检

**表 4-1 SYS 配置后的引脚状态**

| 引脚 | 配置前 | 配置 Serial Wire 后 | 是否可自由分配 |
| --- | --- | --- | --- |
| PA13 | SYS_JTMS-SWDIO | SYS_JTMS-SWDIO | 不可（保留） |
| PA14 | SYS_JTCK-SWCLK | SYS_JTCK-SWCLK | 不可（保留） |
| PA15 | JTDI（灰） | **空闲（浅色）** | ✅ 可 |
| PB3 | JTDO（灰） | **空闲（浅色）** | ✅ 可 |
| PB4 | NJTRST（灰） | **空闲（浅色）** | ✅ 可 |

#### 技能点 2　配置两组片选与 PLASH 组的"占位"

##### 知识点 1　PA4 / PA15 配成推挽输出高

1. 芯片图上**左键点击 PA15** → 选 **GPIO_Output**；
2. **左键点击 PA4** → 选 **GPIO_Output**；
3. 切到 **System Core → GPIO** 页设置：

**表 4-2 两路片选的 GPIO 参数**

| 参数 | W25Q64 片选（PA15） | TF 卡片选（PA4） | 说明 |
| --- | --- | --- | --- |
| GPIO output level | **High** | **High** | 初始不选中（CS 高 = 从机空闲） |
| GPIO mode | Output Push Pull | Output Push Pull | 推挽，不需要上拉 |
| GPIO Pull-up/Pull-down | No pull-up and no pull-down | No pull-up and no pull-down | 板上有外部上拉的话这里不用管 |
| Maximum output speed | **Very High** | **Very High** | 高速时 CS 边沿要陡 |
| User Label | **W25Q64_CS** | **TF_CS** | 起别名，代码里好读 |

> **`User Label` 的作用**：填了别名后，CubeMX 会在 `main.h` 里生成 `#define W25Q64_CS_Pin GPIO_PIN_15` 和 `#define W25Q64_CS_GPIO_Port GPIOA`，代码里可以直接用，**引脚改名时不用全局搜索替换**。

##### 知识点 2　PB3 / PB4 / PB5 先配成 GPIO 输出（关键一步）

这一步是**本项目独有的**，常规 SPI 教程里不会有：

1. 芯片图上依次点击 **PB3、PB4、PB5** → 全部选 **GPIO_Output**；
2. 在 GPIO 页把这三个引脚配成：
   - GPIO output level = **Low**；
   - GPIO mode = Output Push Pull；
   - Maximum output speed = **Very High**；
   - User Label 分别填 `W25Q64_SCK`、`W25Q64_MISO`、`W25Q64_MOSI`。

> **为什么先配成 GPIO 输出而不是直接配 SPI1**：**CubeMX 只允许一个外设占用一组引脚**，我们已经把 SPI1 给了 PA5/PA6/PA7。PB3/PB4/PB5 只能先以普通 GPIO 的身份存在，**运行期再由总线层把它们切换成 AF5**。
>
> **为什么初值是 Low 而不是 High**：W25Q64 的 SCK 空闲态在模式 3 下是**高**，但上电时它还没被选中（CS 高），SCK 是什么电平无关紧要；配成 Low 可以避免上电瞬间通过 MOSI 灌入电流。**真正决定空闲电平的，是总线层把引脚切成 AF5 之后 SPI 外设输出的 CPOL 电平。**

##### 知识点 3　初始电平为什么片选必须是高

CS 的低电平是"选中"。**上电瞬间如果 CS 是低，从机就会以为自己被选中，等待命令**——而 CPU 还在跑启动代码，没有时钟过来，从机就一直挂着。

```c
/* CubeMX 生成的 gpio.c 里，会先写电平再初始化模式 */
HAL_GPIO_WritePin(W25Q64_CS_GPIO_Port, W25Q64_CS_Pin, GPIO_PIN_SET);  /* 先给高 */
HAL_GPIO_Init(W25Q64_CS_GPIO_Port, &GPIO_InitStruct);                 /* 再配模式 */
```

> **顺序不能反**：先配成输出再写高，中间那一瞬间引脚是低电平（复位默认值），从机可能误触发。**CubeMX 已按正确顺序生成**。

---

### 环节三　配置 SPI1（承载两个器件）

#### 技能点 1　Mode 与引脚分配

##### 知识点 1　只配一组引脚，另一组留给总线层

1. 左侧 **Connectivity → SPI1**；
2. **Mode** 下拉选 **Full-Duplex Master**；
3. CubeMX 自动把 **PA5 → SPI1_SCK、PA6 → SPI1_MISO、PA7 → SPI1_MOSI** 点亮；
4. **Hardware NSS Signal** 选 **Disable**（两路都用软件片选）；
5. **不要**试图在这里再选 PB3/PB4/PB5——CubeMX 会提示引脚冲突。

> **这就是"一个外设一组引脚"的现实**：SPI1 在 CubeMX 里只能长在 PA5/PA6/PA7 上。**PB3/PB4/PB5 的 SPI1 身份，是我们在代码里"临时赋予"的。**

##### 知识点 2　Parameter Settings 逐项填写

**表 4-3 SPI1 的 Parameter Settings**

| 配置项 | 取值 | 依据 |
| --- | --- | --- |
| Frame Format | Motorola | 标准 SPI 格式 |
| Data Size | **8 Bits** | 两个器件都是字节流 |
| First Bit | **MSB First** | 两者都要求高位先行 |
| Prescaler | **4**（→ 21MHz） | 上电初值；运行期由总线层按器件重设 |
| Clock Polarity (CPOL) | **Low** | 上电初值给 TF 卡（模式 0） |
| Clock Phase (CPHA) | **1 Edge** | 同上 |
| CRC Calculation | Disabled | 不用硬件 CRC |
| NSS Signal Type | **Software** | 两路都软件片选 |

> **为什么初值按 TF 卡配（模式 0）而不是 FLASH（模式 3）**：因为 **`TF_Init()` 是上电后第一个要降速到 328kHz 的操作**，而 FLASH 的自检可以用任意速度。把初值设成 TF 卡的配置，可以让总线层第一次切换时的"变化量"最小，也方便调试。
> **实际使用中，谁用谁切换**——初值只是"还没切换过"时的兜底状态。

##### 知识点 3　NVIC 与 DMA

本项目用**阻塞式**收发，**NVIC 全部不勾**。若后续要提速（例如整片读 8MB），再到 **DMA Settings** 添加 SPI1_TX/SPI1_RX，本笔记不展开。

#### 技能点 2　配置串口、生成工程与代码结构

##### 知识点 1　配置 USART1 作为调试输出

1. **Connectivity → USART1** → Mode 选 **Asynchronous**；
2. **Parameter Settings**：Baud Rate = **115200**，Word Length = **8 Bits**，Parity = **None**，Stop Bits = **1**；
3. 引脚自动落到 **PA9（TX）/ PA10（RX）**，复用 **AF7**；
4. **NVIC 可以不勾**（只用 printf 单向输出）。

> 📷 图 4-3 USART1 配置 115200-8-N-1（此处可插入截图）

##### 知识点 2　printf 重定向

**Keil MDK（需在 Options → Target 勾选 Use MicroLIB）：**

```c
/* USER CODE BEGIN 0 */
#if defined(__CC_ARM) || defined(__ARMCC_VERSION)
#pragma push
#pragma micro_lib
int fputc(int ch, FILE *f)
{
  HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, HAL_MAX_DELAY);
  return ch;
}
#pragma pop
#endif
/* USER CODE END 0 */
```

**STM32CubeIDE（GCC）：**

```c
/* USER CODE BEGIN 0 */
#include <sys/stat.h>
ssize_t _write(int fd, const void *pdata, size_t bytes)
{
  HAL_UART_Transmit(&huart1, (uint8_t *)pdata, bytes, HAL_MAX_DELAY);
  return bytes;
}
/* USER CODE END 0 */
```

> **串口在这里的角色不只是"打印"**：FLASH 和 TF 卡都没有"屏幕"，**所有判断都靠串口输出**。**printf 写得好不好，直接决定调试速度快不快。**

##### 知识点 3　Code Generator 设置与生成

**Project Manager → Code Generator** 勾选：

- ✅ **Generate peripheral initialization as a pair of '.c/.h' files per peripheral**（生成 `spi.c/h`、`gpio.c/h`、`usart.c/h`）；
- ✅ **Keep User Code when re-generating**（**绝对不要取消**）。

然后点 **GENERATE CODE**。

##### 知识点 4　核对生成的 MspInit：AF5 与初值

```c
void HAL_SPI_MspInit(SPI_HandleTypeDef* hspi)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if (hspi->Instance == SPI1)
  {
    __HAL_RCC_SPI1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* PA5 = SPI1_SCK, PA6 = SPI1_MISO, PA7 = SPI1_MOSI */
    GPIO_InitStruct.Pin       = GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7;
    GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;         /* 复用推挽 */
    GPIO_InitStruct.Pull      = GPIO_NOPULL;
    GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF5_SPI1;           /* ★ SPI1 是 AF5 */
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
  }
}
```

> ⚠️ **SPI1 是 AF5**（SPI3 才是 AF6）。本项目的 **PB3/PB4/PB5 在运行期也要用 AF5**——这一点在任务五的总线层里会反复出现。**写错成 AF6 的典型现象是：CubeMX 里一切正常，烧录后 FLASH 一个字节都不响应。**

##### 知识点 5　新建用户驱动文件

在工程里新建这些模块（**不要写进 CubeMX 管理的 `spi.c`**）：

```
SPI_Storage/
├── Core/
│   ├── Inc/
│   │   ├── main.h                 ← CubeMX 生成（含引脚宏）
│   │   ├── spi.h                  ← CubeMX 生成
│   │   ├── bsp_spi1_bus.h         ← ★ 自写：SPI1 分时复用总线层
│   │   ├── bsp_w25q64.h           ← ★ 自写：W25Q64 驱动
│   │   ├── bsp_tfcard.h           ← ★ 自写：TF 卡驱动
│   │   └── bsp_common.h           ← ★ 自写：日志宏、错误码
│   └── Src/
│       ├── main.c
│       ├── spi.c                  ← CubeMX 生成（勿改）
│       ├── bsp_spi1_bus.c         ← ★ 自写
│       ├── bsp_w25q64.c           ← ★ 自写
│       ├── bsp_tfcard.c           ← ★ 自写
│       └── app_storage.c          ← ★ 自写：测试与业务
```

> **纪律**：所有自写代码放在 `USER CODE BEGIN ... END` 之内，或者干脆独立成文件。**重新 GENERATE CODE 只会覆盖 CubeMX 管理的区域**。

---

## 任务五　SPI1 分时复用总线层（本项目核心）

> **本任务的目标**：写出一个"**让 SPI1 在两组引脚之间安全切换**"的中间层。这一层做对了，后面的 FLASH 与 TF 卡驱动可以**完全不用关心引脚**，只当自己独占一个 SPI1。**这是整个项目技术含量最高、也最容易写错的一层。**

### 环节一　设计总线层的接口

#### 技能点 1　为什么需要独立的一层

##### 知识点 1　三种可选的组织方式

**表 5-1 分时复用代码的三种组织方式**

| 方式 | 做法 | 评价 |
| --- | --- | --- |
| A：散落在各驱动里 | 每个驱动的每个函数开头自己写切换代码 | ❌ 重复几十遍，改一处漏十处 |
| B：用一个全局"当前设备"变量 + 判断 | `if (cur != FLASH) switch_to_flash();` | ⚠️ 能跑，但状态散落、易漏 |
| **C：独立的 bsp_spi1_bus 层** | **驱动只调 `BUS_Select(dev)`，切换逻辑集中在一处** | ✅ **本项目采用** |

> **方案 C 的好处**：
> ① **切换逻辑只有一份**，改引脚、改模式、改分频都只动一个文件；
> ② **驱动层变得和单器件项目一模一样**，野火的代码可以近乎照搬；
> ③ **可以加"状态缓存"**——如果这次要的器件和上次是同一个，直接跳过切换，省掉 2~5µs。

##### 知识点 2　总线层的 API 设计

**表 5-2 bsp_spi1_bus 对外接口**

| API | 作用 | 谁调用 |
| --- | --- | --- |
| `BUS_Init()` | 总线层上电初始化（默认选 TF 卡） | `main()` |
| `BUS_Select(BUS_DEV_TF)` | 切换到 TF 卡（模式 0，指定分频） | TF 卡驱动入口 |
| `BUS_Select(BUS_DEV_FLASH)` | 切换到 W25Q64（模式 3，指定分频） | FLASH 驱动入口 |
| `BUS_ReadWriteByte(b)` | 单字节收发 | 两个驱动 |
| `BUS_WriteBytes(p, n)` | 连续发送 | 两个驱动 |
| `BUS_ReadBytes(p, n)` | 连续接收 | 两个驱动 |
| `BUS_GetCurrent()` | 查询当前接的是谁（调试用） | 测试代码 |

> **设计要点**：`BUS_Select()` 里带上分频参数，是因为 **TF 卡在初始化（328kHz）和工作（21MHz）两个阶段需要不同的速度**，而 FLASH 也可能需要提速。**把"选谁"和"跑多快"合并到一个调用里**，比拆成两个函数更不容易漏。

#### 技能点 2　头文件设计

##### 知识点 1　bsp_spi1_bus.h 完整代码

```c
/* bsp_spi1_bus.h —— SPI1 分时复用总线层
 *
 * 背景：W25Q64（PA15/PB3/PB4/PB5）与 TF 卡（PA4/PA5/PA6/PA7）
 *       都挂在 SPI1 上（AF5），但一个 SPI 外设同一时刻只能驱动一组引脚。
 *       本层负责在两组引脚之间安全切换，向上层提供统一的字节读写接口。
 */
#ifndef __BSP_SPI1_BUS_H
#define __BSP_SPI1_BUS_H

#include "main.h"
#include "spi.h"          /* 提供 hspi1 */

/* ---------- 器件编号 ---------- */
typedef enum {
  BUS_DEV_NONE  = 0,
  BUS_DEV_TF    = 1,      /* TF 卡：PA4/PA5/PA6/PA7，模式 0 */
  BUS_DEV_FLASH = 2       /* W25Q64：PA15/PB3/PB4/PB5，模式 3 */
} BUS_DEV;

/* ---------- 分频快捷宏（SPI1 挂 APB2 = 84MHz） ----------
 *   ÷2   → 42   MHz
 *   ÷4   → 21   MHz   （工作速率）
 *   ÷8   → 10.5 MHz
 *   ÷16  → 5.25 MHz
 *   ÷32  → 2.625 MHz
 *   ÷64  → 1.3125 MHz
 *   ÷128 → 656  kHz
 *   ÷256 → 328  kHz   （TF 卡初始化必须 ≤400kHz）
 */
#define BUS_SPEED_42M    SPI_BAUDRATEPRESCALER_2
#define BUS_SPEED_21M    SPI_BAUDRATEPRESCALER_4
#define BUS_SPEED_10M5   SPI_BAUDRATEPRESCALER_8
#define BUS_SPEED_5M25   SPI_BAUDRATEPRESCALER_16
#define BUS_SPEED_2M6    SPI_BAUDRATEPRESCALER_32
#define BUS_SPEED_1M3    SPI_BAUDRATEPRESCALER_64
#define BUS_SPEED_656K   SPI_BAUDRATEPRESCALER_128
#define BUS_SPEED_328K   SPI_BAUDRATEPRESCALER_256

/* ---------- 引脚定义（与 CubeMX 中的 User Label 对应） ---------- */
#define BUS_CS_TF_PIN       GPIO_PIN_4
#define BUS_CS_TF_PORT      GPIOA
#define BUS_CS_FLASH_PIN    GPIO_PIN_15
#define BUS_CS_FLASH_PORT   GPIOA

#define BUS_TF_PINS         (GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7)   /* PA5/6/7 */
#define BUS_TF_PORT         GPIOA
#define BUS_FLASH_PINS      (GPIO_PIN_3 | GPIO_PIN_4 | GPIO_PIN_5)   /* PB3/4/5 */
#define BUS_FLASH_PORT      GPIOB

/* ---------- 对外接口 ---------- */
void     BUS_Init(void);
void     BUS_Select(BUS_DEV dev, uint32_t prescaler);
BUS_DEV  BUS_GetCurrent(void);
void     BUS_DeselectAll(void);

uint8_t  BUS_ReadWriteByte(uint8_t txData);
void     BUS_WriteBytes(uint8_t *pData, uint16_t len);
void     BUS_ReadBytes(uint8_t *pData, uint16_t len);

#endif /* __BSP_SPI1_BUS_H */
```

> **为什么把引脚定义写在这里而不是用 CubeMX 的 User Label**：因为 PB3/PB4/PB5 在 CubeMX 里是"普通 GPIO"，不会有 `SPI1_xxx` 这样的名字。**总线层自己定义一套明确的引脚宏**，比依赖自动生成的宏更好读、更好改。

---

### 环节二　实现总线层的完整代码

#### 技能点 1　核心切换函数

##### 知识点 1　bsp_spi1_bus.c 完整代码

```c
/* bsp_spi1_bus.c —— SPI1 分时复用总线层实现 */
#include "bsp_spi1_bus.h"

/* 当前接在 SPI1 上的器件 */
static BUS_DEV s_currentDev = BUS_DEV_NONE;

/* ---------- 内部：把一组引脚接上 SPI1（AF5） ---------- */
static void BUS_AttachAF5(GPIO_TypeDef *port, uint16_t pins)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin       = pins;
  GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;          /* 复用推挽 */
  GPIO_InitStruct.Pull      = GPIO_NOPULL;
  GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF5_SPI1;            /* ★ SPI1 = AF5 */
  HAL_GPIO_Init(port, &GPIO_InitStruct);
}

/* ---------- 内部：把一组引脚从 SPI1 上摘下（模拟态隔离） ----------
 * 模拟态同时断开输出驱动器与输入施密特触发器，
 * 引脚既不驱动也不感知电平，是"彻底隔离"的标准做法。
 */
static void BUS_DetachAnalog(GPIO_TypeDef *port, uint16_t pins)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin  = pins;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(port, &GPIO_InitStruct);
}

/* ---------- 内部：两路片选都拉高（谁都不选中） ---------- */
void BUS_DeselectAll(void)
{
  HAL_GPIO_WritePin(BUS_CS_TF_PORT,    BUS_CS_TF_PIN,    GPIO_PIN_SET);
  HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_SET);
}

/* ---------- 上电初始化 ----------
 * 把两组引脚都置于"安全态"：片选高、信号线模拟态，
 * 默认不接任何器件，等第一次 BUS_Select() 再决定。
 */
void BUS_Init(void)
{
  BUS_DeselectAll();

  /* 两个片选配成推挽输出高（CubeMX 已配，这里再确认一次） */
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  GPIO_InitStruct.Pin   = BUS_CS_TF_PIN | BUS_CS_FLASH_PIN;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull  = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* 两组信号线全部摘下 */
  BUS_DetachAnalog(BUS_TF_PORT,    BUS_TF_PINS);
  BUS_DetachAnalog(BUS_FLASH_PORT, BUS_FLASH_PINS);

  s_currentDev = BUS_DEV_NONE;

  /* 以 TF 卡身份启动（模式 0、慢速），方便第一次 TF_Init() */
  BUS_Select(BUS_DEV_TF, BUS_SPEED_328K);
}

/* ---------- 核心：切换到指定器件 ----------
 * 顺序严格如下，乱序会导致器件状态机错位：
 *   ① 关 SPI（SPE=0，才能改 CR1）
 *   ② 两路 CS 都拉高（先"取消选中"，再动引脚）
 *   ③ 旧组引脚 → 模拟态（拔掉旧器件）
 *   ④ 新组引脚 → AF5（接上新器件）
 *   ⑤ 改 CPOL/CPHA/分频（写入 hspi1.Init）
 *   ⑥ HAL_SPI_Init()（写进 CR1）
 *   ⑦ 开 SPI（SPE=1）
 */
void BUS_Select(BUS_DEV dev, uint32_t prescaler)
{
  /* 同器件且同速度：直接返回，省掉一次切换开销 */
  static uint32_t s_lastPrescaler = 0;
  if (dev == s_currentDev && prescaler == s_lastPrescaler)
  {
    return;
  }

  /* ① 关外设 */
  __HAL_SPI_DISABLE(&hspi1);

  /* ② 两路片选都拉高 */
  BUS_DeselectAll();

  /* ③④ 引脚切换 */
  if (dev == BUS_DEV_TF)
  {
    BUS_DetachAnalog(BUS_FLASH_PORT, BUS_FLASH_PINS);   /* 拔掉 FLASH */
    BUS_AttachAF5(BUS_TF_PORT,       BUS_TF_PINS);      /* 接上 TF 卡 */
    hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;          /* 模式 0 */
    hspi1.Init.CLKPhase    = SPI_PHASE_1EDGE;
  }
  else if (dev == BUS_DEV_FLASH)
  {
    BUS_DetachAnalog(BUS_TF_PORT,    BUS_TF_PINS);      /* 拔掉 TF 卡 */
    BUS_AttachAF5(BUS_FLASH_PORT,    BUS_FLASH_PINS);   /* 接上 FLASH */
    hspi1.Init.CLKPolarity = SPI_POLARITY_HIGH;         /* 模式 3 */
    hspi1.Init.CLKPhase    = SPI_PHASE_2EDGE;
  }
  else
  {
    s_currentDev = BUS_DEV_NONE;
    return;
  }

  /* ⑤ 分频 */
  hspi1.Init.BaudRatePrescaler = prescaler;

  /* ⑥ 重新写入 CR1 */
  HAL_SPI_Init(&hspi1);

  /* ⑦ 开外设 */
  __HAL_SPI_ENABLE(&hspi1);

  s_currentDev    = dev;
  s_lastPrescaler = prescaler;
}

BUS_DEV BUS_GetCurrent(void)
{
  return s_currentDev;
}

/* ---------- 单字节收发（两个驱动共用的地基） ---------- */
uint8_t BUS_ReadWriteByte(uint8_t txData)
{
  uint8_t rxData = 0xFF;
  if (HAL_SPI_TransmitReceive(&hspi1, &txData, &rxData, 1, 100) != HAL_OK)
  {
    return 0xFF;      /* 超时按"总线沉默"处理，上层据此判错 */
  }
  return rxData;
}

void BUS_WriteBytes(uint8_t *pData, uint16_t len)
{
  HAL_SPI_Transmit(&hspi1, pData, len, 1000);
}

void BUS_ReadBytes(uint8_t *pData, uint16_t len)
{
  /* SPI 读必须靠发 dummy 产生时钟，HAL_SPI_Receive 内部自动完成 */
  HAL_SPI_Receive(&hspi1, pData, len, 1000);
}
```

##### 知识点 2　逐行解析关键点

**① 为什么 `HAL_SPI_Init()` 可以反复调用**

`HAL_SPI_Init()` 内部会：
1. 先调 `__HAL_SPI_DISABLE()`（如果当前是使能的）；
2. 把 `Init` 结构体的成员逐位写进 `CR1`/`CR2`；
3. 再根据 `Init` 状态调 `__HAL_SPI_ENABLE()`。

所以它本身就是"关→写→开"的完整流程。我们在外面再手动 `DISABLE`/`ENABLE` 一次，是**双保险**——尤其是某些 HAL 版本在 `SPE=1` 时会跳过部分位的写入。

**② 为什么 `s_lastPrescaler` 要用 `static` 而不是成员变量**

它在函数内部当作"记忆上一次的值"用。用 `static` 局部变量最简单，且**不污染全局命名空间**。但要注意：**它不是线程安全的**（本项目是裸机单线程，没有这个问题）。

**③ 为什么"同器件同速度"要直接 return**

因为切换一次约 2~5µs，而**单字节读写只要 0.4µs**（21MHz）。如果驱动里每个字节都调一次 `BUS_Select()`，切换开销会占掉 90% 的时间。**加了缓存后，连续读写只在第一次真正切换。**

**④ 引脚的"模拟态"到底做了什么**

```
GPIO_MODE_ANALOG 使能后的引脚内部结构：
     ┌──────────┐
     │  输出驱动器 │ ← 断开（高阻）
     │  ─────────│
     │  施密特触发器│ ← 断开（不耗电、不感知）
     └──────────┘
```

这正是我们想要的"完全消失"。**对比 `GPIO_MODE_INPUT`（浮空）：输入缓冲还在工作，引脚上的噪声会被采进来；`GPIO_MODE_OUTPUT_PP`：驱动器还在使劲输出。**

#### 技能点 2　验证总线层

##### 知识点 1　一个最小验证程序

在写 FLASH 和 TF 卡驱动之前，**先单独验证总线层**——这是稳妥的开发顺序：

```c
/* 测试：反复切换，看两组引脚是否各自独立 */
void BUS_SelfTest(void)
{
  printf("\r\n===== SPI1 总线层自检 =====\r\n");

  /* 切到 FLASH，读 JEDEC ID */
  BUS_Select(BUS_DEV_FLASH, BUS_SPEED_21M);
  HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_RESET);
  BUS_ReadWriteByte(0x9F);
  uint8_t f0 = BUS_ReadWriteByte(0xFF);
  uint8_t f1 = BUS_ReadWriteByte(0xFF);
  uint8_t f2 = BUS_ReadWriteByte(0xFF);
  HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_SET);
  printf("[总线] FLASH 位置读到 ID = %02X %02X %02X（期望 EF 40 17）\r\n", f0, f1, f2);

  /* 切到 TF 卡，发 CMD0 看有无响应 */
  BUS_Select(BUS_DEV_TF, BUS_SPEED_328K);
  HAL_GPIO_WritePin(BUS_CS_TF_PORT, BUS_CS_TF_PIN, GPIO_PIN_SET);
  for (int i = 0; i < 10; i++) BUS_ReadWriteByte(0xFF);   /* 80 个暖机时钟 */
  HAL_GPIO_WritePin(BUS_CS_TF_PORT, BUS_CS_TF_PIN, GPIO_PIN_RESET);
  BUS_ReadWriteByte(0x40); BUS_ReadWriteByte(0x00);
  BUS_ReadWriteByte(0x00); BUS_ReadWriteByte(0x00);
  BUS_ReadWriteByte(0x00); BUS_ReadWriteByte(0x95);
  uint8_t r1 = 0xFF;
  for (int i = 0; i < 8 && r1 == 0xFF; i++) r1 = BUS_ReadWriteByte(0xFF);
  HAL_GPIO_WritePin(BUS_CS_TF_PORT, BUS_CS_TF_PIN, GPIO_PIN_SET);
  printf("[总线] TF 卡位置读到 R1 = %02X（期望 01）\r\n", r1);

  printf("[总线] 自检完成，当前器件 = %d\r\n", BUS_GetCurrent());
}
```

##### 知识点 2　自检结果判读

**表 5-3 总线层自检结果判读**

| FLASH 位置 | TF 卡位置 | 结论 |
| --- | --- | --- |
| `EF 40 17` | `01` | ✅ **完美，总线层正确** |
| `EF 40 17` | `FF` | 总线层对，**TF 卡硬件有问题**（卡座/供电/上拉） |
| `FF FF FF` | `01` | 总线层对，**FLASH 侧有问题**（PB3/PB4/PB5 未释放 JTAG，或 WP#/HOLD# 悬空） |
| `FF FF FF` | `FF` | **总线层本身有问题**：先查 `HAL_SPI_MspInit` 的 AF5、再查 `BUS_Select` 有没有被调用 |
| 两个位置都读到**同样的值** | | **切换没生效**：`BUS_Select` 里引脚没真正改，或两组的 CS 同时使能了 |

> **这张表的价值**：它把"总线层错"和"器件坏"两类完全不同的问题**彻底分开了**。没有这一步，你会把"PB3 是 JTAG 引脚"误判成"FLASH 芯片坏了"，白白换芯片。

##### 知识点 3　用示波器确认切换

用示波器双通道同时看 **PA5（TF 的 SCK）** 和 **PB3（FLASH 的 SCK）**：

- 切到 TF 卡后，**PA5 有波形，PB3 是一条静止的低电平**（模拟态）；
- 切到 FLASH 后，**PB3 有波形，PA5 静止**；
- 如果**两个都有波形** → 说明旧组引脚没被摘下，MISO 有冲突风险。

> **"同时只有一个 SCK 活动"是分时复用成功的铁证。**

---

### 环节三　总线层的常见坑

#### 技能点 1　六个易错点

##### 知识点 1　错误清单

**表 5-4 总线层的六个典型错误**

| # | 错误写法 | 后果 | 正确做法 |
| --- | --- | --- | --- |
| 1 | 先改引脚，后拉高 CS | 旧器件 CS 还低，SCK 已悬空，状态机错位 | **先 `BUS_DeselectAll()`，再动引脚** |
| 2 | 忘了 `__HAL_SPI_DISABLE()` | CR1 的 CPOL/CPHA/BR 位写不进去（只读保护） | 改 CR1 前必须 SPE=0 |
| 3 | 用 `GPIO_MODE_INPUT` 代替模拟态 | 输入缓冲仍在，噪声被采入 | 用 `GPIO_MODE_ANALOG` |
| 4 | 两组的 CS 都不拉高就切换 | 两个器件同时"半选中"，MISO 打架 | 切换前两路都拉高 |
| 5 | 每个字节都调 `BUS_Select()` | 切换开销占 90%，速度暴跌十倍 | 用状态缓存 + 只在函数入口切 |
| 6 | 切换后没给器件留"恢复时间" | 某些批次器件需要几 µs 才进入状态 | 切换后可加 `__NOP()` 数个或 `HAL_Delay(0)` |

##### 知识点 2　关于第 2 条：为什么改不了 CR1

SPI 的 `CR1` 寄存器在 `SPE = 1`（外设使能）状态下，**大部分配置位被硬件锁定**：

| 位 | SPE=0 | SPE=1 |
| --- | --- | --- |
| CPOL / CPHA | 可写 | **只读** |
| BR[2:0] | 可写 | **只读** |
| DFF / LSBFIRST | 可写 | **只读** |
| MSTR | 可写 | 可写（有限） |

> **这是"改了分频没生效"的头号原因**：代码没报错，返回值也是 `HAL_OK`，但寄存器根本没变。**只要记住"改 CR1 先关外设"，这类 bug 就绝迹了。**

#### 技能点 2　可选优化：用寄存器直接切换

##### 知识点 1　更快的切换（进阶）

如果项目对切换开销极其敏感（例如高频交替读写），可以绕开 `HAL_SPI_Init()`，**直接操作 GPIO 的 AFR 寄存器**：

```c
/* 进阶写法：不调用 HAL_GPIO_Init，直接改 AFR（约快 3 倍）
 * 原理：AFR 每 4 位描述一个引脚的 AF 编号，AF5 = 0b0101
 *       GPIOA->AFR[0] 管 PA0~PA7，GPIOB->AFR[0] 管 PB0~PB7
 */
static void BUS_AttachAF5_Fast(GPIO_TypeDef *port, uint8_t pin)
{
  port->AFR[pin >> 3] &= ~(0xFU << ((pin & 0x7U) * 4U));       /* 清 4 位 */
  port->AFR[pin >> 3] |=  (0x5U << ((pin & 0x7U) * 4U));       /* AF5 */
  port->MODER &= ~(0x3U << (pin * 2U));                        /* 清模式位 */
  port->MODER |=  (0x2U << (pin * 2U));                        /* 10 = 复用 */
}

static void BUS_DetachAnalog_Fast(GPIO_TypeDef *port, uint8_t pin)
{
  port->MODER &= ~(0x3U << (pin * 2U));
  port->MODER |=  (0x3U << (pin * 2U));                        /* 11 = 模拟 */
}
```

> **本笔记的主线代码用 `HAL_GPIO_Init()` 版本**，因为它可读性好、不出错；上面这段是**给你在需要极致性能时的参考**。两者功能完全等价。
>
> **什么时候才值得优化**：只有当你的业务里"每秒切换上万次"时才有意义。**本项目的实际切换频率是"每次事务一次"，优化收益可以忽略。** 记住一句工程箴言：**先跑通，再优化；过早优化是万恶之源。**

---

## 任务六　W25Q64 驱动开发（完整代码）

> **本任务的目标**：给出**完整、可直接编译**的 `bsp_w25q64.h` 与 `bsp_w25q64.c`。所有函数都实现，不留空。**驱动只依赖任务五的总线层，不直接碰 SPI1 —— 这就是分层的价值。**

### 环节一　认识 W25Q64：指令集与存储特性

#### 技能点 1　建立指令集的概念

##### 知识点 1　为什么 FLASH 需要"指令"而 EEPROM 不需要

对比一下两个器件收发的第一字节：

| 器件 | 第一字节的含义 | 举例 |
| --- | --- | --- |
| AT24C02（I2C EEPROM） | **设备地址 + 读写位** | `0xA0` |
| **W25Q64（SPI FLASH）** | **指令编码（Command Code）** | `0x03` = 读数据 |

**SPI 没有地址寻址机制**，所以 W25Q64 把"第一条要发的字节"全部用来当**操作码**：`0x03` 表示"我要读"，`0x02` 表示"我要写"，`0xD8` 表示"我要擦块"。主机先发操作码，再发参数（地址、数据），芯片据此执行。

> **这就是"指令"二字的由来**：对主机（STM32）来说，它只是按 SPI 协议发出了几个字节；对从机（W25Q64）来说，这几个字节被解释成了**不同含义的操作**。

##### 知识点 2　本项目必须掌握的九条指令

**表 6-1 W25Q64 核心指令表**

| 指令名 | 编码 | 后续字节 | 功能 | 本项目用在哪 |
| --- | --- | --- | --- | --- |
| Write Enable | `0x06` | 无 | **写使能**，置位 WEL | 每次擦/写前必发 |
| Write Disable | `0x04` | 无 | 写禁止，清除 WEL | `W25Q64_PowerDown` 前 |
| Read Status Register | `0x05` | 回读 S7~S0 | 读状态寄存器（含 BUSY 位） | **忙等待** |
| Read Data | `0x03` | A23~A0 + 数据流 | 读任意长度数据 | 读数据 |
| Fast Read | `0x0B` | A23~A0 + 1 dummy + 数据 | 高速读（可到 104MHz） | 提速时用 |
| Page Program | `0x02` | A23~A0 + 数据（≤256B） | 页编程，写 1~256 字节 | 写数据 |
| Sector Erase (4KB) | `0x20` | A23~A0 | 擦除 4KB 扇区 | **擦除（主力）** |
| Block Erase (64KB) | `0xD8` | A23~A0 | 擦除 64KB 块 | 大块擦除 |
| Chip Erase | `0xC7` | 无 | 整片擦除（约 20s） | `W25Q64_ChipErase()` |
| **JEDEC ID** | `0x9F` | 回读 3 字节 | 读厂商+容量 ID | **上电自检** |

**表 6-2 常用器件的 JEDEC ID**

| 型号 | 厂商 ID（M7~M0） | 容量 ID（ID15~ID0） | 完整 24 位 ID |
| --- | --- | --- | --- |
| **W25Q64** | `0xEF`（Winbond） | `0x4017` | **`0xEF4017`** |
| W25Q128 | `0xEF` | `0x4018` | `0xEF4018` |
| W25Q32 | `0xEF` | `0x4016` | `0xEF4016` |

> ⚠️ **陷阱提醒**：野火第 24 章用的是 **W25Q128**，代码里宏定义写的是 `#define sFLASH_ID 0XEF4018`。**本项目是 W25Q64，必须改成 `0xEF4017`**。照抄野火代码却忘了改这一行，是"读 ID 校验失败"最常见的原因——**芯片明明是好的，只是你把 128 的 ID 拿去比 64 的芯片**。

#### 技能点 2　理解 NOR FLASH 的"擦写三定律"

##### 知识点 1　只能 1→0，不能 0→1

> **NOR FLASH 的每一个存储位，编程（写）只能把它从 `1` 变成 `0`；要从 `0` 变回 `1`，必须靠"擦除"这一整块操作。**

由此推出三条工程定律：

1. **写之前必须先擦**：如果目标位置本来是 `0x00`，你想写 `0xFF`，直接写是办不到的；
2. **擦除以扇区为单位**：最小擦除单位是 4KB。**哪怕只想改 1 个字节，也要擦掉整个 4KB 扇区**；
3. **擦完之后整块变 `0xFF`**：新擦过的扇区读出来全是 `0xFF`（这是"空"的标志）。

```
写入流程：  擦除扇区(全变0xFF) → 页编程(把需要的位改成0) → 读回校验
              4KB                    256B/次
```

##### 知识点 2　擦除与编程的耗时

**表 6-3 W25Q64 典型操作耗时**

| 操作 | 典型时间 | 最大时间 | 影响 |
| --- | --- | --- | --- |
| 页编程（256B） | 0.7 ms | 3 ms | 写 1KB 约 3ms |
| 扇区擦除（4KB） | 45 ms | 400 ms | **写之前必擦，这笔开销躲不掉** |
| 块擦除（64KB） | 0.15 s | 2 s | 大批量时用 |
| 整片擦除 | 20 s | 100 s | 首次使用可整片擦 |

> **由此得出一个重要的设计原则**：**不要"改一个字节就擦一次扇区"**。如果每秒都要改一个配置字节，一秒擦一次 4KB 扇区，芯片寿命（约 10 万次擦写）只能撑 27 小时。

---

### 环节二　bsp_w25q64.h：接口与宏定义

#### 技能点 1　完整头文件

##### 知识点 1　bsp_w25q64.h 完整代码

```c
/* bsp_w25q64.h —— W25Q64（8MB SPI NOR FLASH）驱动接口
 *
 * 依赖：bsp_spi1_bus.h（SPI1 分时复用总线层）
 * 引脚：CS = PA15，SCK = PB3，MISO = PB4，MOSI = PB5（全部 AF5）
 *
 * 使用约定：
 *   1. 所有公开函数内部会自动 BUS_Select(BUS_DEV_FLASH)，无需调用者手动切换；
 *   2. 写入前必须先擦除（W25Q64_SectorErase 或 W25Q64_ChipErase）；
 *   3. 每个公开函数内部已经处理了 CS 的拉低/拉高，调用者不要自己动 CS。
 */
#ifndef __BSP_W25Q64_H
#define __BSP_W25Q64_H

#include "main.h"
#include "bsp_spi1_bus.h"

/* ==================== 容量与组织参数 ==================== */
#define W25Q64_FLASH_SIZE        (8UL * 1024UL * 1024UL)   /* 8MB = 8388608 字节 */
#define W25Q64_SECTOR_SIZE       4096UL                    /* 扇区 4KB，擦除最小单位 */
#define W25Q64_PAGE_SIZE         256UL                     /* 页 256B，写入最大单位 */
#define W25Q64_BLOCK_SIZE        65536UL                   /* 块 64KB（16 个扇区） */
#define W25Q64_SECTOR_COUNT      (W25Q64_FLASH_SIZE / W25Q64_SECTOR_SIZE)  /* 2048 */
#define W25Q64_PAGE_COUNT        (W25Q64_FLASH_SIZE / W25Q64_PAGE_SIZE)    /* 32768 */

/* ==================== 指令编码 ==================== */
#define W25X_WriteEnable         0x06
#define W25X_WriteDisable        0x04
#define W25X_ReadStatusReg       0x05
#define W25X_WriteStatusReg      0x01
#define W25X_ReadData            0x03
#define W25X_FastReadData        0x0B
#define W25X_FastReadDual        0x3B
#define W25X_PageProgram         0x02
#define W25X_BlockErase          0xD8
#define W25X_SectorErase         0x20
#define W25X_ChipErase           0xC7
#define W25X_PowerDown           0xB9
#define W25X_ReleasePowerDown    0xAB
#define W25X_DeviceID            0xAB
#define W25X_ManufactDeviceID    0x90
#define W25X_JedecDeviceID       0x9F

/* ==================== 其它常量 ==================== */
#define W25Q64_JEDEC_ID          0xEF4017UL   /* ★ W25Q64 是 4017，不是 4018 */
#define W25Q64_DUMMY_BYTE        0xFF
#define W25Q64_WIP_FLAG          0x01         /* 状态寄存器 bit0 = BUSY */
#define W25Q64_WEL_FLAG          0x02         /* 状态寄存器 bit1 = 写使能锁存 */
#define W25Q64_TIMEOUT           1000         /* 单次 SPI 操作超时 ms */
#define W25Q64_ERASE_TIMEOUT     5000         /* 擦除/编程等待超时 ms（扇区擦最大 400ms，留足余量） */

/* ==================== 返回码 ==================== */
#define W25Q64_OK                0
#define W25Q64_ERR_PARAM        (-1)   /* 参数错误（越界/空指针） */
#define W25Q64_ERR_TIMEOUT      (-2)   /* 忙等待超时 */
#define W25Q64_ERR_ID           (-3)   /* JEDEC ID 不匹配 */
#define W25Q64_ERR_BUS          (-4)   /* 总线无响应 */

/* ==================== 片选宏（只在本驱动内部使用） ==================== */
#define W25Q64_CS_LOW()   HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_RESET)
#define W25Q64_CS_HIGH()  HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_SET)

/* ==================== 对外接口 ==================== */

/* --- 初始化与自检 --- */
int      W25Q64_Init(void);                 /* 初始化 + 读 ID 自检，返回 W25Q64_OK / W25Q64_ERR_ID */
uint32_t W25Q64_ReadID(void);               /* 读 JEDEC ID（24 位） */
uint16_t W25Q64_ReadDeviceID(void);         /* 读厂商+器件 ID（16 位） */

/* --- 状态与使能 --- */
uint8_t  W25Q64_ReadStatus(void);           /* 读状态寄存器（8 位） */
void     W25Q64_WriteEnable(void);          /* 写使能（0x06） */
void     W25Q64_WriteDisable(void);         /* 写禁止（0x04） */
int      W25Q64_WaitForWriteEnd(void);      /* 等待 BUSY 清零，返回 W25Q64_OK / W25Q64_ERR_TIMEOUT */

/* --- 擦除 --- */
int      W25Q64_SectorErase(uint32_t sectorAddr);   /* 擦 4KB 扇区，地址自动按 4KB 对齐 */
int      W25Q64_BlockErase(uint32_t blockAddr);     /* 擦 64KB 块，地址自动按 64KB 对齐 */
int      W25Q64_ChipErase(void);                    /* 整片擦除（约 20s） */

/* --- 读写 --- */
int      W25Q64_WriteBuffer(uint32_t addr, uint8_t *pData, uint32_t len);  /* 任意长度写，自动按页拆分 */
int      W25Q64_ReadBuffer(uint32_t addr, uint8_t *pData, uint32_t len);   /* 任意长度读 */

/* --- 便捷函数 --- */
int      W25Q64_EraseAndWrite(uint32_t addr, uint8_t *pData, uint32_t len); /* 擦整个扇区再写 */
int      W25Q64_IsBlank(uint32_t addr, uint32_t len);   /* 检查区域是否为全 0xFF（1=空白） */
void     W25Q64_PowerDown(void);                        /* 进入掉电模式 */
void     W25Q64_WakeUp(void);                           /* 唤醒 */

#endif /* __BSP_W25Q64_H */
```

> **注意返回码的设计**：所有可能失败的函数都返回 `int`，并且区分了四种错误。**这比"返回 void、出错自己想办法"要可靠得多**——上层可以 `if (ret != W25Q64_OK)` 直接判断，也可以 `switch` 出具体原因。

##### 知识点 2　为什么 CS 宏定义在头文件里

`W25Q64_CS_LOW()` / `W25Q64_CS_HIGH()` 在驱动里出现几十次，写成宏既省事又统一；**将来换引脚，只改总线层头文件里的 `BUS_CS_FLASH_PIN` 一处**。

---

### 环节三　bsp_w25q64.c：完整实现（上）

#### 技能点 1　底层收发与地址

##### 知识点 1　内部静态函数

```c
/* bsp_w25q64.c —— W25Q64 驱动实现
 *
 * 所有公开函数都在入口处调用 BUS_Select() 切换到 FLASH，
 * 内部不直接操作 SPI1 的寄存器，也不关心引脚。
 *
 * ★ AF5 说明：PB3/PB4/PB5 的复用切换由总线层完成。
 */
#include "bsp_w25q64.h"
#include <string.h>
#include <stdio.h>

/* ---------- 单字节收发（透传到总线层） ---------- */
static uint8_t W25Q64_SendByte(uint8_t txData)
{
  return BUS_ReadWriteByte(txData);
}

/* ---------- 连续发送 ---------- */
static void W25Q64_SendBytes(uint8_t *pData, uint16_t len)
{
  BUS_WriteBytes(pData, len);
}

/* ---------- 连续接收（内部自动发 dummy 产生时钟） ---------- */
static void W25Q64_RecvBytes(uint8_t *pData, uint16_t len)
{
  BUS_ReadBytes(pData, len);
}

/* ---------- 发送 24 位地址（高字节在前） ---------- */
static void W25Q64_SendAddr(uint32_t addr)
{
  W25Q64_SendByte((addr >> 16) & 0xFF);   /* A23~A16 */
  W25Q64_SendByte((addr >>  8) & 0xFF);   /* A15~A8  */
  W25Q64_SendByte( addr        & 0xFF);   /* A7~A0   */
}

/* ---------- 进入 FLASH 上下文（切换总线 + 拉高 CS 待命） ---------- */
static void W25Q64_Enter(void)
{
  BUS_Select(BUS_DEV_FLASH, BUS_SPEED_21M);
  W25Q64_CS_HIGH();        /* 确保处于"未选中"状态 */
}
```

> **`W25Q64_Enter()` 是这套驱动的"统一入口"**。每个公开函数第一行都调它，**保证了不管上一次总线接的是谁，进来时一定已经切到 FLASH**。这就是分时复用对上层"完全透明"的实现方式。

#### 技能点 2　状态与写使能

##### 知识点 1　状态寄存器与忙等待

```c
/**
 * @brief  读状态寄存器（8 位）
 * @note   bit0 = BUSY(WIP)，bit1 = WEL，其余为块保护位
 */
uint8_t W25Q64_ReadStatus(void)
{
  uint8_t status;

  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_ReadStatusReg);
  status = W25Q64_SendByte(W25Q64_DUMMY_BYTE);
  W25Q64_CS_HIGH();

  return status;
}

/**
 * @brief  写使能：置位 WEL 标志
 * @note   每次擦除/编程前必须调用，因为 WEL 在每次操作结束后自动清零
 */
void W25Q64_WriteEnable(void)
{
  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_WriteEnable);
  W25Q64_CS_HIGH();
}

/**
 * @brief  写禁止：清除 WEL 标志
 */
void W25Q64_WriteDisable(void)
{
  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_WriteDisable);
  W25Q64_CS_HIGH();
}

/**
 * @brief  等待 FLASH 内部擦除/编程结束（BUSY 位归零）
 * @retval W25Q64_OK / W25Q64_ERR_TIMEOUT
 * @note   整个等待过程 CS 保持低电平：手册规定发出读状态指令后，
 *         芯片会持续输出最新状态，直到 CS 拉高为止。
 */
int W25Q64_WaitForWriteEnd(void)
{
  uint32_t tickstart;

  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_ReadStatusReg);

  tickstart = HAL_GetTick();
  while ((W25Q64_SendByte(W25Q64_DUMMY_BYTE) & W25Q64_WIP_FLAG) != 0)
  {
    if ((HAL_GetTick() - tickstart) > W25Q64_ERASE_TIMEOUT)
    {
      W25Q64_CS_HIGH();
      return W25Q64_ERR_TIMEOUT;
    }
  }

  W25Q64_CS_HIGH();
  return W25Q64_OK;
}
```

##### 知识点 2　读 ID 的两个版本

```c
/**
 * @brief  读 JEDEC ID（0x9F + 3 字节），用于识别芯片型号
 * @retval 24 位 ID；W25Q64 应为 0xEF4017
 */
uint32_t W25Q64_ReadID(void)
{
  uint8_t id[3];

  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_JedecDeviceID);          /* 0x9F */
  id[0] = W25Q64_SendByte(W25Q64_DUMMY_BYTE);   /* 厂商 ID */
  id[1] = W25Q64_SendByte(W25Q64_DUMMY_BYTE);   /* 容量高字节 */
  id[2] = W25Q64_SendByte(W25Q64_DUMMY_BYTE);   /* 容量低字节 */
  W25Q64_CS_HIGH();

  return ((uint32_t)id[0] << 16) | ((uint32_t)id[1] << 8) | id[2];
}

/**
 * @brief  读厂商+器件 ID（0x90 + 3 字节 dummy + 1 字节厂商 + 1 字节器件）
 * @retval 16 位：高字节 = 厂商 ID(0xEF)，低字节 = 器件 ID(0x17)
 */
uint16_t W25Q64_ReadDeviceID(void)
{
  uint8_t  mf, dev;

  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_ManufactDeviceID);       /* 0x90 */
  W25Q64_SendByte(0x00);                        /* 3 字节地址（全 0） */
  W25Q64_SendByte(0x00);
  W25Q64_SendByte(0x00);
  mf  = W25Q64_SendByte(W25Q64_DUMMY_BYTE);     /* 厂商 ID */
  dev = W25Q64_SendByte(W25Q64_DUMMY_BYTE);     /* 器件 ID */
  W25Q64_CS_HIGH();

  return ((uint16_t)mf << 8) | dev;
}
```

> **`0x90` 与 `0x9F` 的差别**：
> `0x9F`（JEDEC）= 厂商(1) + 容量(2)，共 3 字节，**靠它识别型号**；
> `0x90`（Manufacturer/Device）= 3 字节 dummy 地址 + 厂商(1) + 器件(1)，**老式用法，信息更少**。本项目**主用 `0x9F`**，`0x90` 保留作为交叉验证。

---

### 环节四　bsp_w25q64.c：完整实现（下）

#### 技能点 1　三种擦除

##### 知识点 1　扇区擦除、块擦除、整片擦除

```c
/**
 * @brief  擦除一个 4KB 扇区
 * @param  sectorAddr: 扇区内任意地址（内部自动向下对齐到 4KB 边界）
 * @retval W25Q64_OK / W25Q64_ERR_PARAM / W25Q64_ERR_TIMEOUT
 */
int W25Q64_SectorErase(uint32_t sectorAddr)
{
  if (sectorAddr >= W25Q64_FLASH_SIZE)
  {
    return W25Q64_ERR_PARAM;
  }

  /* 向下对齐到 4KB 边界：0x1234 → 0x1000 */
  sectorAddr &= ~(W25Q64_SECTOR_SIZE - 1UL);

  W25Q64_Enter();
  W25Q64_WriteEnable();                 /* ① 写使能 */
  if (W25Q64_WaitForWriteEnd() != W25Q64_OK) return W25Q64_ERR_TIMEOUT;

  W25Q64_CS_LOW();                      /* ② 指令 + 地址 */
  W25Q64_SendByte(W25X_SectorErase);
  W25Q64_SendAddr(sectorAddr);
  W25Q64_CS_HIGH();                     /* ③ 拉高，芯片开始擦 */

  return W25Q64_WaitForWriteEnd();      /* ④ 等擦完（最长 400ms） */
}

/**
 * @brief  擦除一个 64KB 块
 * @param  blockAddr: 块内任意地址（内部自动向下对齐到 64KB 边界）
 */
int W25Q64_BlockErase(uint32_t blockAddr)
{
  if (blockAddr >= W25Q64_FLASH_SIZE)
  {
    return W25Q64_ERR_PARAM;
  }

  blockAddr &= ~(W25Q64_BLOCK_SIZE - 1UL);   /* 对齐到 64KB */

  W25Q64_Enter();
  W25Q64_WriteEnable();
  if (W25Q64_WaitForWriteEnd() != W25Q64_OK) return W25Q64_ERR_TIMEOUT;

  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_BlockErase);
  W25Q64_SendAddr(blockAddr);
  W25Q64_CS_HIGH();

  return W25Q64_WaitForWriteEnd();           /* 最长 2s */
}

/**
 * @brief  整片擦除（约 20s，最大 100s）
 * @note   耗时极长，仅在首次使用或需要彻底清空时调用
 */
int W25Q64_ChipErase(void)
{
  W25Q64_Enter();
  W25Q64_WriteEnable();

  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_ChipErase);
  W25Q64_CS_HIGH();

  return W25Q64_WaitForWriteEnd();
}
```

##### 知识点 2　对齐处理为什么重要

**表 6-4 地址对齐的处理方式**

| 传入地址 | 实际擦除范围 | 说明 |
| --- | --- | --- |
| `0x000000` | `0x000000 ~ 0x000FFF` | 已对齐，正常 |
| `0x000123` | `0x000000 ~ 0x000FFF` | **自动向下对齐**，擦掉整个 0x000 扇区 |
| `0x001FFF` | `0x001000 ~ 0x001FFF` | 落在扇区末尾，擦的是它所在的那个扇区 |
| `0x000FFF` 想"只擦 1 字节" | `0x000000 ~ 0x000FFF` | **FLASH 做不到，只能整扇区擦** |

> **`& ~(SIZE - 1)` 是"向下对齐到 SIZE 整数倍"的通用写法**：因为 SIZE 是 2 的幂，`SIZE - 1` 正好是低位全 1 的掩码，取反后低位全 0。
> 这行代码的作用是**把"擦哪个字节"的语义，变成"擦哪个扇区"**——避免调用者传入非对齐地址时，误以为擦掉了别的区域。

#### 技能点 2　页编程与不定长写入

##### 知识点 1　页编程（内部函数）

```c
/**
 * @brief  页编程（内部函数）：向指定地址写入 1~256 字节
 * @note   调用前必须确保目标区域已擦除（全 0xFF）
 * @note   不检查页边界，由调用者（WriteBuffer）保证不跨页
 */
static int W25Q64_PageWrite(uint32_t addr, uint8_t *pData, uint16_t len)
{
  uint16_t i;

  if (len == 0 || len > W25Q64_PAGE_SIZE)
  {
    return W25Q64_ERR_PARAM;
  }

  W25Q64_Enter();
  W25Q64_WriteEnable();                     /* 写使能 */

  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_PageProgram);        /* 0x02 */
  W25Q64_SendAddr(addr);
  for (i = 0; i < len; i++)
  {
    W25Q64_SendByte(pData[i]);              /* 逐字节发数据，芯片内部地址自增 */
  }
  W25Q64_CS_HIGH();

  return W25Q64_WaitForWriteEnd();          /* 等页编程完成（约 0.7ms） */
}
```

##### 知识点 2　页边界：跨页会"回卷"

**这是页编程最反直觉的一点**：

> **页编程命令的地址不要求 256 对齐，但写入的字节数一旦越过了 256 字节的页边界，多出来的数据会"回卷"到本页开头，覆盖掉刚写的数据**——而不是自动跳到下一页。

```
从 0x0000F0 开始写 32 字节（页边界在 0x0000FF）：
  0x0000F0~0x0000FF  → 16 字节，正常
  0x000100~0x00010F  → 本应写这里，实际回卷到 0x000000~0x00000F
                        并把之前写的 0x0000F0~0x0000FF 覆盖掉一部分
```

##### 知识点 3　不定长写入（自动按页拆分）

```c
/**
 * @brief  向 FLASH 写入任意长度数据（自动按页拆分，绝不跨页）
 * @param  addr: 起始地址
 * @param  pData: 数据指针
 * @param  len: 字节数
 * @retval W25Q64_OK / W25Q64_ERR_PARAM / W25Q64_ERR_TIMEOUT
 * @note   调用前必须确保目标扇区已擦除！
 *         如需"擦+写"一步完成，请用 W25Q64_EraseAndWrite()
 */
int W25Q64_WriteBuffer(uint32_t addr, uint8_t *pData, uint32_t len)
{
  uint32_t pageRemain;
  int      ret;

  /* 边界与空指针检查 */
  if (pData == NULL || len == 0)
  {
    return W25Q64_ERR_PARAM;
  }
  if (addr >= W25Q64_FLASH_SIZE || (addr + len) > W25Q64_FLASH_SIZE)
  {
    return W25Q64_ERR_PARAM;
  }

  while (len > 0)
  {
    /* 本页还能写多少字节：当前地址距离本页末尾的剩余空间 */
    pageRemain = W25Q64_PAGE_SIZE - (addr % W25Q64_PAGE_SIZE);
    if (pageRemain > len)
    {
      pageRemain = len;                      /* 数据不够填满一页 */
    }

    ret = W25Q64_PageWrite(addr, pData, (uint16_t)pageRemain);
    if (ret != W25Q64_OK)
    {
      return ret;
    }

    addr  += pageRemain;
    pData += pageRemain;
    len   -= pageRemain;
  }

  return W25Q64_OK;
}
```

> **这个 `pageRemain` 的算法是一切"不定长写 FLASH"的通用骨架**：它先算出"当前页还剩多少空间"，写满一页就换下一页，直到数据写完。**EEPROM 的页写（8 字节/页）用的是完全相同的逻辑**，只是页大小不同——**学会一个，通吃一片**。

#### 技能点 3　连续读取与便捷函数

##### 知识点 1　连续读取

```c
/**
 * @brief  从 FLASH 连续读取任意长度数据
 * @note   读操作没有长度限制：只要 CS 保持低，芯片会一直按地址自增输出
 */
int W25Q64_ReadBuffer(uint32_t addr, uint8_t *pData, uint32_t len)
{
  if (pData == NULL || len == 0)
  {
    return W25Q64_ERR_PARAM;
  }
  if (addr >= W25Q64_FLASH_SIZE || (addr + len) > W25Q64_FLASH_SIZE)
  {
    return W25Q64_ERR_PARAM;
  }

  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_ReadData);      /* 0x03 */
  W25Q64_SendAddr(addr);
  W25Q64_RecvBytes(pData, (uint16_t)len);
  W25Q64_CS_HIGH();

  return W25Q64_OK;
}
```

> **注意 `(uint16_t)len` 的类型转换**：`BUS_ReadBytes()` 的参数是 `uint16_t`，如果一次读超过 65535 字节，会被截断。**本项目的 `ReadBuffer` 限制在 64KB 以内**。若要读更大块，需要改成"分段循环读"或把总线层参数改成 `uint32_t`。

##### 知识点 2　擦写一体化与空白检测

```c
/**
 * @brief  擦除目标区域的起始扇区（可能不止一个），再写入数据
 * @note   会擦掉从 addr 所在扇区开始、覆盖 [addr, addr+len) 的所有扇区！
 *         这是"写任意长度"的最简用法，代价是可能擦掉同扇区的其它数据。
 */
int W25Q64_EraseAndWrite(uint32_t addr, uint8_t *pData, uint32_t len)
{
  uint32_t startSector, endSector, sec;

  if (pData == NULL || len == 0)          return W25Q64_ERR_PARAM;
  if (addr + len > W25Q64_FLASH_SIZE)     return W25Q64_ERR_PARAM;

  startSector = addr / W25Q64_SECTOR_SIZE;
  endSector   = (addr + len - 1) / W25Q64_SECTOR_SIZE;

  /* 逐个扇区擦除 */
  for (sec = startSector; sec <= endSector; sec++)
  {
    int ret = W25Q64_SectorErase(sec * W25Q64_SECTOR_SIZE);
    if (ret != W25Q64_OK) return ret;
  }

  return W25Q64_WriteBuffer(addr, pData, len);
}

/**
 * @brief  检查一段区域是否"空白"（全 0xFF）
 * @retval 1 = 全 0xFF（空白，可直接写），0 = 有数据，-1 = 参数错误
 */
int W25Q64_IsBlank(uint32_t addr, uint32_t len)
{
  uint8_t  buf[64];
  uint32_t i, n;

  if (addr + len > W25Q64_FLASH_SIZE) return -1;

  while (len > 0)
  {
    n = (len > sizeof(buf)) ? sizeof(buf) : len;

    if (W25Q64_ReadBuffer(addr, buf, n) != W25Q64_OK) return -1;

    for (i = 0; i < n; i++)
    {
      if (buf[i] != 0xFF) return 0;      /* 找到非 0xFF，说明有数据 */
    }

    addr += n;
    len  -= n;
  }
  return 1;
}
```

> **`W25Q64_IsBlank()` 的实用价值**：它让你在写入前能判断"这块区域是不是擦干净的"。**如果已经是空白，就可以跳过擦除**——省下一次 45ms 的扇区擦除，也省下一次擦写寿命。

##### 知识点 3　掉电与唤醒

```c
/**
 * @brief  进入掉电模式（功耗降到约 1µA）
 * @note   进入后除了 0xAB 释放命令，其它指令都不响应
 */
void W25Q64_PowerDown(void)
{
  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_PowerDown);       /* 0xB9 */
  W25Q64_CS_HIGH();
  HAL_Delay(1);                          /* tDP = 3µs（最小），给 1ms 富余 */
}

/**
 * @brief  从掉电模式唤醒
 * @note   发 0xAB 后，芯片会回传一个器件 ID 字节，读出即表示已唤醒
 */
void W25Q64_WakeUp(void)
{
  W25Q64_Enter();
  W25Q64_CS_LOW();
  W25Q64_SendByte(W25X_ReleasePowerDown);   /* 0xAB */
  W25Q64_SendByte(W25Q64_DUMMY_BYTE);       /* dummy（3 或 4 字节视型号，1 字节足够唤醒） */
  W25Q64_CS_HIGH();
  HAL_Delay(1);                             /* tRES1 = 3µs */
}
```

#### 技能点 4　初始化与自检

##### 知识点 1　W25Q64_Init 完整实现

```c
/**
 * @brief  W25Q64 初始化与自检
 * @retval W25Q64_OK / W25Q64_ERR_ID
 * @note   内部会通过总线层把 SPI1 切到 FLASH 一侧（AF5 + 模式 3 + 21MHz）
 */
int W25Q64_Init(void)
{
  uint32_t id;

  BUS_Select(BUS_DEV_FLASH, BUS_SPEED_21M);   /* 切到 FLASH 一侧 */
  W25Q64_CS_HIGH();
  HAL_Delay(5);                                /* 上电稳定（tPUW 典型 5ms） */

  id = W25Q64_ReadID();
  printf("[W25Q64] JEDEC ID = 0x%06lX\r\n", (unsigned long)id);

  if (id == W25Q64_JEDEC_ID)
  {
    printf("[W25Q64] 检测到 W25Q64（8MB），自检通过\r\n");
    return W25Q64_OK;
  }
  else if (id == 0xEF4018UL)
  {
    printf("[W25Q64] 警告：实际是 W25Q128（16MB），请修改 W25Q64_JEDEC_ID 宏\r\n");
  }
  else if (id == 0xFFFFFFUL)
  {
    printf("[W25Q64] 错误：ID 全为 0xFF —— MISO 悬空/无供电/CS 未拉低\r\n");
    printf("         检查：① 3.3V 供电 ② PB4(MISO) 焊接 ③ PB3 是否已释放 JTAG\r\n");
  }
  else if (id == 0x000000UL)
  {
    printf("[W25Q64] 错误：ID 全为 0x00 —— MISO 短地/数据线接反\r\n");
  }
  else
  {
    printf("[W25Q64] 错误：ID 不匹配（读到 0x%06lX，期望 0x%06lX）\r\n",
           (unsigned long)id, (unsigned long)W25Q64_JEDEC_ID);
    printf("         若"像但不完全像"，多半是 CPOL/CPHA 模式不对\r\n");
  }
  return W25Q64_ERR_ID;
}
```

##### 知识点 2　ID 校验的诊断表

**表 6-5 读 ID 结果的诊断表**

| 读到值 | 含义 | 下一步 |
| --- | --- | --- |
| **`0xEF4017`** | W25Q64，一切正常 | 继续初始化 |
| `0xEF4018` | 焊的是 **W25Q128** | 改宏定义，或确认板子型号 |
| `0xFFFFFF` | MISO 一直高（上拉/悬空/芯片没供电） | 量 VCC、查 MISO 焊接 |
| `0x000000` | MISO 一直低（短路/CS 时序错） | 查 MISO 是否短地、CS 是否真的在拉低 |
| `0x7Fxxxx` 之类"半对" | **CPOL/CPHA 模式不匹配** | 从模式 3 换模式 0（反之亦然）试 |
| `0xEF0000` | 后两字节没收到 | 检查 `DataSize` 是否为 8 位 |

> **这张表把"读 ID 失败"这个模糊现象，变成了六种可定位的故障**。**任何 SPI 器件上电的第一件事，就是读 ID 并和手册比对**——它用最小的代价验证了"时钟通不通、MISO 通不通、模式对不对"三件事。

---

## 任务七　W25Q64 联调与验证

> **本任务的目标**：把驱动跑起来，并用**三条验收线**证明它真的能工作。**写的代码"看起来对"和"真的对"之间，隔着一整套测试。**

### 环节一　编写测试程序

#### 技能点 1　三条验收线对应的三个测试

##### 知识点 1　测试用变量与辅助函数

```c
/* app_storage.c —— FLASH 测试程序 */
#include "bsp_w25q64.h"
#include <string.h>
#include <stdio.h>

#define FLASH_TEST_ADDR     0x000000UL    /* 测试用地址（扇区 0 起始） */
#define FLASH_TEST_LEN      256UL         /* 一页长度 */

static uint8_t s_txBuf[FLASH_TEST_LEN];
static uint8_t s_rxBuf[FLASH_TEST_LEN];

/* 构造测试数据：前 128 字节 ASCII，后 128 字节 0x00~0x7F 递增（覆盖 0x00 与 0xFF） */
static void BuildTestData(void)
{
  uint32_t i;
  for (i = 0; i < 128; i++)
  {
    s_txBuf[i] = (uint8_t)('A' + (i % 26));
  }
  for (i = 128; i < FLASH_TEST_LEN; i++)
  {
    s_txBuf[i] = (uint8_t)(i - 128);
  }
}

/* 逐字节比对，返回 0 表示一致 */
static int BufferCompare(uint8_t *a, uint8_t *b, uint32_t len)
{
  uint32_t i;
  for (i = 0; i < len; i++)
  {
    if (a[i] != b[i])
    {
      printf("[校验失败] 第 %lu 字节：写入 0x%02X，读出 0x%02X\r\n",
             (unsigned long)i, a[i], b[i]);
      return -1;
    }
  }
  return 0;
}
```

##### 知识点 2　测试一 + 测试二：通得上、写得进读得出

```c
/**
 * @brief  W25Q64 读写回环测试（测试一 + 测试二）
 */
void W25Q64_Test(void)
{
  int ret;

  printf("\r\n========== W25Q64 读写测试 ==========\r\n");

  BuildTestData();

  /* ---------- 测试二之前：先看目标扇区是不是已经空白 ---------- */
  if (W25Q64_IsBlank(FLASH_TEST_ADDR, FLASH_TEST_LEN) == 1)
  {
    printf("[测试] 目标区域已是空白，跳过擦除（省 45ms）\r\n");
  }
  else
  {
    printf("[测试] 正在擦除扇区 0（约 45ms）...\r\n");
    ret = W25Q64_SectorErase(FLASH_TEST_ADDR);
    if (ret != W25Q64_OK)
    {
      printf("[测试] 擦除失败，ret = %d\r\n", ret);
      return;
    }
  }

  /* ---------- 写入 ---------- */
  ret = W25Q64_WriteBuffer(FLASH_TEST_ADDR, s_txBuf, FLASH_TEST_LEN);
  if (ret != W25Q64_OK)
  {
    printf("[测试] 写入失败，ret = %d\r\n", ret);
    return;
  }
  printf("[测试] 写入 %lu 字节完成\r\n", (unsigned long)FLASH_TEST_LEN);

  /* ---------- 读回（先清零，防止"读到旧值也算对"） ---------- */
  memset(s_rxBuf, 0, sizeof(s_rxBuf));
  ret = W25Q64_ReadBuffer(FLASH_TEST_ADDR, s_rxBuf, FLASH_TEST_LEN);
  if (ret != W25Q64_OK)
  {
    printf("[测试] 读取失败，ret = %d\r\n", ret);
    return;
  }

  /* ---------- 比对 ---------- */
  if (BufferCompare(s_txBuf, s_rxBuf, FLASH_TEST_LEN) == 0)
  {
    printf("★ 回环校验通过：写入与读出完全一致\r\n");
    printf("  读出前 32 字节：%.32s\r\n", s_rxBuf);
  }
  else
  {
    printf("✗ 回环校验失败\r\n");
  }
}
```

> **`memset(s_rxBuf, 0, ...)` 这一行的作用**：如果读函数因故没写入任何数据，`s_rxBuf` 里残留的是上一次的内容。**先清零，才能区分"读到了正确的数据"和"根本没读到、只是缓冲区碰巧还是对的"**。这是测试代码的通用纪律。

##### 知识点 3　测试三：掉电保持

```c
/**
 * @brief  掉电保持验证（测试三）
 * @note   必须在"复位后"调用，且【不能擦除、不能写入】
 *         一旦擦除，就变成了"又写一遍再读"，验证不出数据是否真的留在了芯片里
 */
void W25Q64_VerifyAfterReset(void)
{
  printf("\r\n========== 掉电保持验证 ==========\r\n");
  printf("（本次不做擦除、不做写入，只读）\r\n");

  BuildTestData();                         /* 重建期望值（与写入时相同） */

  memset(s_rxBuf, 0, sizeof(s_rxBuf));
  if (W25Q64_ReadBuffer(FLASH_TEST_ADDR, s_rxBuf, FLASH_TEST_LEN) != W25Q64_OK)
  {
    printf("✗ 读取失败\r\n");
    return;
  }

  if (BufferCompare(s_txBuf, s_rxBuf, FLASH_TEST_LEN) == 0)
  {
    printf("★ 掉电保持验证通过：断电重启后数据完好\r\n");
  }
  else
  {
    printf("✗ 掉电保持验证失败：数据丢失或被改写\r\n");
    printf("  常见原因：① 写入后没等 BUSY ② 上电时 WP# 拉低 ③ 写进了 RAM 缓存\r\n");
  }
}
```

> **掉了电还读得对，才说明数据真的落盘了。** 这一步是整个 FLASH 项目里**最有说服力**的验收——它一次就排除了"没擦除""没等待""写在缓存里"三类问题。

#### 技能点 2　进阶测试：跨页与全扇区

##### 知识点 1　跨页写入测试

```c
/**
 * @brief  跨页写入测试：从非页对齐地址写 300 字节（会跨 2 个页边界）
 * @note   专门用来验证 pageRemain 拆分逻辑是否正确
 */
void W25Q64_TestCrossPage(void)
{
  #define CROSS_ADDR   0x000010UL      /* 从页内偏移 16 开始，必然跨页 */
  #define CROSS_LEN    300UL           /* 300 > 256，必然跨页 */

  uint8_t tx[CROSS_LEN];
  uint8_t rx[CROSS_LEN];
  uint32_t i, ret;

  printf("\r\n===== 跨页写入测试（addr=0x%06lX, len=%lu）=====\r\n",
         (unsigned long)CROSS_ADDR, (unsigned long)CROSS_LEN);

  for (i = 0; i < CROSS_LEN; i++) tx[i] = (uint8_t)(i * 7 + 3);

  if (W25Q64_IsBlank(0x000000, W25Q64_SECTOR_SIZE) != 1)
  {
    W25Q64_SectorErase(0x000000);
  }

  ret = W25Q64_WriteBuffer(CROSS_ADDR, tx, CROSS_LEN);
  if (ret != W25Q64_OK) { printf("写入失败 ret=%lu\r\n", (unsigned long)ret); return; }

  memset(rx, 0, sizeof(rx));
  W25Q64_ReadBuffer(CROSS_ADDR, rx, CROSS_LEN);

  if (memcmp(tx, rx, CROSS_LEN) == 0)
    printf("★ 跨页写入正确（pageRemain 拆分逻辑有效）\r\n");
  else
    printf("✗ 跨页写入失败：检查 W25Q64_WriteBuffer 的 pageRemain 计算\r\n");
}
```

> **为什么必须专门测跨页**：`pageRemain` 的算法有三种常见错误写法——① 忘了 `% PAGE_SIZE`；② 用了 `PAGE_SIZE - addr` 而不是 `PAGE_SIZE - (addr % PAGE_SIZE)`；③ 循环里更新了 `addr` 但忘了更新 `pData`/`len`。**这三种错误在"页对齐且长度小于一页"时都不会暴露，只有跨页测试能抓出来。**

##### 知识点 2　写满整扇区测试

```c
/**
 * @brief  写满整个 4KB 扇区并校验（验证 16 页连续写入）
 */
void W25Q64_TestFullSector(void)
{
  static uint8_t tx[W25Q64_SECTOR_SIZE];
  static uint8_t rx[W25Q64_SECTOR_SIZE];
  uint32_t i, t0, t1;

  printf("\r\n===== 整扇区写入测试（4KB）=====\r\n");

  for (i = 0; i < W25Q64_SECTOR_SIZE; i++) tx[i] = (uint8_t)(i ^ 0xA5);

  t0 = HAL_GetTick();
  if (W25Q64_EraseAndWrite(0x001000, tx, W25Q64_SECTOR_SIZE) != W25Q64_OK)
  {
    printf("写入失败\r\n");
    return;
  }
  t1 = HAL_GetTick();
  printf("擦 + 写 4KB 耗时 %lu ms（预期约 48~55ms）\r\n", (unsigned long)(t1 - t0));

  memset(rx, 0, sizeof(rx));
  W25Q64_ReadBuffer(0x001000, rx, W25Q64_SECTOR_SIZE);

  if (memcmp(tx, rx, W25Q64_SECTOR_SIZE) == 0)
    printf("★ 整扇区写入校验通过\r\n");
  else
    printf("✗ 整扇区写入失败\r\n");
}
```

> **耗时是一个极好的"健康指标"**：擦 4KB 约 45ms、写 16 页约 11ms，合计约 **56ms**。如果你测出来只有 1~2ms，说明**擦除根本没执行**（数据是"碰巧"对的）；如果超过 500ms，说明**忙等待在空转**。**学会用时间验证行为，比只看数据对不对更可靠。**

---

### 环节二　下载验证与故障排查

#### 技能点 1　运行结果对照

##### 知识点 1　正常的串口输出

```
========== SPI 存储项目启动 ==========
[W25Q64] JEDEC ID = 0xEF4017
[W25Q64] 检测到 W25Q64（8MB），自检通过
[总线] 自检完成，当前器件 = 2

========== W25Q64 读写测试 ==========
[测试] 目标区域已是空白，跳过擦除（省 45ms）
[测试] 写入 256 字节完成
★ 回环校验通过：写入与读出完全一致
  读出前 32 字节：ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEF

===== 跨页写入测试（addr=0x000010, len=300）=====
★ 跨页写入正确（pageRemain 拆分逻辑有效）

===== 整扇区写入测试（4KB）=====
擦 + 写 4KB 耗时 53 ms（预期约 48~55ms）
★ 整扇区写入校验通过

========== 掉电保持验证 ==========
（本次不做擦除、不做写入，只读）
★ 掉电保持验证通过：断电重启后数据完好
```

##### 知识点 2　FLASH 故障速查表

**表 7-1 W25Q64 故障速查**

| 现象 | 最可能原因 | 验证方法 | 处理 |
| --- | --- | --- | --- |
| ID 读到 `0xFFFFFF` | MISO 悬空 / 芯片没供电 / CS 没拉低 | 万用表量 MISO、VCC、CS | 查 VCC=3.3V、MISO 焊接、`BUS_Select` 是否切到 FLASH |
| ID 读到 `0x000000` | MISO 短地 / 数据线接反 | 量 MISO 对地电阻 | 查短路；确认 PB4=DO、PB5=DI 没接反 |
| ID 读到 `0xEF4018` | 焊接的是 W25Q128 | 看芯片丝印 | 改宏定义 |
| ID 读到"半对"（如 `0x7F20xx`） | **CPOL/CPHA 不匹配** | 改总线层 FLASH 分支为模式 0 | 模式 3 ↔ 模式 0 互换 |
| **ID 正常但写不进去** | ① 忘写使能 ② 忘等 BUSY ③ 未擦除 ④ `WP#` 悬空 | 在 `PageWrite` 里打点 | 四条逐一排查 |
| 写入后读回全是 `0xFF` | ① `WP#` 悬空写保护 ② 未擦除 ③ 写使能漏发 | 量 WP# 是否 3.3V | WP# 上拉 10kΩ |
| 读回数据"整体错位几位" | 模式不匹配 / 速率过高 | 降到 1MHz 试 | 降速或改模式 |
| 前几字节对、后面全错 | 跨页回卷 | 跑 `W25Q64_TestCrossPage()` | 检查 `pageRemain` 计算 |
| 第 0 扇区能写、其它扇区不行 | 地址计算错 | 打印实际发送的 3 字节地址 | 核对高低位顺序 |
| 程序卡死无输出 | SPI 超时用了 `HAL_MAX_DELAY` | — | 改用 100ms 超时 |
| **FLASH 正常但 TF 卡不正常** | 总线切换没生效 | 看示波器：切到 TF 后 PA5 有无波形 | 检查 `BUS_Select` 的引脚切换分支 |
| **两器件都异常** | AF 写成 AF6 | 打开 `bsp_spi1_bus.c` 看 `GPIO_AF5_SPI1` | SPI1 必须是 AF5 |

#### 技能点 2　用示波器与 GPIO 打点

##### 知识点 1　四个必须看的位置

1. **CS（PA15）**：每次命令是否是"一次干净的低-高"？
2. **SCK（PB3）**：空闲时是否是**高电平**（模式 3 的标志）？有无 8 个完整周期的突发？
3. **MOSI（PB5）**：第一个字节是否是 `0x9F`（读 ID 时）？MSB 是否在前？
4. **MISO（PB4）**：是否有数据随 SCK 变化（而不是一根直线）？

> **看什么不重要，"这四条同时在一个屏幕上"最重要**。一次典型的"读 ID"应该看到：CS 下降 → SCK 出 8 个周期（0x9F）→ 再出 24 个周期（3 个 ID 字节）→ CS 上升。

##### 知识点 2　用 GPIO 打点测时序

```c
/* 用一根空闲引脚（比如 PE0）标记代码执行段，示波器量高电平宽度 = 该段耗时 */
HAL_GPIO_WritePin(GPIOE, GPIO_PIN_0, GPIO_PIN_SET);
W25Q64_SectorErase(0);
HAL_GPIO_WritePin(GPIOE, GPIO_PIN_0, GPIO_PIN_RESET);
/* 量到的高电平宽度应该 ≈ 45ms（扇区擦除典型值） */
```

> 这招叫"**软件打点**"，比 printf 精确得多（printf 本身就有毫秒级开销），是排查"到底慢在哪"的利器。**也可以用它量 `BUS_Select()` 的切换开销**，验证是否真在 2~5µs 量级。

---

## 任务八　TF 卡（microSD）SPI 模式驱动（完整代码）

> **本任务的目标**：让 TF 卡在 SPI 模式下跑通，并给出**完整可编译**的 `bsp_tfcard.h` / `bsp_tfcard.c`。**这比 W25Q64 难一个数量级**——因为 TF 卡是"一个带 CPU 的小系统"，有自己的一套协议、状态机和应答格式。

### 环节一　认识 TF 卡：从 SD 总线到 SPI 模式

#### 技能点 1　理解 SD 总线的"四线三模式"

##### 知识点 1　同一组引脚，三种工作模式

TF 卡的 8 个引脚中，真正用来通信用的是 4 根。**这 4 根线在不同的工作模式下，含义完全不同**：

**表 8-1 SD 总线三种工作模式**

| 引脚（卡侧） | SD 1 位模式 | 4 位模式 | **SPI 模式（本项目）** |
| --- | --- | --- | --- |
| 2 脚 DAT3 | DAT3 | DAT3 | **CS（片选）** |
| 3 脚 CMD | CMD | CMD | **MOSI**（主机→卡） |
| 6 脚 CLK | CLK | CLK | **SCK** |
| 8 脚 DAT0 | DAT0 | DAT0 | **MISO**（卡→主机） |
| 1 脚 DAT2 | DAT2 | DAT2 | 不用 |
| 4/5/7 脚 | VSS/VDD/VSS | 同左 | 电源与地 |

> **重点理解这一句**：**同一根线上的信号含义由"工作模式"决定，而不是由引脚物理位置决定。** 本项目把 CMD 当 MOSI、把 DAT0 当 MISO、把 DAT3 当 CS——**这三根线的角色被"重命名"了，它们上面跑的协议也换成了 SPI 协议**。

##### 知识点 2　为什么用 SPI 而不是 SDIO

**表 8-2 SPI 模式 vs SDIO 模式**

| 维度 | SPI 模式（本项目） | SDIO 模式 |
| --- | --- | --- |
| 引脚数 | 4 根 | 6 根（CLK/CMD/DAT0~3） |
| 最高速度 | 25 MHz（约 2.5 MB/s） | 50 MHz × 4 位（约 25 MB/s） |
| 协议复杂度 | **低**，字节流 + R1 应答 | 高，寄存器 + 状态机 + DMA |
| 硬件要求 | **任意 SPI 外设即可** | 必须有 SDIO 外设 |

**选 SPI 的理由**：`PA4~PA7` 这组线本来就是 SPI1 的引脚，**用 SPI 零成本**；而 F407VET6 的 SDIO 用的是 PC8~PC12 + PD2，引脚完全对不上。

> **SPI 模式还有个好处**：它绕过了 SD 卡复杂的"卡识别、地址分配、CRC"流程，只用几条命令就能读写。**缺点是慢，且只能单块操作（一次 512 字节）。**

#### 技能点 2　掌握 SD 协议的命令与应答格式

##### 知识点 1　CMD 命令：6 字节定长

SD 卡的每条命令固定 **6 字节**：

```
┌───────┬───────────────────────────┬──────────┐
│ CMD   │      Argument (32 位)      │  CRC7    │
│ 1字节 │  （参数，常见为地址/位图）  │ 1 字节    │
└───────┴───────────────────────────┴──────────┘
  bit7~6 = 01（传输位），bit5~0 = 命令号 0~63
```

- 第一字节：`0x40 | cmd_num`。例如 CMD0 → `0x40`，CMD17 → `0x51`；
- 中间 4 字节：32 位参数，**高位在前**；
- 最后 1 字节：CRC7 校验 + 结束位。**在 SPI 模式下，除了 `CMD0` 和 `CMD8`，其余命令的 CRC 都可以直接发 `0x01`**。

> **`CMD0` 和 `CMD8` 的 CRC 为什么必须对**：`CMD0` 固定用 `0x95`、`CMD8` 用 `0x87`（参数为 `0x000001AA` 时）。这两个是**唯二必须正确 CRC 的命令**，因为它们在"卡还没进入数据传输模式、CRC 校验仍然生效"的阶段发出。

##### 知识点 2　响应格式：R1 是基础

```
bit7  bit6  bit5      bit4      bit3     bit2       bit1       bit0
 0    参数错  地址错    擦序错     CRC错    非法命令    擦复位     IdleState
```

- **bit7 = 0 表示"响应有效"**；
- **bit0（IdleState）= 1 表示卡还在空闲态**；
- 常见值：`0x01` = 空闲态，`0x00` = 命令成功，`0x04` = 格式化错误，`0x05` = 空闲 + 非法命令。

##### 知识点 3　发完命令要"等一个 0xFF"

> **SD 规范规定**：主机发出命令后，卡**不是立即应答**的，需要最多 8 个字节的延迟才返回响应。

所以必须先"等到有应答"（`bit7 = 0`），再"检查应答内容"。**这两步分开，诊断信息就清晰了**。

##### 知识点 4　两种数据令牌

| 令牌 | 值 | 用于 |
| --- | --- | --- |
| 数据起始令牌 | **`0xFE`** | 读块时卡发出 / 写块时主机发出 |
| 数据应答令牌 | `xxx0 0101` | 写块后卡回，`(resp & 0x1F) == 0x05` 表示成功 |

---

### 环节二　bsp_tfcard.h：接口与宏定义

#### 技能点 1　完整头文件

##### 知识点 1　bsp_tfcard.h 完整代码

```c
/* bsp_tfcard.h —— TF 卡（microSD）SPI 模式驱动接口
 *
 * 依赖：bsp_spi1_bus.h（SPI1 分时复用总线层）
 * 引脚：CS = PA4，SCK = PA5，MISO = PA6，MOSI = PA7（全部 AF5）
 *
 * 使用约定：
 *   1. 所有公开函数内部会自动 BUS_Select(BUS_DEV_TF)，无需调用者手动切换；
 *   2. 初始化会自动从 328kHz 切到 21MHz，调用者无需关心速率；
 *   3. 卡被拔掉后，调用 TF_EnsureReady() 可重新初始化。
 */
#ifndef __BSP_TFCARD_H
#define __BSP_TFCARD_H

#include "main.h"
#include "bsp_spi1_bus.h"

/* ==================== 块与令牌 ==================== */
#define TF_BLOCK_SIZE            512UL     /* SD 卡固定块大小 */
#define TF_DATA_START_TOKEN      0xFE      /* 数据起始令牌 */
#define TF_DUMMY_BYTE            0xFF
#define TF_CMD_TIMEOUT_MS        200       /* 单条命令等 R1 的超时 */
#define TF_READ_TIMEOUT_MS       500       /* 读一块等令牌的超时 */
#define TF_WRITE_TIMEOUT_MS      1000      /* 写一块等 BUSY 的超时 */

/* ==================== 命令号 ==================== */
#define TF_CMD0                  0         /* GO_IDLE_STATE   复位到 idle */
#define TF_CMD8                  8         /* SEND_IF_COND    电压协商 */
#define TF_CMD9                  9         /* SEND_CSD        读 CSD */
#define TF_CMD17                 17        /* READ_SINGLE_BLOCK  */
#define TF_CMD24                 24        /* WRITE_SINGLE_BLOCK */
#define TF_CMD55                 55        /* APP_CMD         应用命令前缀 */
#define TF_CMD58                 58        /* READ_OCR        读 OCR */
#define TF_ACMD41                41        /* SD_SEND_OP_COND 初始化 */

/* ==================== CRC（只有 CMD0/CMD8 需要正确值） ==================== */
#define TF_CRC_CMD0              0x95
#define TF_CRC_CMD8              0x87
#define TF_CRC_IGNORE            0x01      /* 其余命令一律 0x01 */

/* ==================== 返回码 ==================== */
#define TF_OK                    0
#define TF_ERR_PARAM            (-1)    /* 参数错误 */
#define TF_ERR_NO_CARD          (-2)    /* 无卡/卡不响应 CMD0 */
#define TF_ERR_INIT             (-3)    /* 初始化流程失败 */
#define TF_ERR_TIMEOUT          (-4)    /* 等 R1 / 令牌 / BUSY 超时 */
#define TF_ERR_RESPONSE         (-5)    /* R1 或数据应答不符合预期 */
#define TF_ERR_TOKEN            (-6)    /* 等不到数据令牌 0xFE */

/* ==================== 卡状态（由 TF_Init 填充） ==================== */
typedef struct {
  uint8_t  version;        /* 1 = v1.x 老卡，2 = v2.0+ */
  uint8_t  blockAddr;      /* 0 = 字节寻址(SDSC)，1 = 块寻址(SDHC/SDXC) */
  uint8_t  inited;         /* 1 = 已初始化成功 */
  uint32_t capacityMB;     /* 容量（MB），0 表示未获取 */
} TF_Info_t;

extern TF_Info_t g_tfInfo;

/* ==================== 片选宏（只在本驱动内部使用） ==================== */
#define TF_CS_LOW()   HAL_GPIO_WritePin(BUS_CS_TF_PORT, BUS_CS_TF_PIN, GPIO_PIN_RESET)
#define TF_CS_HIGH()  HAL_GPIO_WritePin(BUS_CS_TF_PORT, BUS_CS_TF_PIN, GPIO_PIN_SET)

/* ==================== 对外接口 ==================== */

/* --- 初始化 --- */
int      TF_Init(void);                    /* 完整初始化（含识别与提速） */
int      TF_Check(void);                   /* 仅检测卡是否在线（发 CMD0） */
int      TF_EnsureReady(void);             /* 若未初始化则尝试初始化（热插拔自愈） */

/* --- 单块读写 --- */
int      TF_ReadBlock(uint32_t blockNum, uint8_t *pBuf);       /* CMD17 */
int      TF_WriteBlock(uint32_t blockNum, uint8_t *pBuf);      /* CMD24 */

/* --- 多块操作（循环调用单块） --- */
int      TF_ReadBlocks(uint32_t startBlock, uint8_t *pBuf, uint32_t count);
int      TF_WriteBlocks(uint32_t startBlock, uint8_t *pBuf, uint32_t count);

/* --- 信息 --- */
uint32_t TF_GetCapacityMB(void);           /* 读 CSD 算容量（可选） */

#endif /* __BSP_TFCARD_H */
```

> **为什么把卡状态放进 `TF_Info_t` 结构体而不是几个散落的全局变量**：① 一处定义、一处查看；② 将来加字段不影响已有代码；③ `TF_EnsureReady()` 可以靠 `inited` 字段做状态自愈。

---

### 环节三　bsp_tfcard.c：完整实现（上）

#### 技能点 1　底层命令与响应

##### 知识点 1　文件头与内部辅助函数

```c
/* bsp_tfcard.c —— TF 卡 SPI 模式驱动实现 */
#include "bsp_tfcard.h"
#include <string.h>
#include <stdio.h>

TF_Info_t g_tfInfo = {0, 0, 0, 0};

/* ---------- 单字节收发（透传到总线层） ---------- */
static uint8_t TF_XferByte(uint8_t txData)
{
  return BUS_ReadWriteByte(txData);
}

/* ---------- 发送 6 字节命令（不含 CS 控制） ---------- */
static void TF_SendCmdRaw(uint8_t cmd, uint32_t arg, uint8_t crc)
{
  TF_XferByte(0x40 | cmd);                 /* 命令首字节：01xxxxxx */
  TF_XferByte((arg >> 24) & 0xFF);         /* 参数高字节在前 */
  TF_XferByte((arg >> 16) & 0xFF);
  TF_XferByte((arg >>  8) & 0xFF);
  TF_XferByte( arg        & 0xFF);
  TF_XferByte(crc);                        /* CRC 或 0x01 */
}

/* ---------- 等待并读取 R1 响应 ----------
 * 原理：卡不会立即应答，需要最多 8 字节延迟。
 *       循环发 0xFF 直到读到 bit7 = 0 的字节；全 0xFF 表示卡没应答。
 */
static uint8_t TF_WaitR1(uint32_t timeout_ms)
{
  uint8_t  ret = 0xFF;
  uint32_t tickstart = HAL_GetTick();

  do {
    ret = TF_XferByte(TF_DUMMY_BYTE);
    if ((HAL_GetTick() - tickstart) > timeout_ms) return 0xFF;
  } while (ret == 0xFF);

  return ret;
}

/* ---------- 发送命令 + 等 R1（CS 保持低，由调用者决定何时拉高） ---------- */
static uint8_t TF_SendCmd(uint8_t cmd, uint32_t arg, uint8_t crc)
{
  /* 发命令前先给一个字节的时钟，让卡完成上一条命令的内部处理 */
  TF_CS_HIGH();
  TF_XferByte(TF_DUMMY_BYTE);

  TF_CS_LOW();
  TF_SendCmdRaw(cmd, arg, crc);

  return TF_WaitR1(TF_CMD_TIMEOUT_MS);
}

/* ---------- 结束一次事务：拉高 CS，补一个时钟 ---------- */
static void TF_EndTransaction(void)
{
  TF_CS_HIGH();
  TF_XferByte(TF_DUMMY_BYTE);
}

/* ---------- 上电 80 个暖机时钟（CS 必须高） ---------- */
static void TF_PowerOnClock(void)
{
  TF_CS_HIGH();
  for (uint8_t i = 0; i < 10; i++)       /* 10 字节 = 80 个时钟，规范要求 ≥74 */
  {
    TF_XferByte(TF_DUMMY_BYTE);
  }
}
```

##### 知识点 2　为什么 CS 由调用者控制

```c
/* CMD17 的完整事务跨越"命令 + R1 + 数据令牌 + 512 字节数据"，
   全程 CS 必须保持低。如果 TF_SendCmd() 内部就把 CS 拉高，
   后面的数据就读不到了。 */
```

> **这是 SD 卡驱动最容易被写错的结构性问题**：把"发命令"和"结束事务"分开，而不是让 `TF_SendCmd` 一把梭。**记住一句：CS 的生命周期 = 一笔完整事务，而不是一条命令。**

#### 技能点 2　检测与初始化

##### 知识点 1　检测与完整初始化

```c
/**
 * @brief  检测 TF 卡是否插入并在线
 * @retval TF_OK / TF_ERR_NO_CARD
 * @note   方法：发 CMD0，若卡在，会返回 0x01（idle 态）。
 *         CMD0 是唯一在任何状态下都会被响应的命令，所以它既是"检测"也是"复位"。
 */
int TF_Check(void)
{
  uint8_t r1 = 0xFF;
  uint8_t retry;

  BUS_Select(BUS_DEV_TF, BUS_SPEED_328K);   /* 慢速：≤400kHz */
  TF_PowerOnClock();

  for (retry = 0; retry < 10; retry++)
  {
    r1 = TF_SendCmd(TF_CMD0, 0x00000000, TF_CRC_CMD0);
    TF_EndTransaction();
    if (r1 == 0x01) break;
    HAL_Delay(1);
  }

  if (r1 == 0x01)
  {
    printf("[TF] 检测到卡（CMD0 响应 0x01，空闲态）\r\n");
    return TF_OK;
  }

  printf("[TF] 未检测到卡（CMD0 响应 0x%02X）\r\n", r1);
  return TF_ERR_NO_CARD;
}
```

```c
/**
 * @brief  TF 卡 SPI 模式完整初始化
 * @retval TF_OK / 各类错误码
 * @note   流程：CMD0 → CMD8 → (CMD55+ACMD41 循环) → CMD58，最后提速到 21MHz
 */
int TF_Init(void)
{
  uint8_t  r1;
  uint8_t  buf[4];
  uint32_t retry;

  /* 清零状态 */
  g_tfInfo.version   = 0;
  g_tfInfo.blockAddr = 0;
  g_tfInfo.inited    = 0;
  g_tfInfo.capacityMB = 0;

  /* ---------- 步骤 0：切到 TF 卡 + 慢速 ---------- */
  BUS_Select(BUS_DEV_TF, BUS_SPEED_328K);
  TF_PowerOnClock();
  HAL_Delay(2);                              /* 给卡上电复位时间 */

  /* ---------- 步骤 1：CMD0 复位到 idle ---------- */
  for (retry = 0; retry < 20; retry++)
  {
    r1 = TF_SendCmd(TF_CMD0, 0x00000000, TF_CRC_CMD0);
    TF_EndTransaction();
    if (r1 == 0x01) break;
    HAL_Delay(1);
  }
  if (r1 != 0x01)
  {
    printf("[TF] CMD0 失败（R1=0x%02X），卡未响应\r\n", r1);
    return TF_ERR_NO_CARD;
  }

  /* ---------- 步骤 2：CMD8 电压协商 ---------- */
  r1 = TF_SendCmd(TF_CMD8, 0x000001AA, TF_CRC_CMD8);
  if (r1 == 0x01)
  {
    for (int i = 0; i < 4; i++) buf[i] = TF_XferByte(TF_DUMMY_BYTE);
    TF_EndTransaction();

    if ((buf[2] == 0x01) && (buf[3] == 0xAA))
    {
      g_tfInfo.version = 2;
      printf("[TF] CMD8 响应正常，v2.0 卡\r\n");
    }
    else
    {
      printf("[TF] CMD8 回显校验失败（收到 %02X %02X）\r\n", buf[2], buf[3]);
      return TF_ERR_INIT;
    }
  }
  else if (r1 == 0x05)                        /* 非法命令 = v1 老卡 */
  {
    TF_EndTransaction();
    g_tfInfo.version = 1;
    printf("[TF] CMD8 无响应，按 v1.x 老卡处理\r\n");
  }
  else
  {
    TF_EndTransaction();
    printf("[TF] CMD8 异常响应 0x%02X\r\n", r1);
    return TF_ERR_INIT;
  }

  /* ---------- 步骤 3：ACMD41 循环，直到 R1 = 0x00 ---------- */
  for (retry = 0; retry < 200; retry++)
  {
    /* 3a. CMD55：告诉卡"下一条是应用命令" */
    r1 = TF_SendCmd(TF_CMD55, 0x00000000, TF_CRC_IGNORE);
    TF_EndTransaction();
    if (r1 > 0x01)
    {
      printf("[TF] CMD55 失败（R1=0x%02X）\r\n", r1);
      return TF_ERR_INIT;
    }

    /* 3b. ACMD41：bit30 = HCS，置 1 表示主机支持高容量卡 */
    r1 = TF_SendCmd(TF_ACMD41, 0x40000000, TF_CRC_IGNORE);
    TF_EndTransaction();

    if (r1 == 0x00) break;                    /* 初始化完成 */

    HAL_Delay(10);                            /* 给卡真实时间完成内部初始化 */
  }
  if (r1 != 0x00)
  {
    printf("[TF] ACMD41 超时（重试 %lu 次），卡初始化失败\r\n", (unsigned long)retry);
    return TF_ERR_INIT;
  }

  /* ---------- 步骤 4：CMD58 读 OCR，判断寻址方式 ---------- */
  r1 = TF_SendCmd(TF_CMD58, 0x00000000, TF_CRC_IGNORE);
  if (r1 == 0x00)
  {
    for (int i = 0; i < 4; i++) buf[i] = TF_XferByte(TF_DUMMY_BYTE);
    /* OCR 的 bit30 = CCS：1 = SDHC/SDXC（块寻址），0 = SDSC（字节寻址）
       buf[0] 是 OCR 最高字节，bit30 落在它的 bit6 上 */
    g_tfInfo.blockAddr = ((buf[0] & 0x40) != 0) ? 1 : 0;

    if (g_tfInfo.blockAddr)
      printf("[TF] 高容量卡（SDHC/SDXC），块寻址，单块 512 字节\r\n");
    else
      printf("[TF] 标准容量卡（SDSC），字节寻址\r\n");
  }
  TF_EndTransaction();

  /* ---------- 步骤 5：提速到 21MHz（识别完成后才能提速） ---------- */
  BUS_Select(BUS_DEV_TF, BUS_SPEED_21M);

  g_tfInfo.inited = 1;
  printf("[TF] 初始化成功（%s，%lu MHz SCK）\r\n",
         g_tfInfo.blockAddr ? "块寻址" : "字节寻址", 21UL);
  return TF_OK;
}
```

##### 知识点 2　三个关键细节

1. **`HAL_Delay(10)` 在 ACMD41 循环里不能省**：卡的内部初始化需要真实时间（几毫秒到几百毫秒）。不停发命令而不给延时，`r1` 永远是 `0x01`；
2. **ACMD41 的参数 `0x40000000`**：bit30 = HCS（Host Capacity Support），置 1 表示"我支持高容量卡"。**如果卡是 SDHC/SDXC，不置这一位它就不会完成初始化**；
3. **CMD58 的 bit30 决定地址单位**：SDHC/SDXC 是"**块寻址**"（参数是块号），SDSC 是"**字节寻址**"（参数是字节偏移）。**算错了就读到错误的扇区。**

> **本项目约定**：后面所有的读写都按 **块寻址** 处理。代码里用 `g_tfInfo.blockAddr` 自动判断并换算，**调用者不用关心**。

---

### 环节四　bsp_tfcard.c：完整实现（下）

#### 技能点 1　单块读写

##### 知识点 1　CMD17 读块

```c
/**
 * @brief  读取一个 512 字节的数据块
 * @param  blockNum: 块号（SDHC/SDXC 从 0 开始；SDSC 内部自动换算成字节偏移）
 * @param  pBuf: 数据缓冲区，必须 ≥512 字节
 * @retval TF_OK / 错误码
 */
int TF_ReadBlock(uint32_t blockNum, uint8_t *pBuf)
{
  uint8_t  r1;
  uint32_t tickstart;
  uint32_t arg;
  uint32_t i;

  if (pBuf == NULL) return TF_ERR_PARAM;
  if (!g_tfInfo.inited) return TF_ERR_INIT;

  /* SDSC 是字节寻址：块号 × 512 = 字节偏移；SDHC/SDXC 直接用块号 */
  arg = g_tfInfo.blockAddr ? blockNum : (blockNum * TF_BLOCK_SIZE);

  /* ---------- ① 发 CMD17 ---------- */
  r1 = TF_SendCmd(TF_CMD17, arg, TF_CRC_IGNORE);
  if (r1 != 0x00)
  {
    TF_EndTransaction();
    printf("[TF] CMD17 失败，R1 = 0x%02X\r\n", r1);
    return TF_ERR_RESPONSE;
  }

  /* ---------- ② 等数据起始令牌 0xFE ---------- */
  tickstart = HAL_GetTick();
  do {
    r1 = TF_XferByte(TF_DUMMY_BYTE);
    if ((HAL_GetTick() - tickstart) > TF_READ_TIMEOUT_MS)
    {
      TF_EndTransaction();
      printf("[TF] 等待数据令牌超时（最后一次读到 0x%02X）\r\n", r1);
      return TF_ERR_TOKEN;
    }
  } while (r1 != TF_DATA_START_TOKEN);

  /* ---------- ③ 读 512 字节数据 ---------- */
  for (i = 0; i < TF_BLOCK_SIZE; i++)
  {
    pBuf[i] = TF_XferByte(TF_DUMMY_BYTE);
  }

  /* ---------- ④ 读并丢弃 2 字节 CRC ---------- */
  TF_XferByte(TF_DUMMY_BYTE);
  TF_XferByte(TF_DUMMY_BYTE);

  /* ---------- ⑤ 结束 ---------- */
  TF_EndTransaction();
  return TF_OK;
}
```

> **判断顺序**：**先看 R1，再看令牌**。R1 不是 `0x00` 就直接返回，不要傻等 `0xFE`——等不到，因为卡压根没开始准备数据。

##### 知识点 2　CMD24 写块

```c
/**
 * @brief  写入一个 512 字节的数据块
 * @param  blockNum: 块号
 * @param  pBuf: 待写入数据，长度 512 字节
 * @retval TF_OK / 错误码
 */
int TF_WriteBlock(uint32_t blockNum, uint8_t *pBuf)
{
  uint8_t  r1, resp;
  uint32_t tickstart;
  uint32_t arg;
  uint32_t i;

  if (pBuf == NULL) return TF_ERR_PARAM;
  if (!g_tfInfo.inited) return TF_ERR_INIT;

  arg = g_tfInfo.blockAddr ? blockNum : (blockNum * TF_BLOCK_SIZE);

  /* ---------- ① 发 CMD24 ---------- */
  r1 = TF_SendCmd(TF_CMD24, arg, TF_CRC_IGNORE);
  if (r1 != 0x00)
  {
    TF_EndTransaction();
    printf("[TF] CMD24 失败，R1 = 0x%02X\r\n", r1);
    return TF_ERR_RESPONSE;
  }

  /* ---------- ② 发送数据起始令牌 + 512 字节 ---------- */
  TF_XferByte(TF_DATA_START_TOKEN);            /* 0xFE */
  for (i = 0; i < TF_BLOCK_SIZE; i++)
  {
    TF_XferByte(pBuf[i]);
  }
  TF_XferByte(TF_DUMMY_BYTE);                  /* CRC 占位 */
  TF_XferByte(TF_DUMMY_BYTE);

  /* ---------- ③ 读数据应答令牌 ----------
     格式：xxx0 0101 表示成功，屏蔽高 3 位后应为 0x05 */
  resp = TF_XferByte(TF_DUMMY_BYTE);
  if ((resp & 0x1F) != 0x05)
  {
    TF_EndTransaction();
    printf("[TF] 数据应答失败，resp = 0x%02X（期望 bit4~1 = 010）\r\n", resp);
    return TF_ERR_RESPONSE;
  }

  /* ---------- ④ 等卡内部编程结束（BUSY 期间 MISO 为 0x00） ---------- */
  tickstart = HAL_GetTick();
  do {
    resp = TF_XferByte(TF_DUMMY_BYTE);
    if ((HAL_GetTick() - tickstart) > TF_WRITE_TIMEOUT_MS)
    {
      TF_EndTransaction();
      printf("[TF] 写块 BUSY 超时\r\n");
      return TF_ERR_TIMEOUT;
    }
  } while (resp == 0x00);                      /* 还在忙 */

  /* ---------- ⑤ 结束 ---------- */
  TF_EndTransaction();
  return TF_OK;
}
```

##### 知识点 3　两个"忙"不要混

**表 8-3 三种等待的对比**

| 等待 | 在哪一步 | 现象 | 判断条件 |
| --- | --- | --- | --- |
| **等 R1 响应** | 发完命令后 | MISO 一直 `0xFF` | 读到 `bit7 = 0`（即 `!= 0xFF`）即结束 |
| **等数据令牌** | R1 成功后 | MISO 一直 `0xFF` | 读到 `0xFE` |
| **等 BUSY（写入）** | 数据应答后 | MISO 一直 `0x00` | 读到 `!= 0x00`（通常为 `0xFF`） |

> **注意最后一种的判断方向与前两种相反**：前两种是"**等一个不等于 0xFF 的值**"，最后一种是"**等一个不等于 0x00 的值**"。**"卡忙"在 SD 协议里表现为 MISO 持续输出 0x00**，这是它和"卡没反应（0xFF）"的相反之处——**如果搞混，写块会立刻返回"成功"，但数据其实没写进去。**

#### 技能点 2　多块操作与自愈

##### 知识点 1　多块读写（循环单块）

```c
/**
 * @brief  连续读多个块（内部循环调用 TF_ReadBlock）
 * @note   单块命令的吞吐率低于 CMD18 多块读，但实现简单、容错好
 */
int TF_ReadBlocks(uint32_t startBlock, uint8_t *pBuf, uint32_t count)
{
  uint32_t i;
  int      ret;

  if (pBuf == NULL || count == 0) return TF_ERR_PARAM;

  for (i = 0; i < count; i++)
  {
    ret = TF_ReadBlock(startBlock + i, pBuf + i * TF_BLOCK_SIZE);
    if (ret != TF_OK) return ret;
  }
  return TF_OK;
}

/**
 * @brief  连续写多个块
 */
int TF_WriteBlocks(uint32_t startBlock, uint8_t *pBuf, uint32_t count)
{
  uint32_t i;
  int      ret;

  if (pBuf == NULL || count == 0) return TF_ERR_PARAM;

  for (i = 0; i < count; i++)
  {
    ret = TF_WriteBlock(startBlock + i, pBuf + i * TF_BLOCK_SIZE);
    if (ret != TF_OK) return ret;
  }
  return TF_OK;
}
```

> **为什么不用 CMD18/CMD25（多块读写）**：多块命令需要处理 CMD12（停止传输）和卡自动递增的细节，**出错后更难恢复**。本项目的数据量小、对吞吐率要求不高，**循环单块是更稳妥的工程选择**。要做大数据量时再升级。

##### 知识点 2　热插拔自愈

```c
/**
 * @brief  确保卡就绪：未初始化则尝试初始化一次
 * @retval TF_OK / 错误码
 * @note   典型用法：每次上层操作前调一次，卡被拔掉再插回来能自动恢复
 */
int TF_EnsureReady(void)
{
  if (g_tfInfo.inited)
  {
    return TF_OK;
  }
  return TF_Init();
}
```

> **这类"状态自愈"的设计**，是把一个"能跑的 demo"变成"能用的产品"的关键一步。**嵌入式设备的部署环境千变万化，能自己恢复的程序才叫可靠。**

##### 知识点 3　读 CSD 获取容量（可选）

```c
/**
 * @brief  读取并解析 TF 卡容量（仅针对 SDHC/SDXC）
 * @retval 容量（MB）；失败返回 0
 * @note   CSD 位域在不同版本卡上不同，实际工程多用文件系统读取，
 *         本函数用于"知道容量从哪来"的教学目的
 */
uint32_t TF_GetCapacityMB(void)
{
  uint8_t  r1, csd[16];
  uint32_t c_size, tickstart;

  if (!g_tfInfo.inited) return 0;

  r1 = TF_SendCmd(TF_CMD9, 0x00000000, TF_CRC_IGNORE);   /* CMD9 = SEND_CSD */
  if (r1 != 0x00)
  {
    TF_EndTransaction();
    return 0;
  }

  /* 等数据令牌 */
  tickstart = HAL_GetTick();
  do {
    r1 = TF_XferByte(TF_DUMMY_BYTE);
    if ((HAL_GetTick() - tickstart) > TF_READ_TIMEOUT_MS)
    {
      TF_EndTransaction();
      return 0;
    }
  } while (r1 != TF_DATA_START_TOKEN);

  for (int i = 0; i < 16; i++) csd[i] = TF_XferByte(TF_DUMMY_BYTE);
  TF_XferByte(TF_DUMMY_BYTE);        /* CRC */
  TF_XferByte(TF_DUMMY_BYTE);
  TF_EndTransaction();

  /* CSD 的 C_SIZE（22 位）位于 bit 69~48，在 16 字节数组中的位置如下 */
  c_size = ((uint32_t)(csd[7] & 0x3F) << 16)
         | ((uint32_t)csd[8] << 8)
         |  (uint32_t)csd[9];

  /* SDHC/SDXC：容量 = (C_SIZE + 1) × 512KB */
  g_tfInfo.capacityMB = (c_size + 1) * 512UL / 1024UL;
  printf("[TF] 容量 = %lu MB\r\n", (unsigned long)g_tfInfo.capacityMB);
  return g_tfInfo.capacityMB;
}
```

---

### 环节五　TF 卡测试与验证

#### 技能点 1　回环测试

##### 知识点 1　选一个"安全"的测试块

**千万不要对块 0 做写测试**——那是分区表/引导扇区，写坏了卡就"变砖"（需要重新格式化）。

```c
#define TF_TEST_BLOCK   2048      /* 保守起见用块 2048（约 1MB 位置） */
```

**为什么选靠后的块**：即使那块区域有文件系统数据，写坏了顶多丢文件，**不会破坏分区表**。测试前最好用读操作看一眼目标块的内容——**若全是 `0x00` 或 `0xFF`，大概率是空闲区。**

##### 知识点 2　完整测试流程

```c
void TF_Test(void)
{
  static uint8_t tx[TF_BLOCK_SIZE];
  static uint8_t rx[TF_BLOCK_SIZE];
  uint32_t i;

  printf("\r\n========== TF 卡读写测试 ==========\r\n");

  /* ---------- ① 先读一次目标块，看看原来是什么 ---------- */
  if (TF_ReadBlock(TF_TEST_BLOCK, rx) != TF_OK)
  {
    printf("[TF] 预读失败，测试中止\r\n");
    return;
  }
  printf("[TF] 块 %lu 预读成功，首字节 0x%02X\r\n",
         (unsigned long)TF_TEST_BLOCK, rx[0]);

  /* ---------- ② 构造测试数据 ---------- */
  for (i = 0; i < TF_BLOCK_SIZE; i++)
  {
    tx[i] = (uint8_t)(i & 0xFF);
  }
  memcpy(tx, "TF-CARD SPI TEST OK!", 20);       /* 前 20 字节盖可读文本 */

  /* ---------- ③ 写入 ---------- */
  if (TF_WriteBlock(TF_TEST_BLOCK, tx) != TF_OK)
  {
    printf("[TF] 写块失败\r\n");
    return;
  }
  printf("[TF] 写入 512 字节完成\r\n");

  /* ---------- ④ 读回并比对 ---------- */
  memset(rx, 0, sizeof(rx));
  if (TF_ReadBlock(TF_TEST_BLOCK, rx) != TF_OK)
  {
    printf("[TF] 回读失败\r\n");
    return;
  }

  if (memcmp(tx, rx, TF_BLOCK_SIZE) == 0)
  {
    printf("★ TF 卡块回环校验通过\r\n");
    printf("[TF] 读回内容：%.20s\r\n", rx);
  }
  else
  {
    for (i = 0; i < TF_BLOCK_SIZE; i++)
    {
      if (tx[i] != rx[i])
      {
        printf("✗ 第 %lu 字节不一致：写 0x%02X / 读 0x%02X\r\n",
               (unsigned long)i, tx[i], rx[i]);
        break;
      }
    }
  }
}
```

> **`memcpy(tx, "TF-CARD SPI TEST OK!", 20)` 的作用**：在二进制递增数据前面盖一段可读文本。这样回读后**肉眼就能看出对不对**——打印出来是 `TF-CARD SPI TEST OK!` 就一眼确认"通了"。

#### 技能点 2　读块 0 检查文件系统

##### 知识点 1　块 0 的 0x55AA 签名

```c
void TF_DumpBlock0(void)
{
  static uint8_t buf[TF_BLOCK_SIZE];

  if (TF_ReadBlock(0, buf) != TF_OK) return;

  printf("[TF] 块 0 前 16 字节：");
  for (int i = 0; i < 16; i++) printf("%02X ", buf[i]);
  printf("\r\n");

  if ((buf[510] == 0x55) && (buf[511] == 0xAA))
    printf("[TF] 检测到有效引导扇区（卡已格式化）\r\n");
  else
    printf("[TF] 块 0 无 0x55AA 标记（卡可能未格式化）\r\n");
}
```

> **`0x55 0xAA` 是 FAT 文件系统引导扇区的"签名"**，位于偏移 510/511。这个小检查能一次性区分"卡读写正常但没格式化"和"卡读写本身就不通"——**后者是硬件问题，前者重新格式化就好。**

##### 知识点 2　TF 卡故障速查

**表 8-4 TF 卡故障速查**

| 现象 | 最可能原因 | 排查步骤 | 解决方案 |
| --- | --- | --- | --- |
| `TF_Check()` 返回 `0xFF` | ① 卡没插好 ② 供电不足 ③ 模式不是 0 ④ 少了 80 个暖机时钟 | 量 VDD=3.3V，看 CS/MISO | 补 80 时钟、确认 CPOL=0/CPHA=1Edge |
| CMD0 有响应但 ACMD41 一直 `0x01` | ① 循环里没延时 ② 参数没置 HCS 位 | 看 ACMD41 参数 | 加 `HAL_Delay(10)`；参数用 `0x40000000` |
| CMD8 返回 `0x05` | v1 老卡（正常现象） | — | 代码已按 v1 处理 |
| CMD17 返回 `0x40` | 块号超出卡容量 | 打印块号与卡容量 | 换合法块号 |
| 读块时等不到 `0xFE` | R1 不是 0x00 就开始等了 | 检查 R1 判断逻辑 | **先判 R1，再等令牌** |
| 写块"成功"但读回不对 | 数据应答判断错 / 没等 BUSY | 看是否判 `(resp & 0x1F) == 0x05` | 补 BUSY 等待（MISO 回到非 0x00） |
| 写卡时程序复位 | 电源跌落（卡写入瞬态电流大） | 量写入瞬间 VDD | 加 10µF~100µF 储能电容 |
| 拔卡后程序死等 | 没有超时机制 | 看每个 while 循环 | 全部加超时并返回错误码 |
| **TF 卡不响应但 FLASH 正常** | 总线切换没切到 TF 侧 | 示波器看 PA5 有无 SCK | 查 `BUS_Select(BUS_DEV_TF,...)` 的分支 |

---

<!--CHUNK-END-->
