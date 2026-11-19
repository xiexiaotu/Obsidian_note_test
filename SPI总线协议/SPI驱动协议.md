# SPI 驱动协议——SPI1 共享总线读写 W25Q64 FLASH 与 TF 卡（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F4xx 中文数据手册》SPI 引脚复用表、《RM0090 STM32F407 参考手册》SPI/I2S 章节、《W25Q64FV 数据手册》（指令集与时序）、《SD Specifications Part 1 Physical Layer Simplified Specification》（SPI 模式），以及野火《STM32 HAL 库开发实战指南——基于霸天虎开发板》**第 24 章 SPI-读写串行 FLASH**（本章的协议讲解、指令表与驱动写法以此为基础改写，并扩展为"一条 SPI1 共享总线挂两个器件"）。
> **学习提示**：配合参考手册中 `SPI_CR1`（CPOL/CPHA/MSTR/BR/SPE/SSI/DFF）、`SPI_CR2`（中断与 DMA 使能）、`SPI_SR`（TXE/RXNE/BSY/OVR/MODF）三个寄存器的说明一起阅读，效果更佳。
> **特别说明**：本笔记以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 **STM32 HAL 库**，所有实验结果**通过 USART1 + printf 输出到串口助手**（115200-8-N-1）。
> **本项目的两件被驱动对象与引脚**（工程实际接线表）：
>
> | 器件 | 协议 | CS | CLK | MISO | MOSI |
> | --- | --- | --- | --- | --- | --- |
> | **TF-CARD** | SPI | **PA4** | **PA5** | **PA6** | **PA7** |
> | **Flash（W25Q64）** | SPI | **PA15** | **PB3** | **PB4**（SDO） | **PB5**（SDI） |
>
> **本项目全部使用 SPI1**，两组引脚**都是 SPI1 的 AF5 复用引脚**。
> **重要澄清**：`PA5/PB3` 都是 `SPI1_SCK`、`PA6/PB4` 都是 `SPI1_MISO`、`PA7/PB5` 都是 `SPI1_MOSI`。**这 6 根信号线一次性全部配成 AF5，运行期永不改动**；`PA4` 与 `PA15` 是两个**普通 GPIO 片选**，程序通过"拉低哪一根 CS"来决定与谁通讯。
> 所以本项目**没有引脚切换、没有分时复用**——**共享总线 + 独立片选**，这正是 SPI 多从机的标准做法。

---

> **笔记结构说明（五级组织法）**
> 本笔记按 **项目（一级标题）→ 任务（二级标题）→ 环节（三级标题）→ 技能点（四级标题）→ 知识点（五级标题）** 逐层拆解。
> ① 一级只有 1 个，就是"项目"本身；
> ② 二级是 9 个可独立验收的"任务"，按"**认知 → 建工程 → 公共总线层 → 驱动 FLASH → 驱动 TF 卡 → 集成收尾**"由浅入深排列；
> ③ 三级本应叫"工序"，但本项目是"先设计、再编码、后验证"的软件开发流程，叫工序（偏制造语境）不够贴切，**故全文统一用"环节"替代"工序"**；
> ④ 四级"技能点"回答"**这一步要会做什么**"，五级"知识点"回答"**为什么这么做**"。

---

## 项目全景：一图看懂本笔记的任务链

```
                    ┌──────────────────────────────────────────────┐
                    │  项目 SPI-STORAGE                             │
                    │  用一条 SPI1 共享总线驱动两片存储器件          │
                    └───────────────────┬──────────────────────────┘
                                        │
   任务一 导入与拆解 ──────────────────►│  需求 → 引脚 → 共享总线定案
   任务二 协议认知   ──────────────────►│  四根线 + 四种模式 + 多从机
   任务三 外设认知   ──────────────────►│  框图 + 寄存器 + HAL 句柄
   任务四 工程搭建   ──────────────────►│  CubeMX：SPI1(两组引脚) + 双 CS
   任务五 公共总线层 ─────────────────►│  ★ 选中器件 + 速率切换
   任务六 FLASH 驱动 ──────────────────►│  指令集 + 擦 + 写 + 读（完整代码）
   任务七 FLASH 联调 ──────────────────►│  读 ID + 回环 + 掉电保持
   任务八 TF 卡驱动  ──────────────────►│  CMD0→CMD8→ACMD41→CMD58（完整代码）
   任务九 集成与收尾 ──────────────────►│  双器件共存 + 容错 + 验收清单
```

**表 0-1 本项目任务清单与验收标准**

| 任务 | 名称 | 一句话目标 | 验收标准 |
| --- | --- | --- | --- |
| 一 | 项目导入与需求拆解 | 把需求翻译成引脚、外设与验收指标 | 产出一张共享总线引脚分配表 |
| 二 | SPI 协议认知 | 说清物理层与协议层 | 能画出模式 0 的时序并说明采样沿 |
| 三 | STM32 SPI 外设认知 | 看懂框图、寄存器与 HAL 封装 | 能默写主机收发四步流程 |
| 四 | CubeMX 工程搭建 | 生成可编译的工程骨架 | 8 根信号线全部 AF5，无引脚告警 |
| 五 | **SPI1 公共总线层** | 用一套 API 选中器件并切换速率 | 选中谁就只有谁响应 |
| 六 | W25Q64 驱动开发 | 提供**完整可编译**的驱动文件 | `bsp_w25q64.c` 全部函数实现 |
| 七 | W25Q64 联调验证 | 串口打印回环与掉电校验结果 | 校验一致、断电后数据完好 |
| 八 | TF 卡 SPI 驱动 | 初始化 + 单块读写 | `TF_Init()` 成功、512B 回环一致 |
| 九 | 项目集成与收尾 | 双器件共存、容错、可维护 | 交替读写 20 轮全部正确 |

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

1. **W25Q64 固定接 PA15(CS)、PB3(CLK)、PB4(MISO/SDO)、PB5(MOSI/SDI)**；
2. **TF 卡固定接 PA4(CS)、PA5(CLK)、PA6(MISO)、PA7(MOSI)**；
3. **两个器件都只走 SPI1**——工程已定，不考虑 SPI2/SPI3；
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

### 环节二　看清芯片资源：两组引脚怎么拼成一条总线

#### 技能点 1　查表确认：两组引脚都是 SPI1

##### 知识点 1　STM32F407VET6 的 SPI 引脚映射

F407 有 **3 个 SPI 外设**：SPI1 挂在 **APB2（PCLK2 = 84MHz）**，SPI2/SPI3 挂在 **APB1（PCLK1 = 42MHz）**。SCK 的最高频率是所在总线时钟的 1/2，所以 **SPI1 最快 42MHz，SPI2/SPI3 最快 21MHz**。

**表 1-4 STM32F407VET6 的 SPI1 引脚映射（LQFP100）**

| SPI1 信号 | 第一组引脚 | 第二组引脚 | 本项目用途 |
| --- | --- | --- | --- |
| **NSS**（片选） | PA4 | PA15 | 都用**普通 GPIO** 软件控制 |
| **SCK**（时钟） | **PA5** | **PB3** | PA5→TF 卡，PB3→Flash |
| **MISO**（主入） | **PA6** | **PB4** | PA6→TF 卡，PB4→Flash（SDO） |
| **MOSI**（主出） | **PA7** | **PB5** | PA7→TF 卡，PB5→Flash（SDI） |

> **这张表是本项目的全部秘密**，逐行读一遍：
> - `PA5` 与 `PB3` **都是 SPI1_SCK 的输出候选脚**；
> - `PA6` 与 `PB4` **都是 SPI1_MISO 的输入候选脚**；
> - `PA7` 与 `PB5` **都是 SPI1_MOSI 的输出候选脚**。
> **也就是说：两组引脚本来就是你那张接线表里的 SPI1，一个外设，两种落地位置。**

##### 知识点 2　AF5：两组引脚共用同一个复用编号

STM32 的引脚是"复用"的：同一个物理引脚，靠寄存器里写入的 **AF 编号** 决定它此刻听谁指挥。F407 上 **SPI1/SPI2/SPI4/SPI5/SPI6 全部是 AF5**（只有 SPI3 是 AF6）。

所以本项目**两组引脚全部写 AF5**，这一点从头到尾不会变。

#### 技能点 2　为什么这 6 根线可以"同时接上"

##### 知识点 1　输出信号可以广播，输入要靠片选隔离

这是理解共享总线最关键的一步。SPI1 的三种信号性质不同：

```
                        ┌──────────────────────────────────┐
                        │          SPI1 外设内部            │
                        │                                  │
     SCK  ──────────────┤ 输出  ──┬──────────┬─────────────┼──► PA5  ──► TF卡 CLK
     （广播）            │         └──────────┴──► PB3 ─────┼──► PB3  ──► Flash CLK
                        │                                  │
     MOSI ──────────────┤ 输出  ──┬──────────┬─────────────┼──► PA7  ──► TF卡 MOSI
     （广播）            │         └──────────┴──► PB5 ─────┼──► PB5  ──► Flash MOSI
                        │                                  │
     MISO ◄─────────────┤ 输入  ◄─┬──────────┬─────────────┼──◄ PA6  ◄── TF卡 MISO
     （只能选一个源）    │         └──────────┴──► PB4 ─────┼──◄ PB4  ◄── Flash SDO
                        └──────────────────────────────────┘
```

1. **SCK 与 MOSI 是纯输出**：同一条内部信号送到两个引脚是完全合法的（就是"广播"）。两个器件都会收到时钟和主机数据；
2. **MISO 是输入**：SPI 外设在任一时刻只会从**一个**引脚取样。但注意——**"没被片选"的器件会把 MISO 置为高阻态（释放总线）**，所以实际上只有被选中那一个在驱动 MISO，不会打架；
3. **片选 CS 是"总开关"**：CS 为高的器件**彻底忽略 SCK/MOSI**、并**释放 MISO**。

> **一句话总结**：**SCK/MOSI/MISO 三根线并联共享（因为 SPI 是总线），靠两根独立的 CS 决定"跟谁说话"。** 这不是什么特殊技巧，**这正是 SPI 协议设计多从机的本意**。

##### 知识点 2　为什么之前的"分时复用"是错的

我上一版笔记把 PB3~PB5 配成普通 GPIO、运行时按需切换，那是**过度设计**，而且带来三个真实的问题：

**表 1-5 两种思路的对比**

| 对比项 | ❌ 引脚分时复用（错误做法） | ✅ 共享总线 + 片选（正确做法） |
| --- | --- | --- |
| 6 根信号线的配置 | 运行期反复在 AF5 与模拟态之间切换 | **一次性配成 AF5，永不改动** |
| 是否需要切换 CPOL/CPHA | 需要（每次切换都要关外设重配） | **不需要**（两个器件统一模式 0） |
| 切换开销 | 每次约 2~5µs | **0** |
| 代码复杂度 | 多一个 `bsp_spi1_bus` 切换层，约 260 行 | **只需一个选器件的函数，约 40 行** |
| MISO 冲突风险 | 有（要靠模拟态硬隔离） | **无**（靠 CS 让从机自己释放） |
| 是否符合 SPI 规范 | 否（SPI 本来就是靠片选区分从机） | **是** |

> **工程箴言**：**能用协议本身解决的问题，就不要用额外的硬件操作去绕。** SPI 已经有片选机制，我们就不该再去动引脚。

##### 知识点 3　共同模式的约束：两个器件都必须用模式 0

共享总线还有一个**必须提前算清楚**的连带约束：

**表 1-6 两个器件的 SPI 参数**

| 参数 | W25Q64 | TF 卡（SPI 模式） | 能否共存 |
| --- | --- | --- | --- |
| 数据帧 | 8 位 | 8 位 | ✅ 一致 |
| 位序 | MSB 先行 | MSB 先行 | ✅ 一致 |
| **CPOL/CPHA** | **支持模式 0 和模式 3** | **只支持模式 0** | ✅ **取模式 0** |
| 时钟 | 最高 104MHz（0x03 读约 50MHz） | 最高 25MHz（初始化 ≤400kHz） | ✅ 取 21MHz |

> **关键结论**：总线共享后，**SPI1 的 CPOL/CPHA 只能有一个值**。TF 卡只支持模式 0，所以**整个总线统一用模式 0**。
> 好消息是 **W25Q64 同时支持模式 0 和模式 3**（数据手册 SPI Mode 0 & Mode 3），所以 FLASH 用模式 0 完全没问题。**野火第 24 章用的是模式 3，照抄的话必须改这两行——这是本项目最容易踩的坑。**

---

### 环节三　释放 JTAG 占用的引脚

#### 技能点 1　定位"三个被借走的引脚"

##### 知识点 1　PA15 / PB3 / PB4 复位后不是普通 IO

很多人卡在这里：CubeMX 里明明把 SPI1 配好了，烧录后 FLASH 毫无反应，读 ID 恒为 `0xFF`。**根因往往不是 SPI 配置错，而是这三个引脚上电后默认是 JTAG 调试口。**

**表 1-7 被 JTAG 默认占用的引脚**

| 引脚 | 复位默认功能 | 本项目要用它做 | 是否冲突 |
| --- | --- | --- | --- |
| PA13 | JTMS / **SWDIO** | 保留（调试用） | 保留 |
| PA14 | JTCK / **SWCLK** | 保留（调试用） | 保留 |
| **PA15** | **JTDI** | Flash 的 CS | ⚠️ **冲突，必须释放** |
| **PB3** | **JTDO / TRACESWO** | SPI1_SCK（第二组） | ⚠️ **冲突，必须释放** |
| **PB4** | **NJTRST** | SPI1_MISO（第二组） | ⚠️ **冲突，必须释放** |
| PB5 | 无（默认普通 IO） | SPI1_MOSI（第二组） | 不冲突 |

##### 知识点 2　SWD 与 JTAG 的取舍

- **JTAG（5 线）**：占用 PA13/PA14/**PA15/PB3/PB4**；
- **SWD（2 线）**：只用 SWDIO(PA13)/SWCLK(PA14) 两根，**不占用 PA15/PB3/PB4**。

结论很直接：**本项目必须选 Serial Wire（SWD）**。

> ⚠️ **特别注意**：CubeMX 的 Debug 选项里还有一个 **Trace Asynchronous Sw**，它会把 PB3 单独留下来当 TRACESWO 输出。**本项目不能选它**，否则 PB3 依然被占。

#### 技能点 2　没释放时会怎样

##### 知识点 1　典型现象对照

**表 1-8 JTAG 未释放时的现象与判别**

| 现象 | 判别方法 | 结论 |
| --- | --- | --- |
| 读 JEDEC ID 恒为 `0xFF` | 用示波器看 PB3 有无时钟 | 无时钟 → PB3 被 TRACESWO 占用 |
| 读 JEDEC ID 恒为 `0x00` | 量 PB4 电平 | MISO 被 JTAG 驱动为固定电平 |
| 编译下载后程序"跑飞" | 检查是否误用了 PA13/PA14 | SWD 引脚被重配成普通 IO，调试器失联 |
| CubeMX 里 PB3 选不到 `SPI1_SCK` | 看 SYS 的 Debug 设置 | 选成了 JTAG 或 Trace Asynchronous Sw |

> **排错口诀**：**"Pinout 里点不亮，先看 SYS 里选了什么"**。

---

### 环节四　编制引脚分配表与接线检查

#### 技能点 1　最终引脚分配

##### 知识点 1　完整分配表

**表 1-9 本项目的最终引脚分配（对照用户接线表）**

| 器件 | 协议 | 信号 | STM32 引脚 | CubeMX 配置 | 说明 |
| --- | --- | --- | --- | --- | --- |
| **TF-CARD** | SPI | **CS** | **PA4** | GPIO_Output（High） | 软件片选，低有效 |
| | | **CLK** | **PA5** | **SPI1_SCK（AF5）** | 组 1 时钟 |
| | | **MISO** | **PA6** | **SPI1_MISO（AF5）** | 组 1 主入 |
| | | **MOSI** | **PA7** | **SPI1_MOSI（AF5）** | 组 1 主出 |
| **Flash** | SPI | **CS** | **PA15** | GPIO_Output（High） | 软件片选，低有效；需释放 JTDI |
| | | **CLK** | **PB3** | **SPI1_SCK（AF5）** | 组 2 时钟；需释放 JTDO |
| | | **SDO** | **PB4** | **SPI1_MISO（AF5）** | 组 2 从出；需释放 NJTRST |
| | | **SDI** | **PB5** | **SPI1_MOSI（AF5）** | 组 2 主出 |
| 调试 | SWD | SWDIO / SWCLK | PA13 / PA14 | SYS | 必须保留 |
| 串口 | USART | TX / RX | PA9 / PA10 | USART1（AF7） | printf 输出 |

> **注意 SDI/SDO 的命名**：W25Q64 手册里 `SDI`（Serial Data In）= 主机 MOSI，`SDO`（Serial Data Out）= 主机 MISO。**不少人把 SDO 当成"主机输出"而接反**——记住判据：**"站在芯片的角度看"**，SDI 是芯片收，SDO 是芯片发。

##### 知识点 2　W25Q64 接法（含 WP# 与 HOLD#）

**表 1-10 W25Q64 引脚接法**

| W25Q64 引脚 | 全称 | 接到 | 说明 |
| --- | --- | --- | --- |
| CS# | Chip Select | **PA15** | 片选，低有效 |
| CLK | Serial Clock | **PB3** | 时钟 |
| **DI（IO0）** | Data In | **PB5** | 主机→FLASH（MOSI / SDI） |
| **DO（IO1）** | Data Out | **PB4** | FLASH→主机（MISO / SDO） |
| **WP#** | Write Protect | **3.3V**（10kΩ 上拉） | 低电平写保护；**不接会随机写失败** |
| **HOLD#** | Hold | **3.3V**（10kΩ 上拉） | 低电平暂停通讯；不接可能读到乱码 |
| VCC | 电源 | 3.3V + 100nF 去耦 | 不可接 5V |
| GND | 地 | GND | 与 MCU 共地 |

> **这两根脚为什么必须拉高**：`WP#` 悬空时电平不确定，芯片可能进入写保护而**悄悄丢弃写入命令**（不报错、只表现为"读回来还是 0xFF"）；`HOLD#` 悬空时可能被误触发暂停。**新手 90% 的"写不进去"都出在这两根脚上。**

##### 知识点 3　TF 卡接法

**表 1-11 TF 卡（SPI 模式）引脚接法**

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

> **MISO 上拉在本项目里格外重要**：共享总线上有两条 MISO（PA6 与 PB4）汇入 SPI1。虽然没被选中的器件会释放 MISO，但**释放后的引脚是浮空的**，加 10kΩ 上拉能让它稳定为高，**避免浮空电平被 SPⅠ 采成噪声**。

#### 技能点 2　电气与接线检查清单

##### 知识点 1　上电前必查的五件事

1. **电平**：W25Q64 与 TF 卡都是 **3.3V 器件**，不要接开发板的 5V 排针；
2. **共地**：TF 卡座、FLASH、MCU 必须共地；
3. **上拉**：`WP#`、`HOLD#` 拉 3.3V；TF 卡的 CS/MOSI/**MISO** 各 10kΩ 上拉；
4. **去耦**：两颗器件电源脚就近各放 100nF，TF 卡再并 10µF，抑制插拔浪涌；
5. **不要动调试口**：PA13/PA14 保持给 SWD。

##### 知识点 2　共享总线的走线要求

1. **SCK 走线要短**：PA5 与 PB3 是同一条 SCK 的两个出口，**两根线加起来的总长度都要控制**，避免一边长一边短导致两个器件的时序偏差过大；
2. **MISO 别长距离并行**：PA6 与 PB4 两条 MISO 若并排走 10cm 以上，未选中那边的浮空信号容易被耦合进被选中那边的数据里，**加地线隔离**；
3. **片选线各自就近**：PA4 靠近 TF 卡座、PA15 靠近 FLASH，避免被 SCK 串扰；
4. **绝不允许同时拉低两根 CS**——这会让两颗器件同时驱动各自的 MISO，电气上"打架"。

> 📷 图 1-1 本项目的实际接线照片（此处可插入实物图）

---

## 任务二　SPI 协议认知（物理层与协议层）

> **本任务的目标**：把 SPI 从"四根线"讲到"四种模式"，并且**把"多从机怎么共存"这件事讲透**——这正是本项目的理论基础。

### 环节一　物理层：四根线如何搭起一条总线

#### 技能点 1　认识四根信号线

##### 知识点 1　SCK / MOSI / MISO 的角色

SPI（Serial Peripheral Interface，串行外围设备接口）由 Motorola 提出，是一条**高速、全双工、同步**的串行总线。

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

1. **一个从机需要一根独立的 NSS 线**：挂 4 个从机，主机要多花 4 根 IO（**SCK/MOSI/MISO 三根可以并联共用**）；
2. **NSS 的边沿就是通讯的起止信号**：`NSS 由高变低 = 起始`，`NSS 由低变高 = 停止`。

> **本项目就是标准的"一主两从"**：SPI1 作主机，PA4/PB3/PB4/PB5 挂 W25Q64，PA5/PA6/PA7 挂 TF 卡，两条 CS（PA15、PA4）决定当前跟谁说话。

#### 技能点 2　多从机拓扑：为什么能共用三根线

##### 知识点 1　三种信号的电气性质

**表 2-2 共享总线上三种信号的电气性质**

| 信号 | 方向 | 未被选中时从机怎么处理 | 能否共用 |
| --- | --- | --- | --- |
| **SCK** | 主机→所有从机 | 忽略时钟（内部不采样） | ✅ 可并联 |
| **MOSI** | 主机→所有从机 | 忽略数据 | ✅ 可并联 |
| **MISO** | 从机→主机 | **置为高阻态（释放总线）** | ✅ 可并联 |
| **CS** | 主机→每个从机（独立） | 保持高电平 | ❌ 必须独立 |

> **关键就在 MISO 那一行**：SPI 从机被"取消选中"时，其 MISO 输出级进入**高阻态**（相当于把线从内部断开）。因此只要**同一时刻只选中一个从机**，MISO 上就只有一个人在说话。**这就是 SPI 能"三线并联 + 多片选"的全部原理。**

##### 知识点 2　本项目的拓扑图

```
                    ┌──────────────────────────────┐
                    │      STM32F407VET6  SPI1     │
                    │  （模式 0，21MHz，AF5）       │
                    └───┬────┬────┬────┬────┬──────┘
                        │    │    │    │    │
                 CS ────┘    │    │    │    └──── CS
              (PA4)          │    │    │        (PA15)
                        SCK  │  MISO  │  MOSI
                        (PA5)│ (PA6)  │ (PA7)
                             │         │
        ┌────────────────────┴─────────┴────────────┐
        │   ★ 注意：SCK/MISO/MOSI 还有第二组出口    │
        │      PB3 / PB4 / PB5（同属 SPI1，AF5）    │
        └────────────────────┬─────────┬────────────┘
                             │         │
                        SCK (PB3)  MISO(PB4)  MOSI(PB5)
                             │         │         │
   ┌───────────────┐    ┌────┴─────────┴─────────┴────┐
   │   TF-CARD     │    │        W25Q64 FLASH         │
   │ CS=PA4        │    │  CS=PA15  CLK=PB3           │
   │ CLK=PA5       │    │  DO(SDO)=PB4  DI(SDI)=PB5   │
   │ MISO=PA6      │    └─────────────────────────────┘
   │ MOSI=PA7      │
   └───────────────┘
```

> **看图要点**：SPI1 的每个信号都有**两组物理出口**（PA 组和 PB 组），**两组同时有效**。这意味着"跟 Flash 说话"时，TF 卡那边其实也收到了时钟和数据——但它 CS 高，所以**完全不理**。**片选才是真正的"总开关"。**

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

```
NSS  ‾‾‾‾\_______________________________________________/‾‾‾‾‾
          ▲ 起始（选中）                        ▲ 停止（取消选中）
SCK  ________/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\________________
MOSI ______X D7 X D6 X D5 X D4 X D3 X D2 X D1 X D0 X________
MISO ______X D7 X D6 X D5 X D4 X D3 X D2 X D1 X D0 X________
```

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

> **Dummy 字节为什么常用 `0xFF`**：从机在 MISO 上输出数据时，MOSI 上的值通常被它忽略；用 `0xFF`（全 1）可以在总线空闲时保持 MOSI 高电平，副作用最小。

#### 技能点 2　理解 CPOL 与 CPHA：四种模式的由来

##### 知识点 1　时钟极性与时钟相位

- **CPOL（Clock Polarity，时钟极性）**：**空闲时** SCK 是高还是低。`CPOL=0` 空闲为低，`CPOL=1` 空闲为高；
- **CPHA（Clock Phase，时钟相位）**：数据在**第几个边沿**被采样。`CPHA=0` 在**奇数边沿**采样，`CPHA=1` 在**偶数边沿**采样。

> **注意"奇数边沿"不等于"上升沿"**：当 CPOL=0 时奇数边沿是上升沿，当 CPOL=1 时奇数边沿是下降沿。**所以采样沿不是由上升/下降决定的，而是由"第几个边沿"决定的**——这是野火第 24 章特别强调、也是初学者最容易记混的一句。

**表 2-3 SPI 的四种模式**

| 模式 | CPOL | CPHA | 空闲时 SCK | 采样时刻 | 数据切换时刻 | 本项目 |
| --- | --- | --- | --- | --- | --- | --- |
| **模式 0** | 0 | 0 | 低电平 | 奇数边沿（上升沿） | 偶数边沿（下降沿） | ✅ **两器件都用** |
| 模式 1 | 0 | 1 | 低电平 | 偶数边沿（下降沿） | 奇数边沿（上升沿） | — |
| 模式 2 | 1 | 0 | 高电平 | 奇数边沿（下降沿） | 偶数边沿（上升沿） | — |
| 模式 3 | 1 | 1 | 高电平 | 偶数边沿（上升沿） | 奇数边沿（下降沿） | ❌ 不能用（TF 卡不支持） |

**模式 0 的时序（本项目唯一使用的模式）**：

```
NSS   ‾‾‾\_________________________________________/‾‾‾
SCK   ______/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\________
            ↑ ↑ ↑ ↑                        （CPOL=0，空闲低）
MOSI  ──X═D7═X═D6═X═ … ═X═D0═X──────────
          ↑ 在上升沿采样（CPHA=0，奇数边沿）
MISO  ──X═D7═X═D6═X═ … ═X═D0═X──────────
          ↑ 同样在上升沿采样
```

##### 知识点 2　为什么本项目必须统一用模式 0

这是共享总线带来的**硬约束**：

**表 2-4 模式选择的推导**

| 器件 | 支持的模式 | 说明 |
| --- | --- | --- |
| W25Q64 | **模式 0** 和 **模式 3** | 数据手册明确支持两种 |
| TF 卡 | **只有模式 0** | SD 规范规定 SPI 模式固定 CPOL=0、CPHA=0 |
| **共享总线** | **只能有一个 CPOL/CPHA** | 因为两组引脚同时挂在同一个 SPI1 上 |
| **结论** | **全总线用模式 0** | 取交集，两器件都满足 |

> ⚠️ **这是本项目最容易踩的坑**：野火第 24 章的 FLASH 驱动用的是**模式 3**（`SPI_POLARITY_HIGH` + `SPI_PHASE_2EDGE`）。**如果你照抄野火的初始化结构体，TF 卡就完全无法工作**（CMD0 发出去没响应）。
> **解决办法**：把 `CLKPolarity` 改成 `SPI_POLARITY_LOW`、`CLKPhase` 改成 `SPI_PHASE_1EDGE`。**W25Q64 对两种模式都支持，改完照常工作。**

##### 知识点 3　模式不匹配时的症状

**表 2-5 模式不匹配时的典型症状**

| 主机 | 从机 | 现象 |
| --- | --- | --- |
| 模式 3 | 模式 0 | 数据位整体错开半个时钟，读 ID 得到"像但不完全像"的值 |
| 模式 0 | 模式 3 | 首字节丢失或末字节丢一位 |
| 任一 | 任一 | 偶尔能通、偶尔不通（时序处于临界） |

> **排错方法**：先用**模式 0**（本项目要求），不通再换**模式 3**。**但注意：换成模式 3 之后 TF 卡一定不工作**，所以模式 3 只能用来单独验证 FLASH。

---

### 环节三　横向对比与速率账

#### 技能点 1　三条总线的选型逻辑

##### 知识点 1　SPI / I2C / UART 对照表

**表 2-6 常用三种板级总线的对比**

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

```
字节速率 = SCK 频率 ÷ 8
```

本项目**只有一个 SPI1**，全部时钟来自 **APB2 = 84MHz**：

**表 2-7 本项目各阶段的 SPI 速率**

| 使用场景 | 分频 | SCK | 字节速率 | 说明 |
| --- | --- | --- | --- | --- |
| W25Q64 工作 | ÷4 | **21 MHz** | ≈ 2.6 MB/s | 对 0x03 读指令余量充足 |
| TF 卡初始化 | ÷256 | **328 kHz** | ≈ 41 KB/s | **SD 规范要求 ≤400kHz** |
| TF 卡工作 | ÷4 | **21 MHz** | ≈ 2.6 MB/s | SD SPI 模式上限 25MHz |
| （可选）提速 | ÷2 | 42 MHz | ≈ 5.2 MB/s | 需换 Fast Read(0x0B) |

> **TF 卡为什么初始化阶段必须降到 328kHz**：SD 规范规定，**卡在上电初始化期间（识别、协商阶段）SCK 不得超过 400kHz**。÷256 得 328kHz，刚好卡在红线以下。
> **注意**：共享总线下，**切换速率不需要动引脚、不需要关外设重配 CPOL/CPHA**，只需要改 `hspi1.Init.BaudRatePrescaler` 并重新 `HAL_SPI_Init()`。**这比"分时复用"方案简单得多。**

##### 知识点 2　把时间算到擦除与编程上：FLASH 慢在哪

新手常以为"SPI 21MHz 很快，写 8MB 也就 3 秒"。**错的**。FLASH 的瓶颈从来不在总线，而在**芯片内部的擦除与编程**：

**表 2-8 写满 8MB 的时间账**

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

> **理解框图上"信号只有一条线"的意义**：SCK/MISO/MOSI 在芯片内部各只有一路。它们通过 GPIO 的复用选择器**同时送到多个引脚**，所以 PA5 和 PB3 能同时输出同一个 SCK——这就是本项目两组引脚可以同时工作的硬件基础。

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
| 000 | ÷2 | `SPI_BAUDRATEPRESCALER_2` | 42 MHz | （可选）提速 |
| 001 | ÷4 | `SPI_BAUDRATEPRESCALER_4` | **21 MHz** | **FLASH / TF 卡工作** |
| 010 | ÷8 | `SPI_BAUDRATEPRESCALER_8` | 10.5 MHz | 调试降速 |
| 011 | ÷16 | `SPI_BAUDRATEPRESCALER_16` | 5.25 MHz | 调试降速 |
| 100 | ÷32 | `SPI_BAUDRATEPRESCALER_32` | 2.625 MHz | — |
| 101 | ÷64 | `SPI_BAUDRATEPRESCALER_64` | 1.3125 MHz | — |
| 110 | ÷128 | `SPI_BAUDRATEPRESCALER_128` | 656 kHz | — |
| 111 | ÷256 | `SPI_BAUDRATEPRESCALER_256` | **328 kHz** | **TF 卡初始化** |

> **本项目只有一个 SPI1，所以分频值只有这一列**——不用再记两个基准时钟。

##### 知识点 2　选分频的三条实践规则

1. **先查从机的上限**：W25Q64 标准读（03h）最高约 50MHz，TF 卡 SPI 模式最高 25MHz。本项目统一取 21MHz，两者都满足；
2. **初始化降速，通信提速**：TF 卡识别阶段必须 ≤400kHz，识别完再切 21MHz；
3. **留余量**：**调试期先降到 1~5MHz 跑通，再逐步提高**。

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

| CubeMX 配置项 | 结构体成员 | 本项目取值 | 说明 |
| --- | --- | --- | --- |
| Mode | `Mode` | Master | 两块存储都是从机 |
| Direction | `Direction` | 2 Lines Full Duplex | 全双工 |
| Data Size | `DataSize` | 8 Bits | 两者都是 8 位帧 |
| **Clock Polarity (CPOL)** | `CLKPolarity` | **Low** | **模式 0，两器件共用** |
| **Clock Phase (CPHA)** | `CLKPhase` | **1 Edge** | **模式 0，两器件共用** |
| NSS Signal Type | `NSS` | **Software** | 都用 GPIO 片选 |
| Prescaler | `BaudRatePrescaler` | **256（初值）→ 运行期改 4** | TF 卡初始化必须降速 |
| First Bit | `FirstBit` | MSB First | 两者都是高位先行 |
| CRC Calculation | `CRCCalculation` | Disabled | 不用 SPI 硬件 CRC |

> **注意：CPOL/CPHA 全程只有一个值（模式 0）**，不再需要"按器件切换模式"。

##### 知识点 2　两个容易被忽略的坑

> **坑一：`DataSize` 设成 16 位后，MISO 会"多发一个字节"**。因为 16 位帧需要 16 个时钟。**W25Q64 与 TF 卡都必须用 8 位帧**。
>
> **坑二：`SPI_CRCCALCULATION_DISABLE` 时 `CRCPolynomial` 的赋值无效**。本项目 CRC 关掉，这行可删可留。

#### 技能点 2　看懂 HAL 的收发 API

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

> **为什么单字节收发必须是 `TransmitReceive`**：SPI 是全双工，**只有产生时钟才能收到数据**。`HAL_SPI_Transmit()` 虽然也产生时钟，但**它不会把接收内容返回给你**。

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

> **第 ④ 步是最容易漏的一步**：接收缓冲只有一个位置，不读走，下一个字节到来时就溢出。**HAL 的 `HAL_SPI_Transmit()` 内部已经帮你读了**，但自己写寄存器版本时千万别忘。

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
| 读到全 `0x00` | MISO 被短接到地，或 CS 一直有效导致数据错位 | 量 MISO 静态电平；查 CS |
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

> ⚠️ **共享总线下的额外纪律**：**绝不允许同时拉低两根 CS**。PA4 与 PA15 必须互斥——这会让两颗器件同时驱动各自的 MISO，电气上"打架"。

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

### 环节二　配置调试口与两路片选

#### 技能点 1　释放 JTAG 引脚（承接任务一环节三）

##### 知识点 1　SYS 配置的连锁反应

1. **System Core → SYS**；
2. **Debug** 选 **Serial Wire**；
3. 观察芯片图：PA13/PA14 变为绿色（已分配 SYS_JTMS-SWDIO / SYS_JTCK-SWCLK），而 **PA15/PB3/PB4 恢复为可分配状态**；
4. **Timebase Source** 保持 **SysTick**（HAL_Delay 依赖它）。

> **操作顺序很重要**：**一定要先配 SYS，再去配 SPI1**。反过来的话，CubeMX 会因为 JTAG 占用而拒绝 PB3/PB4。

##### 知识点 2　配置完的自检

**表 4-1 SYS 配置后的引脚状态**

| 引脚 | 配置前 | 配置 Serial Wire 后 | 是否可自由分配 |
| --- | --- | --- | --- |
| PA13 | SYS_JTMS-SWDIO | SYS_JTMS-SWDIO | 不可（保留） |
| PA14 | SYS_JTCK-SWCLK | SYS_JTCK-SWCLK | 不可（保留） |
| PA15 | JTDI（灰） | **空闲（浅色）** | ✅ 可 |
| PB3 | JTDO（灰） | **空闲（浅色）** | ✅ 可 |
| PB4 | NJTRST（灰） | **空闲（浅色）** | ✅ 可 |

#### 技能点 2　把两路片选配成 GPIO 输出高

##### 知识点 1　PA4 / PA15 的 GPIO 参数

**注意：整个项目只有这两个引脚是普通 GPIO，其余 6 根全是 AF5。**

1. 芯片图上**左键点击 PA4** → 选 **GPIO_Output**；
2. **左键点击 PA15** → 选 **GPIO_Output**；
3. 切到 **System Core → GPIO** 页设置：

**表 4-2 两路片选的 GPIO 参数**

| 参数 | TF 卡片选（PA4） | Flash 片选（PA15） | 说明 |
| --- | --- | --- | --- |
| GPIO output level | **High** | **High** | 初始不选中（CS 高 = 从机空闲） |
| GPIO mode | Output Push Pull | Output Push Pull | 推挽，不需要上拉 |
| GPIO Pull-up/Pull-down | No pull-up and no pull-down | No pull-up and no pull-down | 板上有外部上拉的话这里不用管 |
| Maximum output speed | **Very High** | **Very High** | 高速时 CS 边沿要陡 |
| User Label | **TF_CS** | **W25Q64_CS** | 起别名，代码里好读 |

> **`User Label` 的作用**：填了别名后，CubeMX 会在 `main.h` 里生成 `#define W25Q64_CS_Pin GPIO_PIN_15` 和 `#define W25Q64_CS_GPIO_Port GPIOA`，代码里可以直接用，**引脚改名时不用全局搜索替换**。

##### 知识点 2　初始电平为什么必须是高

CS 的低电平是"选中"。**上电瞬间如果 CS 是低，从机就会以为自己被选中，等待命令**——而 CPU 还在跑启动代码，没有时钟过来，从机就一直挂着。

```c
/* CubeMX 生成的 gpio.c 里，会先写电平再初始化模式 */
HAL_GPIO_WritePin(TF_CS_GPIO_Port, TF_CS_Pin, GPIO_PIN_SET);        /* 先给高 */
HAL_GPIO_Init(TF_CS_GPIO_Port, &GPIO_InitStruct);                    /* 再配模式 */
```

> **顺序不能反**：先配成输出再写高，中间那一瞬间引脚是低电平（复位默认值），从机可能误触发。**CubeMX 已按正确顺序生成**。

---

### 环节三　配置 SPI1（一次性配好两组引脚）

#### 技能点 1　让 CubeMX 同时点亮 8 根信号线

##### 知识点 1　关键操作：先选第一组，再手工补第二组

CubeMX 的默认行为是"一个外设只自动分配一组引脚"，但**它允许你手工把同一外设的第二组引脚也点上去**——因为 `PA5` 和 `PB3` 在芯片定义里**都是合法的 `SPI1_SCK`**。

**操作步骤（这是本项目最关键的一步，务必按顺序做）**：

1. 左侧 **Connectivity → SPI1**；
2. **Mode** 下拉选 **Full-Duplex Master**；
3. CubeMX 自动把 **PA5 → SPI1_SCK、PA6 → SPI1_MISO、PA7 → SPI1_MOSI** 点亮；
4. **Hardware NSS Signal** 选 **Disable**（两路都用软件片选）；
5. **手工把第二组补上**：在芯片图上依次左键点击 **PB3**，在弹出菜单里选 **`SPI1_SCK`**；再点 **PB4** 选 **`SPI1_MISO`**；再点 **PB5** 选 **`SPI1_MOSI`**；
6. 此时芯片图上 **PA5/PB3 都会标成 SPI1_SCK，PA6/PB4 标成 SPI1_MISO，PA7/PB5 标成 SPI1_MOSI** —— **完全正常，这就是我们要的效果**。

> 📷 图 4-3 SPI1 同时点亮两组引脚（PA5/PB3 均为 SPI1_SCK）（此处可插入截图）

> ⚠️ **如果 PB3/PB4 点不出 SPI1 选项**：回去检查 **SYS 的 Debug 是不是 Serial Wire**——被 JTAG 占用时，CubeMX 不会给你 SPI1 的选项。

##### 知识点 2　Parameter Settings 逐项填写

**表 4-3 SPI1 的 Parameter Settings（两器件共用）**

| 配置项 | 取值 | 依据 |
| --- | --- | --- |
| Frame Format | Motorola | 标准 SPI 格式 |
| Data Size | **8 Bits** | 两个器件都是字节流 |
| First Bit | **MSB First** | 两者都要求高位先行 |
| Prescaler | **256**（→ 328kHz） | 上电初值给 TF 卡初始化用 |
| **Clock Polarity (CPOL)** | **Low** | **模式 0（TF 卡强制要求）** |
| **Clock Phase (CPHA)** | **1 Edge** | **模式 0** |
| CRC Calculation | Disabled | 不用硬件 CRC |
| NSS Signal Type | **Software** | 两路都软件片选 |

> **为什么 CPOL/CPHA 只能选模式 0**：TF 卡在 SPI 模式下**只支持模式 0**，而总线是共享的，所以整个 SPI1 只能有一个模式。**W25Q64 同时支持模式 0 和 3，用模式 0 完全没问题。**
> **为什么初值分频选 256**：因为 `TF_Init()` 是上电后第一个要降到 ≤400kHz 的操作。用 328kHz 起步最安全，识别完成后再由总线层提速到 21MHz。

##### 知识点 3　NVIC 与 DMA

本项目用**阻塞式**收发，**NVIC 全部不勾**。若后续要提速（例如整片读 8MB），再到 **DMA Settings** 添加 SPI1_TX/SPI1_RX，本笔记不展开。

#### 技能点 2　配置串口、生成工程与代码结构

##### 知识点 1　配置 USART1 作为调试输出

1. **Connectivity → USART1** → Mode 选 **Asynchronous**；
2. **Parameter Settings**：Baud Rate = **115200**，Word Length = **8 Bits**，Parity = **None**，Stop Bits = **1**；
3. 引脚自动落到 **PA9（TX）/ PA10（RX）**，复用 **AF7**；
4. **NVIC 可以不勾**（只用 printf 单向输出）。

> 📷 图 4-4 USART1 配置 115200-8-N-1（此处可插入截图）

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

##### 知识点 4　核对生成的 MspInit：8 根线必须全是 AF5

```c
void HAL_SPI_MspInit(SPI_HandleTypeDef* hspi)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if (hspi->Instance == SPI1)
  {
    __HAL_RCC_SPI1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();          /* ★ 第二组在 PB 口，必须开 GPIOB 时钟 */

    /* 第一组：PA5 = SPI1_SCK, PA6 = SPI1_MISO, PA7 = SPI1_MOSI */
    GPIO_InitStruct.Pin       = GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7;
    GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;         /* 复用推挽 */
    GPIO_InitStruct.Pull      = GPIO_NOPULL;
    GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF5_SPI1;           /* ★ SPI1 是 AF5 */
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    /* 第二组：PB3 = SPI1_SCK, PB4 = SPI1_MISO, PB5 = SPI1_MOSI */
    GPIO_InitStruct.Pin       = GPIO_PIN_3 | GPIO_PIN_4 | GPIO_PIN_5;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);              /* 复用编号沿用上面的 AF5 */
  }
}
```

> ⚠️ **两个必须核对的地方**：
> ① **`__HAL_RCC_GPIOB_CLK_ENABLE()` 必须存在**——第二组在 PB 口，忘了开时钟则整个 Flash 组无信号，现象是"TF 卡正常、Flash 读到全 0xFF"；
> ② **`GPIO_AF5_SPI1`**（SPI3 才是 AF6）。写错成 AF6 的典型现象是"烧录后一个器件都不响应"。

##### 知识点 5　新建用户驱动文件

在工程里新建这些模块（**不要写进 CubeMX 管理的 `spi.c`**）：

```
SPI_Storage/
├── Core/
│   ├── Inc/
│   │   ├── main.h                 ← CubeMX 生成（含引脚宏）
│   │   ├── spi.h                  ← CubeMX 生成
│   │   ├── bsp_common.h           ← ★ 自写：日志宏、错误码
│   │   ├── bsp_spi1_bus.h         ← ★ 自写：SPI1 公共总线层
│   │   ├── bsp_w25q64.h           ← ★ 自写：W25Q64 驱动
│   │   └── bsp_tfcard.h           ← ★ 自写：TF 卡驱动
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

## 任务五　SPI1 公共总线层

> **本任务的目标**：写一个**只做两件事**的薄层——**选中器件** + **设定速率**。因为没有引脚切换、没有模式切换，这一层比"分时复用"简单得多（约 40 行核心代码），但仍然是全项目的地基。

### 环节一　设计总线层的接口

#### 技能点 1　这一层到底要做什么

##### 知识点 1　三个职责，一个函数

**表 5-1 公共总线层的职责**

| 职责 | 具体动作 | 是否必须 |
| --- | --- | --- |
| **① 互斥片选** | 选中一个器件前，先把另一个的 CS 拉高 | ✅ 必须 |
| **② 速率切换** | TF 卡初始化 328kHz、运行 21MHz | ✅ 必须 |
| ③ 引脚/模式切换 | —— | ❌ **不需要**（引脚固定 AF5、模式固定 0） |
| ④ 字节收发 | 提供统一的单字节/多字节读写 | ✅ 方便 |

> **和"分时复用"方案比，这里少了最关键的一块**：不用 `__HAL_SPI_DISABLE()` 关外设、不用改 CPOL/CPHA、不用重配 GPIO 的 MODER/AFR。**只改一个分频值。**

##### 知识点 2　API 设计

**表 5-2 bsp_spi1_bus 对外接口**

| API | 作用 | 谁调用 |
| --- | --- | --- |
| `BUS_Init()` | 上电初始化（两路 CS 拉高、SPI1 切 328kHz） | `main()` |
| `BUS_Select(BUS_DEV, prescaler)` | 选中一个器件并按需改变速率 | 两个驱动入口 |
| `BUS_DeselectAll()` | 两路 CS 都拉高 | 切换时内部用 |
| `BUS_ReadWriteByte(b)` | 单字节收发 | 两个驱动 |
| `BUS_WriteBytes(p, n)` | 连续发送 | 两个驱动 |
| `BUS_ReadBytes(p, n)` | 连续接收 | 两个驱动 |
| `BUS_GetCurrent()` | 查询当前选中谁（调试用） | 测试代码 |

> **设计要点**：`BUS_Select()` 内部**先拉高两路 CS，再拉低目标那一根**。这个"先全断、后单选"的顺序保证了**任何时候都不会出现两颗器件同时被选中**。

#### 技能点 2　头文件设计

##### 知识点 1　bsp_spi1_bus.h 完整代码

```c
/* bsp_spi1_bus.h —— SPI1 公共总线层（共享总线 + 独立片选）
 *
 * 总线拓扑（全部为 SPI1 / AF5）：
 *   TF-CARD : CS=PA4  CLK=PA5  MISO=PA6  MOSI=PA7
 *   Flash   : CS=PA15 CLK=PB3  MISO=PB4  MOSI=PB5
 *
 * 两组信号线一次性配成 AF5，运行期永不改动；
 * 本层只负责"拉低哪一根 CS"和"跑多快"。
 */
#ifndef __BSP_SPI1_BUS_H
#define __BSP_SPI1_BUS_H

#include "main.h"
#include "spi.h"          /* 提供 hspi1 */

/* ---------- 器件编号 ---------- */
typedef enum {
  BUS_DEV_NONE  = 0,
  BUS_DEV_TF    = 1,      /* TF 卡：CS = PA4 */
  BUS_DEV_FLASH = 2       /* W25Q64：CS = PA15 */
} BUS_DEV;

/* ---------- 分频快捷宏（SPI1 挂 APB2 = 84MHz） ----------
 *   ÷2   → 42    MHz
 *   ÷4   → 21    MHz   （FLASH / TF 卡工作速率）
 *   ÷8   → 10.5  MHz
 *   ÷16  → 5.25  MHz
 *   ÷32  → 2.625 MHz
 *   ÷64  → 1.3125 MHz
 *   ÷128 → 656   kHz
 *   ÷256 → 328   kHz   （TF 卡初始化必须 ≤400kHz）
 */
#define BUS_SPEED_42M    SPI_BAUDRATEPRESCALER_2
#define BUS_SPEED_21M    SPI_BAUDRATEPRESCALER_4
#define BUS_SPEED_10M5   SPI_BAUDRATEPRESCALER_8
#define BUS_SPEED_5M25   SPI_BAUDRATEPRESCALER_16
#define BUS_SPEED_2M6    SPI_BAUDRATEPRESCALER_32
#define BUS_SPEED_1M3    SPI_BAUDRATEPRESCALER_64
#define BUS_SPEED_656K   SPI_BAUDRATEPRESCALER_128
#define BUS_SPEED_328K   SPI_BAUDRATEPRESCALER_256

/* ---------- 两路片选 ---------- */
#define BUS_CS_TF_PIN       GPIO_PIN_4
#define BUS_CS_TF_PORT      GPIOA
#define BUS_CS_FLASH_PIN    GPIO_PIN_15
#define BUS_CS_FLASH_PORT   GPIOA

/* ---------- 对外接口 ---------- */
void     BUS_Init(void);
void     BUS_Select(BUS_DEV dev, uint32_t prescaler);
void     BUS_DeselectAll(void);
BUS_DEV  BUS_GetCurrent(void);

uint8_t  BUS_ReadWriteByte(uint8_t txData);
void     BUS_WriteBytes(uint8_t *pData, uint16_t len);
void     BUS_ReadBytes(uint8_t *pData, uint16_t len);

#endif /* __BSP_SPI1_BUS_H */
```

> **8 根信号线在这份头文件里一次都没出现**——这是正确的：它们由 CubeMX 的 `spi.c` 一次性配成 AF5，**运行期谁都不该再碰它们**。本层只管两根 CS 和分频。

---

### 环节二　实现总线层的完整代码

#### 技能点 1　核心实现

##### 知识点 1　bsp_spi1_bus.c 完整代码

```c
/* bsp_spi1_bus.c —— SPI1 公共总线层实现 */
#include "bsp_spi1_bus.h"

static BUS_DEV  s_currentDev     = BUS_DEV_NONE;
static uint32_t s_currentPrescaler = 0;

/* ---------- 两路片选都拉高（谁都不选中） ---------- */
void BUS_DeselectAll(void)
{
  HAL_GPIO_WritePin(BUS_CS_TF_PORT,    BUS_CS_TF_PIN,    GPIO_PIN_SET);
  HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_SET);
}

/* ---------- 上电初始化 ---------- */
void BUS_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  /* 两路 CS 配成推挽输出（CubeMX 已配，这里再确认一次，防止被别处改掉） */
  __HAL_RCC_GPIOA_CLK_ENABLE();

  HAL_GPIO_WritePin(BUS_CS_TF_PORT,    BUS_CS_TF_PIN,    GPIO_PIN_SET);
  HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_SET);

  GPIO_InitStruct.Pin   = BUS_CS_TF_PIN | BUS_CS_FLASH_PIN;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull  = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* 以慢速启动（TF 卡初始化要求 ≤400kHz） */
  s_currentDev = BUS_DEV_NONE;
  BUS_Select(BUS_DEV_TF, BUS_SPEED_328K);
}

/* ---------- 核心：选中器件 + 设定速率 ----------
 * 顺序：① 两路 CS 全拉高（先都断） → ② 拉低目标 CS（后单选）
 *       → ③ 若速率变了，重设分频
 */
void BUS_Select(BUS_DEV dev, uint32_t prescaler)
{
  /* ① 先把两路片选都拉高，保证任何时候只有一颗被选中 */
  BUS_DeselectAll();

  if (dev == BUS_DEV_NONE)
  {
    s_currentDev = BUS_DEV_NONE;
    return;
  }

  /* ② 速率变化时才动 SPI 外设（改 CR1 前必须先 DISABLE） */
  if (prescaler != s_currentPrescaler)
  {
    __HAL_SPI_DISABLE(&hspi1);
    hspi1.Init.BaudRatePrescaler = prescaler;
    HAL_SPI_Init(&hspi1);          /* 内部会按 Init 内容重写 CR1 并重新使能 */
    __HAL_SPI_ENABLE(&hspi1);
    s_currentPrescaler = prescaler;
  }

  /* ③ 拉低目标片选，真正"选中" */
  if (dev == BUS_DEV_TF)
  {
    HAL_GPIO_WritePin(BUS_CS_TF_PORT, BUS_CS_TF_PIN, GPIO_PIN_RESET);
  }
  else if (dev == BUS_DEV_FLASH)
  {
    HAL_GPIO_WritePin(BUS_CS_FLASH_PORT, BUS_CS_FLASH_PIN, GPIO_PIN_RESET);
  }

  s_currentDev = dev;
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

**① 为什么 `BUS_Select` 一进来就 `BUS_DeselectAll()`**

这是**共享总线安全的唯一保障**：

```c
/* 危险写法：直接拉低目标 CS，不管另一根 */
HAL_GPIO_WritePin(TF_CS_PORT, TF_CS_PIN, GPIO_PIN_RESET);   /* 假设此时 Flash 的 CS 还是低 */
/* 结果：两颗器件同时被选中，各自驱动自己的 MISO，电气"打架" */
```

**正确写法**就是代码里那样：**先两根都拉高（全断），再拉低目标（单选）**。多花 1µs，换来绝对安全。

**② 为什么改分频前要 `__HAL_SPI_DISABLE()`**

SPI 的 `CR1` 在 `SPE = 1`（外设使能）时，**BR[2:0] 与 CPOL/CPHA 是只读的**。代码不会报错，但寄存器根本没变——**这是"改了分频没生效"的头号原因**。

**③ 为什么要缓存 `s_currentPrescaler`**

因为 `HAL_SPI_Init()` 会重写整个 CR1 并重新使能外设，**有一定开销**。加上"速率没变就不动"的判断，连续读写同一器件时就不会反复重配。

**④ 引脚去哪了**

**根本没出现**。因为 `PA5/PA6/PA7/PB3/PB4/PB5` 在 CubeMX 生成的 `HAL_SPI_MspInit()` 里**一次性配成了 AF5 复用推挽**，之后**永远不会被改动**。这就是共享总线方案的简洁之处。

#### 技能点 2　验证总线层

##### 知识点 1　最小验证程序

在写完整驱动之前，**先单独验证"选中谁就只有谁响应"**：

```c
/* 测试：交替选中两颗器件，看各自是否独立响应 */
void BUS_SelfTest(void)
{
  printf("\r\n===== SPI1 公共总线自检 =====\r\n");

  /* ---------- 选中 Flash，读 JEDEC ID ---------- */
  BUS_Select(BUS_DEV_FLASH, BUS_SPEED_21M);
  BUS_ReadWriteByte(0x9F);
  uint8_t f0 = BUS_ReadWriteByte(0xFF);
  uint8_t f1 = BUS_ReadWriteByte(0xFF);
  uint8_t f2 = BUS_ReadWriteByte(0xFF);
  BUS_DeselectAll();
  printf("[总线] Flash 读到 ID = %02X %02X %02X（期望 EF 40 17）\r\n", f0, f1, f2);

  /* ---------- 选中 TF 卡，发 CMD0 ---------- */
  BUS_Select(BUS_DEV_TF, BUS_SPEED_328K);
  for (int i = 0; i < 10; i++) BUS_ReadWriteByte(0xFF);   /* 80 个暖机时钟 */
  BUS_ReadWriteByte(0x40); BUS_ReadWriteByte(0x00);
  BUS_ReadWriteByte(0x00); BUS_ReadWriteByte(0x00);
  BUS_ReadWriteByte(0x00); BUS_ReadWriteByte(0x95);
  uint8_t r1 = 0xFF;
  for (int i = 0; i < 8 && r1 == 0xFF; i++) r1 = BUS_ReadWriteByte(0xFF);
  BUS_DeselectAll();
  printf("[总线] TF 卡读到 R1 = %02X（期望 01）\r\n", r1);

  printf("[总线] 自检完成，当前器件 = %d\r\n", BUS_GetCurrent());
}
```

> **注意这里没有"先拉低 CS"的代码**：`BUS_Select()` 已经帮你拉低了，`BUS_DeselectAll()` 负责拉高。**驱动的写法就是"选 → 干活 → 取消"三段式。**

##### 知识点 2　自检结果判读

**表 5-3 总线层自检结果判读**

| Flash 读到 | TF 读到 | 结论 |
| --- | --- | --- |
| `EF 40 17` | `01` | ✅ **完美，总线层正确** |
| `EF 40 17` | `FF` | 总线对，**TF 卡硬件有问题**（卡座/供电/上拉） |
| `FF FF FF` | `01` | 总线对，**Flash 侧有问题**：先查 ① `__HAL_RCC_GPIOB_CLK_ENABLE()` ② PB3/PB4 是否释放 JTAG ③ WP#/HOLD# 是否上拉 |
| `FF FF FF` | `FF` | **总线层本身有问题**：先查 `HAL_SPI_MspInit` 的 AF5、再查 `BUS_Select` 有没有被调用 |
| 两个位置读到**同样的值** | | **片选没起作用**：两颗器件的 CS 同时有效，或 CS 引脚没配成输出 |

> **这张表的价值**：它把"总线层错"和"器件坏"两类完全不同的问题**彻底分开了**。没有这一步，你会把"PB3 是 JTAG 引脚"误判成"FLASH 芯片坏了"，白白换芯片。

##### 知识点 3　用示波器确认隔离

共享总线**不需要**"只有一组引脚有波形"（那是分时复用的要求）。本项目要看的是**片选是否互斥**：

- 选中 Flash 时：**PA15 低、PA4 高**；SCK 在 **PA5 和 PB3 上都有**（正常，因为是广播）；
- 选中 TF 卡时：**PA4 低、PA15 高**；
- **绝不允许 PA4 和 PA15 同时为低**——这是唯一的红线。

> **一句话记住共享总线与分时复用的区别**：**分时复用是"只让一根 SCK 出来"，共享总线是"两根 SCK 都出来，但只让一颗芯片听"。**

---

### 环节三　总线层的常见坑

#### 技能点 1　四个易错点

##### 知识点 1　错误清单

**表 5-4 公共总线层的四个典型错误**

| # | 错误写法 | 后果 | 正确做法 |
| --- | --- | --- | --- |
| 1 | 直接拉低目标 CS，不先拉高另一根 | 两颗器件同时选中，MISO 电气打架 | **`BUS_Select()` 里先 `BUS_DeselectAll()`** |
| 2 | 忘了 `__HAL_SPI_DISABLE()` 就改分频 | BR 位写不进去（只读保护），速率不变 | 改分频前必须 SPE=0 |
| 3 | 忘记 `__HAL_RCC_GPIOB_CLK_ENABLE()` | Flash 组完全无信号，读到全 `0xFF` | 检查 MspInit 里有没有开 GPIOB 时钟 |
| 4 | **照抄野火的模式 3 配置** | **TF 卡完全不响应**（CMD0 无应答） | **全总线统一模式 0**（CPOL=Low, CPHA=1Edge） |

##### 知识点 2　关于第 2 条：为什么改不了 CR1

SPI 的 `CR1` 寄存器在 `SPE = 1`（外设使能）状态下，**大部分配置位被硬件锁定**：

| 位 | SPE=0 | SPE=1 |
| --- | --- | --- |
| CPOL / CPHA | 可写 | **只读** |
| BR[2:0] | 可写 | **只读** |
| DFF / LSBFIRST | 可写 | **只读** |

> **这是"改了分频没生效"的头号原因**：代码没报错，返回值也是 `HAL_OK`，但寄存器根本没变。**只要记住"改 CR1 先关外设"，这类 bug 就绝迹了。**

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

> ⚠️ **陷阱提醒**：野火第 24 章用的是 **W25Q128**，代码里宏定义写的是 `#define sFLASH_ID 0XEF4018`。**本项目是 W25Q64，必须改成 `0xEF4017`**。照抄野火代码却忘了改这一行，是"读 ID 校验失败"最常见的原因。

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
 * 依赖：bsp_spi1_bus.h（SPI1 公共总线层）
 * 引脚：CS = PA15，CLK = PB3，SDO = PB4，SDI = PB5（信号线全部 AF5，模式 0）
 *
 * 使用约定：
 *   1. 所有公开函数内部会自动 BUS_Select(BUS_DEV_FLASH)，无需调用者手动选片；
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
 * 所有公开函数都在入口处调用 BUS_Select() 选中 Flash，
 * 内部不直接操作 SPI1 的寄存器，也不关心引脚。
 *
 * ★ 注意：本驱动与 TF 卡共用 SPI1，全总线统一模式 0（CPOL=0, CPHA=1Edge）。
 *   野火例程用的是模式 3，照抄时务必把 CLKPolarity/CLKPhase 改成 Low / 1Edge。
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

/* ---------- 进入 Flash 上下文：选中 Flash（总线层会拉低 PA15） ---------- */
static void W25Q64_Enter(void)
{
  BUS_Select(BUS_DEV_FLASH, BUS_SPEED_21M);
}
```

> **`W25Q64_Enter()` 是这套驱动的"统一入口"**。每个公开函数第一行都调它，**保证了不管上一次总线选的是谁，进来时一定已经选中 Flash 并把另一颗的 CS 拉高了**。这就是共享总线对上层"完全透明"的实现方式。

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
  W25Q64_SendByte(W25X_ReadStatusReg);
  status = W25Q64_SendByte(W25Q64_DUMMY_BYTE);
  BUS_DeselectAll();

  return status;
}

/**
 * @brief  写使能：置位 WEL 标志
 * @note   每次擦除/编程前必须调用，因为 WEL 在每次操作结束后自动清零
 */
void W25Q64_WriteEnable(void)
{
  W25Q64_Enter();
  W25Q64_SendByte(W25X_WriteEnable);
  BUS_DeselectAll();
}

/**
 * @brief  写禁止：清除 WEL 标志
 */
void W25Q64_WriteDisable(void)
{
  W25Q64_Enter();
  W25Q64_SendByte(W25X_WriteDisable);
  BUS_DeselectAll();
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
  W25Q64_SendByte(W25X_ReadStatusReg);

  tickstart = HAL_GetTick();
  while ((W25Q64_SendByte(W25Q64_DUMMY_BYTE) & W25Q64_WIP_FLAG) != 0)
  {
    if ((HAL_GetTick() - tickstart) > W25Q64_ERASE_TIMEOUT)
    {
      BUS_DeselectAll();
      return W25Q64_ERR_TIMEOUT;
    }
  }

  BUS_DeselectAll();
  return W25Q64_OK;
}
```

> **注意 `W25Q64_Enter()` 之后就不要再手动拉 CS 了**——`BUS_Select` 已经把 PA15 拉低。**驱动里"选片"和"拉 CS"是同一件事**，重复操作不会错，但会让人困惑。**本笔记统一用 `BUS_Select()` 拉低、`BUS_DeselectAll()` 拉高**，CS 宏只保留给特殊场景。

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
  W25Q64_SendByte(W25X_JedecDeviceID);          /* 0x9F */
  id[0] = W25Q64_SendByte(W25Q64_DUMMY_BYTE);   /* 厂商 ID */
  id[1] = W25Q64_SendByte(W25Q64_DUMMY_BYTE);   /* 容量高字节 */
  id[2] = W25Q64_SendByte(W25Q64_DUMMY_BYTE);   /* 容量低字节 */
  BUS_DeselectAll();

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
  W25Q64_SendByte(W25X_ManufactDeviceID);       /* 0x90 */
  W25Q64_SendByte(0x00);                        /* 3 字节地址（全 0） */
  W25Q64_SendByte(0x00);
  W25Q64_SendByte(0x00);
  mf  = W25Q64_SendByte(W25Q64_DUMMY_BYTE);     /* 厂商 ID */
  dev = W25Q64_SendByte(W25Q64_DUMMY_BYTE);     /* 器件 ID */
  BUS_DeselectAll();

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

  W25Q64_Enter();                       /* ② 指令 + 地址 */
  W25Q64_SendByte(W25X_SectorErase);
  W25Q64_SendAddr(sectorAddr);
  BUS_DeselectAll();                    /* ③ 拉高，芯片开始擦 */

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

  W25Q64_Enter();
  W25Q64_SendByte(W25X_BlockErase);
  W25Q64_SendAddr(blockAddr);
  BUS_DeselectAll();

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
  BUS_DeselectAll();

  W25Q64_Enter();
  W25Q64_SendByte(W25X_ChipErase);
  BUS_DeselectAll();

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
  if (len == 0 || len > W25Q64_PAGE_SIZE)
  {
    return W25Q64_ERR_PARAM;
  }

  W25Q64_Enter();
  W25Q64_WriteEnable();                     /* 写使能 */
  BUS_DeselectAll();

  W25Q64_Enter();
  W25Q64_SendByte(W25X_PageProgram);        /* 0x02 */
  W25Q64_SendAddr(addr);
  W25Q64_SendBytes(pData, len);             /* 一次发完，芯片内部地址自增 */
  BUS_DeselectAll();

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
  W25Q64_SendByte(W25X_ReadData);      /* 0x03 */
  W25Q64_SendAddr(addr);
  W25Q64_RecvBytes(pData, (uint16_t)len);
  BUS_DeselectAll();

  return W25Q64_OK;
}
```

> **注意 `(uint16_t)len` 的类型转换**：`BUS_ReadBytes()` 的参数是 `uint16_t`，如果一次读超过 65535 字节，会被截断。**本项目的 `ReadBuffer` 限制在 64KB 以内**。

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
  W25Q64_SendByte(W25X_PowerDown);       /* 0xB9 */
  BUS_DeselectAll();
  HAL_Delay(1);                          /* tDP = 3µs（最小），给 1ms 富余 */
}

/**
 * @brief  从掉电模式唤醒
 * @note   发 0xAB 后，芯片会回传一个器件 ID 字节，读出即表示已唤醒
 */
void W25Q64_WakeUp(void)
{
  W25Q64_Enter();
  W25Q64_SendByte(W25X_ReleasePowerDown);   /* 0xAB */
  W25Q64_SendByte(W25Q64_DUMMY_BYTE);       /* dummy */
  BUS_DeselectAll();
  HAL_Delay(1);                             /* tRES1 = 3µs */
}
```

#### 技能点 4　初始化与自检

##### 知识点 1　W25Q64_Init 完整实现

```c
/**
 * @brief  W25Q64 初始化与自检
 * @retval W25Q64_OK / W25Q64_ERR_ID
 * @note   内部会通过总线层选中 Flash（PA15 拉低、PA4 拉高、21MHz、模式 0）
 */
int W25Q64_Init(void)
{
  uint32_t id;

  BUS_Select(BUS_DEV_FLASH, BUS_SPEED_21M);   /* 选中 Flash */
  BUS_DeselectAll();
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
    printf("         检查：① 3.3V 供电 ② PB4(SDO) 焊接 ③ PB3/PB4 是否已释放 JTAG\r\n");
    printf("         ④ HAL_SPI_MspInit 里有没有 __HAL_RCC_GPIOB_CLK_ENABLE()\r\n");
  }
  else if (id == 0x000000UL)
  {
    printf("[W25Q64] 错误：ID 全为 0x00 —— MISO 短地/数据线接反\r\n");
  }
  else
  {
    printf("[W25Q64] 错误：ID 不匹配（读到 0x%06lX，期望 0x%06lX）\r\n",
           (unsigned long)id, (unsigned long)W25Q64_JEDEC_ID);
    printf("         若读到的值'像但不完全像'，多半是 CPOL/CPHA 模式不对\r\n");
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
| `0xFFFFFF` | MISO 一直高（上拉/悬空/无供电） | 量 VCC、查 PB4 焊接、查 GPIOB 时钟 |
| `0x000000` | MISO 一直低（短路/CS 时序错） | 查 MISO 是否短地、CS 是否真的在拉低 |
| `0x7Fxxxx` 之类"半对" | **CPOL/CPHA 模式不匹配** | 检查是否误用了模式 3（TF 卡要求模式 0） |
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

  /* ---------- 先看目标扇区是不是已经空白，是就跳过擦除 ---------- */
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
| ID 全 `0xFF` | MISO 悬空 / 无供电 / CS 没拉低 | 万用表量 PB4、VCC、PA15 | 查供电与焊接；确认 `BUS_Select` 被调用 |
| ID 全 `0x00` | MISO 短地 / 数据线接反 | 量 PB4 对地电阻 | 查短路；确认 PB4=DO、PB5=DI 没接反 |
| ID 读 `0xEF4018` | 焊接的是 W25Q128 | 看芯片丝印 | 改宏定义 |
| ID "半对"（如 `0x7F20xx`） | **CPOL/CPHA 不匹配** | 检查是否误用模式 3 | **改成模式 0**（CPOL=Low, CPHA=1Edge） |
| **ID 正常但写不进去** | ① 忘写使能 ② 忘等 BUSY ③ 未擦除 ④ `WP#` 悬空 | 在 `PageWrite` 里打点 | 四条逐一排查 |
| 写入后读回全是 `0xFF` | ① `WP#` 悬空写保护 ② 未擦除 ③ 写使能漏发 | 量 WP# 是否 3.3V | WP# 上拉 10kΩ |
| 前几字节对、后面全错 | 跨页回卷 | 跑 `W25Q64_TestCrossPage()` | 检查 `pageRemain` 计算 |
| 第 0 扇区能写、其它扇区不行 | 地址计算错 | 打印实际发送的 3 字节地址 | 核对高低位顺序 |
| 程序卡死无输出 | SPI 超时用了 `HAL_MAX_DELAY` | — | 改用 100ms 超时 |
| **TF 卡正常但 Flash 全错** | **GPIOB 时钟没开**或 PB3/PB4 被 JTAG 占 | 看 `HAL_SPI_MspInit` | 补 `__HAL_RCC_GPIOB_CLK_ENABLE()`；SYS 选 Serial Wire |
| **两器件都异常** | AF 写成 AF6 | 打开 `spi.c` 看 `GPIO_AF5_SPI1` | SPI1 必须是 AF5 |

#### 技能点 2　用示波器与 GPIO 打点

##### 知识点 1　四个必须看的位置

1. **CS（PA15）**：每次命令是否是"一次干净的低-高"？
2. **SCK（PB3）**：空闲时是否是**低电平**（模式 0 的标志）？有无 8 个完整周期的突发？
3. **MOSI（PB5）**：第一个字节是否是 `0x9F`（读 ID 时）？MSB 是否在前？
4. **MISO（PB4）**：是否有数据随 SCK 变化（而不是一根直线）？

> **注意本项目看的是模式 0**：SCK 空闲时**低电平**。如果你看到空闲高，那就是配成了模式 3，**TF 卡一定不工作**。

##### 知识点 2　用 GPIO 打点测时序

```c
/* 用一根空闲引脚（比如 PE0）标记代码执行段，示波器量高电平宽度 = 该段耗时 */
HAL_GPIO_WritePin(GPIOE, GPIO_PIN_0, GPIO_PIN_SET);
W25Q64_SectorErase(0);
HAL_GPIO_WritePin(GPIOE, GPIO_PIN_0, GPIO_PIN_RESET);
/* 量到的高电平宽度应该 ≈ 45ms（扇区擦除典型值） */
```

> 这招叫"**软件打点**"，比 printf 精确得多（printf 本身就有毫秒级开销），是排查"到底慢在哪"的利器。

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
 * 依赖：bsp_spi1_bus.h（SPI1 公共总线层）
 * 引脚：CS = PA4，CLK = PA5，MISO = PA6，MOSI = PA7（全部 AF5，模式 0）
 *
 * 使用约定：
 *   1. 所有公开函数内部会自动 BUS_Select(BUS_DEV_TF)，无需调用者手动选片；
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

/* ---------- 期望的操作速率 ----------
 * 初始化阶段必须是 328kHz（SD 规范要求 ≤400kHz），
 * 识别完成后由 TF_Init() 改成 21MHz。
 * TF_SendCmd() 每次都用这个值选片，保证速率始终正确。
 */
static uint32_t s_tfSpeed = BUS_SPEED_328K;

/* ---------- 发送命令 + 等 R1 ----------
 * 注意：本函数内部调用 BUS_Select() 选中 TF 卡并拉低其 CS，
 *       CS 会一直保持低电平，由调用者在整笔事务结束时用 BUS_DeselectAll() 拉高。
 */
static uint8_t TF_SendCmd(uint8_t cmd, uint32_t arg, uint8_t crc)
{
  /* 发命令前先拉高再给一个字节时钟，让卡完成上一条命令的内部处理 */
  BUS_DeselectAll();
  TF_XferByte(TF_DUMMY_BYTE);

  BUS_Select(BUS_DEV_TF, s_tfSpeed);        /* 拉低 PA4，选中卡（速率跟随 s_tfSpeed） */
  TF_SendCmdRaw(cmd, arg, crc);

  return TF_WaitR1(TF_CMD_TIMEOUT_MS);
}

/* ---------- 结束一次事务：拉高 CS，补一个时钟 ---------- */
static void TF_EndTransaction(void)
{
  BUS_DeselectAll();
  TF_XferByte(TF_DUMMY_BYTE);
}

/* ---------- 上电 80 个暖机时钟（CS 必须高） ---------- */
static void TF_PowerOnClock(void)
{
  BUS_DeselectAll();
  for (uint8_t i = 0; i < 10; i++)       /* 10 字节 = 80 个时钟，规范要求 ≥74 */
  {
    TF_XferByte(TF_DUMMY_BYTE);
  }
}
```

> **速度参数说明**：`TF_SendCmd()` 里固定用 `BUS_SPEED_21M`，因为在 `TF_Init()` 内部第一次调用前会先手动把总线设成 328kHz。**初始化完成后所有命令都跑 21MHz。**

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

  s_tfSpeed = BUS_SPEED_328K;               /* 检测阶段必须慢速 ≤400kHz */
  BUS_Select(BUS_DEV_TF, s_tfSpeed);        /* 选中卡 */
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
  g_tfInfo.version    = 0;
  g_tfInfo.blockAddr  = 0;
  g_tfInfo.inited     = 0;
  g_tfInfo.capacityMB = 0;

  /* ---------- 步骤 0：切回慢速（若之前在高速）+ 暖机 ---------- */
  s_tfSpeed = BUS_SPEED_328K;                /* 初始化全程必须 ≤400kHz */
  BUS_Select(BUS_DEV_TF, s_tfSpeed);
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
  s_tfSpeed = BUS_SPEED_21M;                 /* ★ 之后所有命令都用这个速率 */
  BUS_Select(BUS_DEV_TF, s_tfSpeed);
  BUS_DeselectAll();

  g_tfInfo.inited = 1;
  printf("[TF] 初始化成功（%s，21 MHz SCK）\r\n",
         g_tfInfo.blockAddr ? "块寻址" : "字节寻址");
  return TF_OK;
}
```

> **`s_tfSpeed` 这个变量是必要的**：因为 `TF_SendCmd()` 每次都要 `BUS_Select()`，如果它写死 `BUS_SPEED_21M`，那么**初始化阶段的 CMD0/CMD8/ACMD41 就会以 21MHz 发出，违反 SD 规范 ≤400kHz 的要求，卡可能完全无响应或偶发失败**。用一个全局变量统一管理当前速率，是这类"分阶段变速"需求的最简单解法。

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

> **为什么不用 CMD18/CMD25（多块读写）**：多块命令需要处理 CMD12（停止传输）和卡自动递增的细节，**出错后更难恢复**。本项目的数据量小、对吞吐率要求不高，**循环单块是更稳妥的工程选择**。

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

**为什么选靠后的块**：即使那块区域有文件系统数据，写坏了顶多丢文件，**不会破坏分区表**。

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
| `TF_Check()` 返回 `0xFF` | ① 卡没插好 ② 供电不足 ③ 模式不是 0 ④ 少了 80 个暖机时钟 | 量 VDD=3.3V，看 PA4/PA6 | 补 80 时钟、确认 CPOL=0/CPHA=1Edge |
| **CMD0 完全无响应** | **SPI 配成了模式 3** | 看 `spi.c` 的 `CLKPolarity` | **改成 `SPI_POLARITY_LOW`** |
| CMD0 有响应但 ACMD41 一直 `0x01` | ① 循环里没延时 ② 参数没置 HCS 位 | 看 ACMD41 参数 | 加 `HAL_Delay(10)`；参数用 `0x40000000` |
| CMD8 返回 `0x05` | v1 老卡（正常现象） | — | 代码已按 v1 处理 |
| CMD17 返回 `0x40` | 块号超出卡容量 | 打印块号与卡容量 | 换合法块号 |
| 读块时等不到 `0xFE` | R1 不是 0x00 就开始等了 | 检查 R1 判断逻辑 | **先判 R1，再等令牌** |
| 写块"成功"但读回不对 | 数据应答判断错 / 没等 BUSY | 看是否判 `(resp & 0x1F) == 0x05` | 补 BUSY 等待 |
| 写卡时程序复位 | 电源跌落（卡写入瞬态电流大） | 量写入瞬间 VDD | 加 10µF~100µF 储能电容 |
| 拔卡后程序死等 | 没有超时机制 | 看每个 while 循环 | 全部加超时并返回错误码 |
| **Flash 正常但 TF 卡不响应** | 片选没拉到 PA4，或模式不对 | 示波器看 PA4 是否变低 | 检查 `BUS_Select(BUS_DEV_TF, ...)` |

---

## 任务九　双器件共存调度与收尾

> **本任务的目标**：把两块器件放进一个工程里跑起来，验证**共享总线是真的安全**——两颗器件交替读写不串数据、片选互斥。**这是对任务五总线层的最终考核。**

### 环节一　调度策略

#### 技能点 1　主程序骨架

##### 知识点 1　完整的 main 结构

```c
/* main.c 的 USER CODE BEGIN 2 区域 */
int main(void)
{
  HAL_Init();
  SystemClock_Config();          /* 168MHz：PCLK2 = 84MHz（SPI1 时钟源） */
  MX_GPIO_Init();                /* PA4 / PA15 两路片选 */
  MX_SPI1_Init();                /* SPI1：模式 0、8 位、÷256（初值） */
  MX_USART1_UART_Init();         /* 115200-8-N-1 */

  printf("\r\n========== SPI 存储项目启动 ==========\r\n");

  /* ---------- 第一阶段：总线层自检 ---------- */
  BUS_Init();
  BUS_SelfTest();

  /* ---------- 第二阶段：两个器件各自初始化 ---------- */
  int flash_ok = (W25Q64_Init() == W25Q64_OK) ? 1 : 0;
  int tf_ok    = (TF_Init()     == TF_OK)     ? 1 : 0;

  printf("\r\n[自检汇总] Flash: %s   TF卡: %s\r\n\r\n",
         flash_ok ? "正常" : "异常",
         tf_ok    ? "正常" : "异常");

  /* ---------- 第三阶段：功能测试 ---------- */
  if (flash_ok) { W25Q64_Test(); W25Q64_TestCrossPage(); W25Q64_TestFullSector(); }
  if (tf_ok)    { TF_DumpBlock0(); TF_Test(); }

  /* ---------- 第四阶段：交替读写压测 ---------- */
  if (flash_ok && tf_ok) DualDeviceStressTest();

  /* ---------- 第五阶段：周期任务 ---------- */
  while (1)
  {
    /* 业务代码放这里 */
  }
}
```

> **三阶段顺序的道理**：**先证明总线能选中谁、再证明单个器件能跑、最后证明两者能交替跑**。任何一步失败，问题就被锁定在那一层，不会混在一起。

#### 技能点 2　交替读写压测

##### 知识点 1　压测程序

```c
/**
 * @brief  双器件交替读写压测：模拟"Flash 存参数、TF 卡存文件"的真实场景
 * @note   每轮都写不同内容，能抓出"片选没互斥导致读到另一颗数据"的隐蔽 bug
 */
void DualDeviceStressTest(void)
{
  static uint8_t fbuf[256];
  static uint8_t tbuf[TF_BLOCK_SIZE];
  static uint8_t rbuf[TF_BLOCK_SIZE];
  uint32_t round, i;
  uint32_t fail = 0;

  printf("\r\n========== 双器件交替读写压测（20 轮） ==========\r\n");

  for (round = 0; round < 20; round++)
  {
    /* ---------- Flash 侧：写 256 字节（每轮内容不同） ---------- */
    for (i = 0; i < sizeof(fbuf); i++)
    {
      fbuf[i] = (uint8_t)(i + round);
    }
    if (W25Q64_EraseAndWrite(0x002000, fbuf, sizeof(fbuf)) != W25Q64_OK)
    {
      printf("  第 %lu 轮：Flash 写失败\r\n", (unsigned long)round);
      fail++;
      continue;
    }

    /* ---------- TF 卡侧：写 512 字节（每轮内容不同） ---------- */
    for (i = 0; i < TF_BLOCK_SIZE; i++)
    {
      tbuf[i] = (uint8_t)(i ^ round);
    }
    if (TF_WriteBlock(3000, tbuf) != TF_OK)
    {
      printf("  第 %lu 轮：TF 写失败\r\n", (unsigned long)round);
      fail++;
      continue;
    }

    /* ---------- 反过来读：先读 TF，再读 Flash ----------
       顺序故意与写入相反，确保每次都真的发生了片选切换 */
    memset(rbuf, 0, sizeof(rbuf));
    if (TF_ReadBlock(3000, rbuf) != TF_OK || memcmp(tbuf, rbuf, TF_BLOCK_SIZE) != 0)
    {
      printf("  第 %lu 轮：TF 读校验失败\r\n", (unsigned long)round);
      fail++;
      continue;
    }

    memset(fbuf, 0, sizeof(fbuf));
    if (W25Q64_ReadBuffer(0x002000, fbuf, 256) != W25Q64_OK)
    {
      printf("  第 %lu 轮：Flash 读失败\r\n", (unsigned long)round);
      fail++;
      continue;
    }
    for (i = 0; i < 256; i++)
    {
      if (fbuf[i] != (uint8_t)(i + round))
      {
        printf("  第 %lu 轮：Flash 读校验失败（第 %lu 字节）\r\n",
               (unsigned long)round, (unsigned long)i);
        fail++;
        break;
      }
    }
  }

  if (fail == 0)
    printf("★ 20 轮交替读写全部通过，共享总线工作正常\r\n");
  else
    printf("✗ 共 %lu 轮失败，请检查 BUS_Select 的片选互斥\r\n", (unsigned long)fail);
}
```

> **为什么要"写 A 读 B"而不是"写完立刻读同一个"**：如果片选没互斥，写完 Flash 立刻读 Flash 会**读到正确数据**（因为 CS 还是它）——这个 bug 就藏住了。**必须交叉操作，才能暴露"该切换时没切"的问题。**

##### 知识点 2　这个测试能抓出什么

**表 9-1 交替压测能暴露的四类 bug**

| 被暴露的 bug | 现象 | 根因 |
| --- | --- | --- |
| `BUS_Select` 的 CS 引脚写反 | Flash 正常，TF 卡全错 | TF/Flash 的 CS 引脚对应关系颠倒 |
| 切换时漏了 `BUS_DeselectAll()` | 偶发读到另一颗的数据 | 两颗器件同时被选中 |
| 忘了 `__HAL_SPI_DISABLE` | 速率没变，第二颗器件时序出错 | CR1 在 SPE=1 时只读 |
| 模式配成了 3 | Flash 正常，**TF 卡完全不动** | TF 卡只支持模式 0 |

---

### 环节二　容错设计与代码规范

#### 技能点 1　统一错误码

##### 知识点 1　三层错误码对照

**表 9-2 三层错误码体系**

| 层 | 错误码前缀 | 示例 | 谁来处理 |
| --- | --- | --- | --- |
| 总线层 | （不返回，由 HAL 状态体现） | `HAL_TIMEOUT` → 返回 `0xFF` | 驱动层判 |
| **FLASH 驱动** | `W25Q64_ERR_*` | `W25Q64_ERR_TIMEOUT` | 应用层判 |
| **TF 卡驱动** | `TF_ERR_*` | `TF_ERR_NO_CARD` | 应用层判 |

> **统一错误码的价值**：上层代码可以统一处理，不用为每个函数单独写一遍。**更重要的是——错误码能让你在三个月后回看这段代码时，一眼知道当时卡在哪一步。**

##### 知识点 2　把调试信息做成宏开关

```c
/* bsp_common.h */
#ifndef __BSP_COMMON_H
#define __BSP_COMMON_H

#include <stdio.h>

#define BSP_DEBUG_ENABLE   1

#if BSP_DEBUG_ENABLE
  #define BSP_LOG(fmt, ...)   printf(fmt, ##__VA_ARGS__)
#else
  #define BSP_LOG(fmt, ...)   ((void)0)
#endif

#endif
```

> **为什么不在驱动里直接写 printf**：驱动里到处 printf 会让代码臃肿，而且量产时要去掉很麻烦。**用一个宏统一开关，调试期打开、发布期关闭**，是工程上的标准做法。
> 本笔记为了教学清晰，代码里直接用了 `printf`；**实际项目里请替换成 `BSP_LOG`**。

#### 技能点 2　代码组织与命名

##### 知识点 1　最终工程结构

```
SPI_Storage/
├── Core/
│   ├── Inc/
│   │   ├── main.h                 ← CubeMX 生成（含引脚宏）
│   │   ├── spi.h                  ← CubeMX 生成
│   │   ├── bsp_common.h           ← ★ 自写：日志宏、通用返回码
│   │   ├── bsp_spi1_bus.h         ← ★ 自写：SPI1 公共总线层（任务五）
│   │   ├── bsp_w25q64.h           ← ★ 自写：W25Q64（任务六）
│   │   └── bsp_tfcard.h           ← ★ 自写：TF 卡（任务八）
│   └── Src/
│       ├── main.c
│       ├── spi.c                  ← CubeMX 生成（勿改）
│       ├── bsp_spi1_bus.c         ← ★ 自写
│       ├── bsp_w25q64.c           ← ★ 自写
│       ├── bsp_tfcard.c           ← ★ 自写
│       └── app_storage.c          ← ★ 自写：测试与业务（任务七、九）
└── Drivers/                       ← HAL 库，不动
```

##### 知识点 2　命名规范

**表 9-3 本项目采用的命名规范**

| 类型 | 前缀/风格 | 示例 |
| --- | --- | --- |
| 文件 | `bsp_` + 器件名 | `bsp_w25q64.c` |
| 公开函数 | `器件名_` + 动作 | `W25Q64_ReadBuffer` |
| 内部函数 | `static` + 同前缀 | `static int W25Q64_PageWrite(...)` |
| 宏 | 全大写 + 下划线 | `W25Q64_PAGE_SIZE` |
| 全局变量 | `g_` 前缀 | `g_tfInfo` |
| 局部静态变量 | `s_` 前缀 | `s_currentDev` |
| 类型 | `_t` / `_T` 后缀 | `TF_Info_t`、`BUS_DEV` |

> **`bsp_` 前缀的含义**：Board Support Package，指"板级支持包"——**专门用来隔离"硬件细节"与"业务逻辑"**。业务代码只调 `W25Q64_ReadBuffer()`，不关心底下用了几根引脚、跑多快。将来换板子，只改 `bsp_` 层，业务代码一行不动。

---

### 环节三　验收清单

#### 技能点 1　逐项验收

##### 知识点 1　十三条验收清单

**表 9-4 项目验收清单（全部打勾才算完成）**

| 序号 | 验收项 | 通过标准 | 关联任务 |
| --- | --- | --- | --- |
| 1 | CubeMX 无引脚冲突警告 | 生成时无黄色/红色告警 | 任务四 |
| 2 | **8 根信号线全部是 AF5** | `spi.c` 中 PA5/6/7 与 PB3/4/5 均为 `GPIO_AF5_SPI1` | 任务四 |
| 3 | **`__HAL_RCC_GPIOB_CLK_ENABLE()` 存在** | MspInit 里有这一行 | 任务四 |
| 4 | 工程编译 0 错误 0 警告 | 编译器输出 | 任务四 |
| 5 | 调试器能连接、能单步 | Keil/CubeIDE 正常下载调试 | 任务一 |
| 6 | **总线层自检** | Flash 读到 `EF 40 17`，TF 读到 `01` | 任务五 |
| 7 | **两路片选互斥** | 示波器：PA4 与 PA15 不同时为低 | 任务五 |
| 8 | W25Q64 读 ID 正确 | `0xEF4017` | 任务六 |
| 9 | W25Q64 擦 + 写 + 读回一致 | 回环校验通过 | 任务七 |
| 10 | W25Q64 跨页写入正确 | 300 字节跨页测试通过 | 任务七 |
| 11 | W25Q64 掉电保持 | 断电重启后数据完好 | 任务七 |
| 12 | TF 卡初始化成功 | 识别出版本与寻址方式 | 任务八 |
| 13 | **双器件交替压测** | 20 轮交叉读写全部通过 | 任务九 |

##### 知识点 2　第 7 项：为什么单列一条

**"两路片选互斥"** 是共享总线正确性的**物理层铁证**。即使软件一切看起来正常，如果这条不满足，就意味着**两颗器件同时驱动各自的 MISO**——后果是：

- 两个推挽输出直接对打，**长期会损伤引脚**；
- 读回的数据是两个信号的"打架结果"，**随机误码**；
- 有时"碰巧"能工作（两颗器件读到相同数据时），**更难排查**。

> **这条必须用示波器验证，软件测不出来。** 这是本项目唯一一条"必须借助仪器"的验收项。

#### 技能点 2　完整验证报告

##### 知识点 1　正常的串口输出

```
========== SPI 存储项目启动 ==========

===== SPI1 公共总线自检 =====
[总线] Flash 读到 ID = EF 40 17（期望 EF 40 17）
[总线] TF 卡读到 R1 = 01（期望 01）
[总线] 自检完成，当前器件 = 1

[W25Q64] JEDEC ID = 0xEF4017
[W25Q64] 检测到 W25Q64（8MB），自检通过
[TF] 检测到卡（CMD0 响应 0x01，空闲态）
[TF] CMD8 响应正常，v2.0 卡
[TF] 高容量卡（SDHC/SDXC），块寻址，单块 512 字节
[TF] 初始化成功（块寻址，21 MHz SCK）

[自检汇总] Flash: 正常   TF卡: 正常

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

[TF] 块 0 前 16 字节：EB 3C 90 4D 53 44 4F 53 35 2E 30 00 02 08 01 00
[TF] 检测到有效引导扇区（卡已格式化）

========== TF 卡读写测试 ==========
[TF] 块 2048 预读成功，首字节 0xFF
[TF] 写入 512 字节完成
★ TF 卡块回环校验通过
[TF] 读回内容：TF-CARD SPI TEST OK!

========== 双器件交替读写压测（20 轮） ==========
★ 20 轮交替读写全部通过，共享总线工作正常
```

##### 知识点 2　这份输出为什么这么"啰嗦"

每一条打印都对应一个**可独立判定的检查点**：

- `[总线] Flash 读到 ID = EF 40 17` → **片选 PA15 有效、AF5 正确、模式 0 正确**；
- `[总线] TF 卡读到 R1 = 01` → **片选 PA4 有效、模式 0 正确**；
- `[TF] CMD8 响应正常` → SD 协议栈第一步成功；
- `[TF] 高容量卡（SDHC）` → CMD58 读到了 OCR，寻址方式确定；
- `★ 20 轮交替读写全部通过` → **共享总线真正经受住了考核**。

> **一个原则：能打印的中间结论，都要打印出来。** 因为嵌入式调试没有断点、没有日志文件、没有 crash dump，**串口就是唯一的"黑匣子"**。**打点越细，定位越快。**

---

### 环节四　项目小结与延伸

#### 技能点 1　回顾整条链路

##### 知识点 1　一句话总结

> **SPI 协议用四根线 + 四种模式定义了"位怎么传"；STM32 的 SPI1 外设把它做成硬件；HAL 库包成四个 API；W25Q64 与 TF 卡在 API 之上各自用"指令集/命令集"定义自己的语义。而让两颗器件共享一条 SPI1 的，就是那两根独立的片选线。**

##### 知识点 2　六级知识链路

```
物理层（四根线）
    → 协议层（CPOL/CPHA，本项目统一模式 0）
        → 外设层（CR1/SR/HAL API）
            → 片选层（两路 CS 互斥 ← 本项目核心）
                → 器件层（W25Q64 指令 / TF 卡 CMD 状态机）
                    → 驱动层（bsp_w25q64.c / bsp_tfcard.c）
                        → 应用层（测试、日志、文件系统）
```

**每往上一层，屏蔽的细节就多一层**：应用层调 `W25Q64_ReadBuffer()` 时，完全不用知道底下是 SPI1、是 AF5、是模式 0、是 21MHz。**分层不是为了好看，是为了"出问题时你能快速定位到哪一层"**：

- ID 读不到 → 看**片选层及以下**（CS、AF5、模式）；
- ID 能读但写不进 → 看**器件层**（写使能、擦除、忙等待）；
- 单颗能跑但交替出错 → 看**片选层**（CS 互斥、`BUS_DeselectAll()`）。

#### 技能点 2　本项目的三条独特经验

##### 知识点 1　三条经验

1. **"两组引脚都属于同一个 SPI"是可行的，前提是它们真的是同一个外设的复用脚**
   一看到"两组引脚"就以为要分时复用，是过度设计。**先查数据手册确认复用编号**——本项目两组都是 AF5，所以可以同时接上。

2. **共享总线的安全性只靠一件事：片选互斥**
   引脚不用切、模式不用切，但要保证**任何时候只有一根 CS 为低**。`BUS_Select()` 里"先全断、后单选"的写法就是这条原则的落地。

3. **共享总线会强制两个器件"统一参数"**
   模式取交集（模式 0）、速率取交集（21MHz）。**设计阶段就要把两个器件的手册参数摆在一起比**，否则写到一半才发现冲突，返工代价很大。

#### 技能点 3　延伸方向

##### 知识点 1　三条延伸路线

**表 9-5 本项目的三条进阶路线**

| 方向 | 要做什么 | 涉及技术 | 难度 |
| --- | --- | --- | --- |
| **提速** | 用 DMA 替代阻塞式收发 | `HAL_SPI_TransmitReceive_DMA()`、双缓冲 | ⭐⭐ |
| **上文件系统** | 移植 FatFs 到 TF 卡 | 实现五个 `disk_*` 函数、配置 `ffconf.h` | ⭐⭐⭐ |
| **做产品** | 日志系统、掉电保护、磨损均衡 | 环形日志、双备份、写前校验 | ⭐⭐⭐⭐ |

##### 知识点 2　FatFs 移植需要的五个函数

**表 9-6 FatFs 移植需要实现的五个底层函数**

| 函数 | 作用 | 在本项目里的实现 |
| --- | --- | --- |
| `disk_initialize()` | 初始化磁盘 | 调 `TF_Init()` |
| `disk_status()` | 查询状态 | 返回 `g_tfInfo.inited` |
| `disk_read()` | 读扇区 | 循环调 `TF_ReadBlock()` |
| `disk_write()` | 写扇区 | 循环调 `TF_WriteBlock()` |
| `disk_ioctl()` | 控制（容量、扇区大小） | 返回 512 和 `g_tfInfo.capacityMB` |

> **注意：TF 卡的扇区是 512 字节，而 W25Q64 的擦除单位是 4KB。** 如果要在 W25Q64 上跑 FatFs，必须实现"**读-改-写**"：先把整个 4KB 扇区读到 RAM，改其中 512 字节，擦整块，再写回。**这是 FLASH 上跑文件系统的核心难点**，也是为什么大多数工程选择在 TF 卡上跑 FatFs、在 W25Q64 上做小数据存储。

##### 知识点 3　如果哪天发现共享总线不够用

虽然本项目按需求"两个都用 SPI1"，但如果将来增加第三个从机、或者两个器件需要**真正并行**（互不阻塞），可以考虑：

1. **增加 SPI 外设**：STM32F407VET6 还有 SPI2、SPI3 可用，把某个器件挪过去；
2. **用硬件片选**：若总线上从机较多，把 NSS 交给 SPI 外设硬件管理（`SPI_NSS_HARD`）；
3. **加外部缓冲/开关**：极端情况下用模拟开关扩展。

> **好消息是迁移成本很低**：`bsp_w25q64.c` 与 `bsp_tfcard.c` **完全不用改**，只需在 `bsp_spi1_bus.c` 里换一个 `hspi` 句柄。**这就是"分层"的回报。**

---

## 本章小结

1. **SPI 是四线制（SCK/MOSI/MISO/NSS）、全双工、同步、推挽的串行总线**，靠 NSS 片选寻址。**本项目两组引脚（PA4~PA7 与 PA15/PB3~PB5）都是 SPI1 的 AF5 复用脚**，所以能同时接在一条总线上。

2. **共享总线的原理是"三线并联 + 片选互斥"**：SCK/MOSI/MISO 三根线并联共用，**没被选中的器件会把 MISO 置为高阻并忽略时钟**，因此同一时刻只要只有一根 CS 为低，就不会冲突。**不需要切换引脚，也不需要分时复用。**

3. **共享总线的硬约束：两个器件必须用同一个 SPI 模式**。TF 卡只支持模式 0，所以**全总线统一模式 0（CPOL=Low, CPHA=1Edge）**。W25Q64 也支持模式 0，可以直接用。**野火例程用的是模式 3，照抄必须改这两行。**

4. **PA15/PB3/PB4 复位后是 JTAG 引脚**，必须在 CubeMX 的 SYS 里把 Debug 选成 **Serial Wire**（不能选 JTAG，也不能选 Trace Asynchronous Sw）。

5. **CubeMX 里要手工把第二组引脚也点成 SPI1**：先选 Full-Duplex Master 自动分配 PA5/6/7，再手工把 PB3/PB4/PB5 分别选成 `SPI1_SCK`/`SPI1_MISO`/`SPI1_MOSI`。**别忘了 `HAL_SPI_MspInit()` 里的 `__HAL_RCC_GPIOB_CLK_ENABLE()`。**

6. **W25Q64 驱动的三定律**：写之前必须擦（最小擦除单位 4KB 扇区）；每页最多写 256 字节且不能跨页；每条擦/写命令前必须发写使能（`0x06`），之后必须查 BUSY 位等待完成。**漏掉任何一条，芯片会静默丢弃命令。**

7. **TF 卡的初始化是一条完整的状态机**：80 个暖机时钟 → CMD0（`0x95`）进 idle → CMD8（`0x87`）电压协商 → CMD55+ACMD41 循环直到 `R1=0x00` → CMD58 读 OCR 判断寻址方式。**R1 的 bit7 = 0 才表示"有响应"。**

8. **TF 卡读写的三个关键判据**：读用 CMD17、等数据令牌 `0xFE`；写用 CMD24、先发 `0xFE`、数据应答判 `(resp & 0x1F) == 0x05`、最后等 BUSY（MISO 从 `0x00` 回到非 `0x00`）。**"卡忙"表现为 MISO 持续 `0x00`，与"卡没反应"的 `0xFF` 方向相反。**

9. **片选互斥是共享总线唯一的红线**：`BUS_Select()` 里必须"先两路都拉高、再拉低目标那一根"。**绝不允许 PA4 与 PA15 同时为低**——那会让两颗器件同时驱动各自的 MISO，电气上打架。

10. **`bsp_spi1_bus.c` 这一层的价值在于"解耦"**：驱动完全不知道引脚在哪、跑多快，将来要换总线（如某个器件挪到 SPI2/SPI3），只改总线层一个文件，两个驱动一行不动。

---

## 常见问题速查

**表 10-1 全项目故障速查表**

| 现象 | 最可能原因 | 排查步骤 | 解决方案 |
| --- | --- | --- | --- |
| CubeMX 里 PB3/PB4/PA15 点不亮 | SYS 的 Debug 选了 JTAG 或 Trace Async Sw | 看 System Core → SYS | 改选 **Serial Wire** |
| CubeMX 里 PB3 选不到 SPI1_SCK | 同上，被 JTAG 占用 | 看 SYS 设置 | 先释放 JTAG，再选 SPI1 |
| **TF 卡完全不动，Flash 正常** | **SPI 配成了模式 3** | 看 `spi.c` 的 `CLKPolarity` | **改成 `SPI_POLARITY_LOW` + `SPI_PHASE_1EDGE`** |
| **Flash 全错，TF 卡正常** | ① GPIOB 时钟没开 ② PB3/PB4 被 JTAG 占 | 看 `HAL_SPI_MspInit` | 补 `__HAL_RCC_GPIOB_CLK_ENABLE()`；释放 JTAG |
| 编译通过但两器件都不响应 | **AF 写成 AF6** | 看 `spi.c` 的 `GPIO_AF5_SPI1` | SPI1 必须是 **AF5** |
| **改了分频没生效** | **SPE=1 时 CR1 只读** | 看是否先 `__HAL_SPI_DISABLE()` | 改 CR1 前必须关外设 |
| 交替读写偶发失败 | 两颗器件同时被选中 | 示波器看 PA4/PA15 是否同时为低 | `BUS_Select()` 里先 `BUS_DeselectAll()` |
| W25Q64 读 ID = `0xFFFFFF` | MISO 悬空/无供电/CS 没拉低 | 量 VCC、PB4、PA15 | 查焊接与 GPIOB 时钟 |
| W25Q64 读 ID = `0xEF4018` | 焊的是 W25Q128 | 看芯片丝印 | 改 `W25Q64_JEDEC_ID` 宏 |
| W25Q64 读 ID "半对" | CPOL/CPHA 不匹配 | 检查是否误用模式 3 | 改成模式 0 |
| W25Q64 写不进、读回全 `0xFF` | ① 忘写使能 ② 忘等 BUSY ③ 未擦除 ④ `WP#` 悬空 | 逐条对照 | 补齐四步；`WP#` 上拉 10kΩ |
| W25Q64 前几字节对、后面错 | 跨页回卷 | 跑跨页测试 | 检查 `pageRemain` 计算 |
| 程序卡死无输出 | SPI 超时用了 `HAL_MAX_DELAY` | 看 API 的 Timeout 参数 | 改成 100ms |
| TF 卡 `TF_Check()` 返回 `0xFF` | ① 卡没插好 ② 供电不足 ③ 模式不是 0 ④ 少了 80 时钟 | 先量 VDD=3.3V | 补 80 时钟、确认模式 0 |
| TF 卡 ACMD41 一直 `0x01` | ① 循环没延时 ② 参数没置 HCS | 看 ACMD41 参数 | 加 `HAL_Delay(10)`；用 `0x40000000` |
| TF 卡读块等不到 `0xFE` | R1 不是 0x00 就开始等了 | 检查 R1 判断 | **先判 R1，再等令牌** |
| TF 卡写块"成功"但读回不对 | 数据应答判错 / 没等 BUSY | 看 `(resp & 0x1F) == 0x05` | 补 BUSY 等待 |
| 写 TF 卡时程序复位 | 电源跌落 | 量写入瞬间 VDD | 加 10µF~100µF 储能电容 |
| 拔卡后程序死等 | 没有超时机制 | 看每个 while 循环 | 全部加超时并返回错误码 |
| 重新 GENERATE 后驱动丢失 | 代码写进 CubeMX 管理区 | 看文件位置 | 自写代码放独立文件 |

---

## 附录 A　本项目速查卡

**表 A-1 关键参数速查**

| 项目 | 参数 | 值 |
| --- | --- | --- |
| 系统时钟 | SYSCLK / HCLK | 168 MHz |
| **SPI1 时钟源** | **PCLK2（APB2）** | **84 MHz** |
| 复用编号 | **SPI1（两组引脚都是）** | **AF5** |
| **TF-CARD 引脚** | CS / CLK / MISO / MOSI | **PA4 / PA5 / PA6 / PA7** |
| **Flash 引脚** | CS / CLK / MISO(SDO) / MOSI(SDI) | **PA15 / PB3 / PB4 / PB5** |
| **SPI 模式** | CPOL / CPHA（两器件共用） | **0 / 0 → Low / 1 Edge（模式 0）** |
| 数据帧 / 位序 | — | 8 位 / MSB 先行 |
| FLASH 速率 | 分频 / SCK | ÷4 / **21 MHz** |
| TF 卡速率 | 分频 / SCK | ÷256→**328 kHz**（初始化）、÷4→**21 MHz**（运行） |
| W25Q64 | JEDEC ID / 容量 | **0xEF4017** / 8 MB |
| W25Q64 | 页 / 扇区 / 块 | 256 B / 4 KB / 64 KB |
| TF 卡 | 块大小 / 最大 SPI 时钟 | **512 B** / 25 MHz |
| 关键指令 | 写使能 / 读状态 / 读 / 页写 / 扇区擦 / JEDEC | `0x06` / `0x05` / `0x03` / `0x02` / `0x20` / `0x9F` |
| TF 卡命令 | CMD0 / CMD8 / CMD55 / ACMD41 / CMD58 / CMD17 / CMD24 | 复位 / 电压协商 / 应用前缀 / 初始化 / 读 OCR / 读块 / 写块 |
| TF 卡固定字节 | CMD0 CRC / CMD8 CRC / 数据令牌 / 写成功应答 | `0x95` / `0x87` / `0xFE` / `(resp & 0x1F) == 0x05` |
| 超时建议 | 单字节 / 扇区擦除 / TF 读块 / TF 写块 | 100 ms / 5000 ms / 500 ms / 1000 ms |

---

## 附录 B　文件清单与依赖关系

**表 B-1 本项目自写文件清单**

| 文件 | 行数量级 | 依赖 | 内容 |
| --- | --- | --- | --- |
| `bsp_common.h` | ~20 | 无 | 日志宏 `BSP_LOG` |
| `bsp_spi1_bus.h` | ~55 | `spi.h`、`main.h` | 器件枚举、分频宏、片选宏、API 声明 |
| `bsp_spi1_bus.c` | ~90 | `bsp_spi1_bus.h` | 片选互斥、速率切换、字节收发 |
| `bsp_w25q64.h` | ~110 | `bsp_spi1_bus.h` | 指令宏、容量宏、错误码、API 声明 |
| `bsp_w25q64.c` | ~380 | `bsp_w25q64.h` | **22 个函数完整实现**（见下表） |
| `bsp_tfcard.h` | ~90 | `bsp_spi1_bus.h` | 命令宏、`TF_Info_t`、错误码、API 声明 |
| `bsp_tfcard.c` | ~420 | `bsp_tfcard.h` | **14 个函数完整实现**（见下表） |
| `app_storage.c` | ~250 | 上述三个驱动 | 测试、压测、自检 |

**表 B-2 bsp_w25q64.c 函数实现清单**

| 函数 | 类型 | 功能 |
| --- | --- | --- |
| `W25Q64_SendByte` | static | 单字节收发（透传总线层） |
| `W25Q64_SendBytes` | static | 连续发送 |
| `W25Q64_RecvBytes` | static | 连续接收 |
| `W25Q64_SendAddr` | static | 发送 24 位地址 |
| `W25Q64_Enter` | static | 选中 Flash（PA15 拉低） |
| `W25Q64_ReadStatus` | 公开 | 读状态寄存器 |
| `W25Q64_WriteEnable` | 公开 | 写使能 `0x06` |
| `W25Q64_WriteDisable` | 公开 | 写禁止 `0x04` |
| `W25Q64_WaitForWriteEnd` | 公开 | 忙等待 BUSY 清零 |
| `W25Q64_ReadID` | 公开 | 读 JEDEC ID `0x9F` |
| `W25Q64_ReadDeviceID` | 公开 | 读厂商/器件 ID `0x90` |
| `W25Q64_SectorErase` | 公开 | 擦 4KB 扇区 `0x20` |
| `W25Q64_BlockErase` | 公开 | 擦 64KB 块 `0xD8` |
| `W25Q64_ChipErase` | 公开 | 整片擦除 `0xC7` |
| `W25Q64_PageWrite` | static | 页编程 `0x02`（1~256B） |
| `W25Q64_WriteBuffer` | 公开 | 任意长度写（按页拆分） |
| `W25Q64_ReadBuffer` | 公开 | 任意长度读 `0x03` |
| `W25Q64_EraseAndWrite` | 公开 | 擦扇区 + 写 |
| `W25Q64_IsBlank` | 公开 | 检查是否全 `0xFF` |
| `W25Q64_PowerDown` | 公开 | 掉电 `0xB9` |
| `W25Q64_WakeUp` | 公开 | 唤醒 `0xAB` |
| `W25Q64_Init` | 公开 | 初始化 + ID 自检 |

**表 B-3 bsp_tfcard.c 函数实现清单**

| 函数 | 类型 | 功能 |
| --- | --- | --- |
| `TF_XferByte` | static | 单字节收发 |
| `TF_SendCmdRaw` | static | 发送 6 字节命令 |
| `TF_WaitR1` | static | 等待并读取 R1 |
| `TF_SendCmd` | static | 发命令 + 等 R1（CS 保持低） |
| `TF_EndTransaction` | static | 拉高 CS + 补时钟 |
| `TF_PowerOnClock` | static | 80 个暖机时钟 |
| `TF_Check` | 公开 | 检测卡是否在线 |
| `TF_Init` | 公开 | 完整初始化（CMD0→CMD8→ACMD41→CMD58） |
| `TF_EnsureReady` | 公开 | 热插拔自愈 |
| `TF_ReadBlock` | 公开 | CMD17 读 512 字节 |
| `TF_WriteBlock` | 公开 | CMD24 写 512 字节 |
| `TF_ReadBlocks` | 公开 | 多块读（循环） |
| `TF_WriteBlocks` | 公开 | 多块写（循环） |
| `TF_GetCapacityMB` | 公开 | 读 CSD 算容量 |

---

> **写在最后**：本笔记的完整代码可以直接贴进 Keil/CubeIDE 编译。**但请务必按"任务五 → 任务七 → 任务九"的顺序验证**——先证明总线能选中谁，再证明单个器件能跑，最后证明两个器件能交替跑。**这个顺序能让每一层的问题都在它自己的层次里被抓住，而不至于混在一起查三天。**

