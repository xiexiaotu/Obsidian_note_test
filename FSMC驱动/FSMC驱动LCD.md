# FSMC—驱动 LCD 屏显示（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F4xx 中文数据手册》FSMC 引脚复用表、《RM0090 STM32F407 参考手册》FSMC 章节、《ILI9341 数据手册》、野火《STM32 HAL 库开发实战指南——基于霸天虎开发板》第 26 章（FSMC 模拟扩展 SRAM）与第 27 章（LCD 液晶显示）。
> **学习提示**：配合参考手册中 FSMC_BCR1~4、FSMC_BTR1~4、FSMC_BWTR1~4 寄存器的说明一起阅读，效果更佳，特别是 ADDSET / DATAST 时序位与访问模式 A/B/C/D 的部分。
> **特别说明**：本笔记内容以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 STM32 HAL 库。LCD 采用 **2.8 寸全彩 TFT 屏（240×320，8080 并口、16 位数据总线、RGB565 色彩格式）**，控制器按最常见的 **ILI9341** 讲解，通过 **FSMC 的 NOR/PSRAM 模式 B** 模拟 8080 时序驱动；屏幕按 **横屏（320×240）** 使用。显示内容取自《IIC 通信》笔记中挂在 PA1/PA0 软件 I2C 总线上的 **BH1750 光照 / HTU21D 温湿度 / PCF8563 时钟 / LIS3DH 三轴**传感器数据。

---

## 1. LCD 与显示控制器简介

### 1.1 液晶显示器的基本概念

液晶显示器（LCD，Liquid Crystal Display）靠电压改变液晶分子的排列方向来控制背光的透过率，从而显示图像。衡量一块屏的基本参数：

- **像素**：图像的最小单元，一个像素就是一个光点；
- **分辨率**："行像素数 × 列像素数"，如本屏 240×320，即一个方向 240 个像素、另一个方向 320 个像素（横屏用时就是 320×240）；
- **色彩深度**：每个像素用多少位表示颜色。本屏采用 **RGB565 格式**：红色 5 位、绿色 6 位、蓝色 5 位，共 16 位，即每个像素用 1 个 16 位数据（`uint16_t`）表示，可显示 2¹⁶ = 65536 种颜色；
- **点距**：相邻像素中心的距离，决定屏的精细程度。

> **"2.8 寸 / 240×320 / 全彩 TFT"这几个词的关系**：2.8 寸是**屏的物理对角尺寸**，240×320 是**分辨率**（像素个数），全彩指每个像素可以显示 65536 种颜色（而不是只能显示固定字形的"字符屏"）。三者彼此独立——同样 2.8 寸可以有 240×320 或 320×480 的不同分辨率屏。

### 1.2 显示控制器与 GRAM

单片机不可能自己逐点驱动液晶屏的几百个像素引脚，必须由**显示控制器**芯片代劳。本屏集成的控制器是 **ILI9341**（2.8 寸 240×320 屏最常见的 8080 并口控制器），它的核心是一块 **GRAM（Graphics RAM，图形存储器）**：

- GRAM 中**每个存储单元对应屏幕上的一个像素**；
- MCU 把像素的 RGB565 颜色值写入 GRAM，ILI9341 就**周期性自动刷新屏幕**，MCU 不需要持续干预；
- MCU 通过 **8080 并行接口**向 ILI9341 发送**控制命令**（如设置分辨率、开窗坐标）和**像素数据**（写入 GRAM）。

ILI9341 可以通过 **IM[3:0] 引脚**配置成 SPI 接口、8080 并口（18/16/9/8 位）等模式。本笔记按 **8080 并口、16 位数据线**讲解——这也是能用 FSMC 驱动的前提。

> **买屏/接线前必须先确认这一点（最容易翻车的地方）**：市面上大量 2.8 寸 240×320 模块是**只有 8 根接口线的 SPI 版**（VCC/GND/CS/RST/DC/MOSI/SCK/BL），它**没有 8080 并口**，无论怎么接都不能用 FSMC 驱动（只能用 SPI，速度慢得多）。能用 FSMC 的是**并口版模块**，引出 DB0~DB15 + RD/WR/RS/CS/RST，模块板上的 IM 配置焊盘/电阻已选好 8080-16 模式（有些模块留了跳线供切换，需照模块说明确认）。**选屏时看接口线数量，是唯一的快速判据。**

### 1.3 8080 并行接口的信号与时序

8080 接口因 Intel 8080 处理器总线而得名，是液晶屏最常见的 MCU 接口。本屏引出的 8080 相关信号如下：

**表 1-1 液晶屏 8080 接口信号说明**

| 信号线 | ILI9341 对应 | 说明 |
| --- | --- | --- |
| LCD_DB[15:0] | D[17:0] 中的 D[15:0] | 16 位数据线，传输命令与像素数据 |
| LCD_RD | RDX | 读数据信号，低电平有效 |
| LCD_WR | WRX | 写数据信号，低电平有效 |
| LCD_RS | D/CX | 数据/命令选择：高电平 = 传输的是数据，低电平 = 传输的是命令 |
| LCD_CS | CSX | 片选，低电平有效 |
| LCD_RST | RESX | 复位，低电平有效 |
| LCD_BL | — | 背光控制，高电平点亮（可直接由普通 GPIO 控制） |

**写命令的时序过程**：片选 CSX 拉低 → D/CX 拉低（表示接下来是命令）→ WRX 拉低（数据线上出现命令码，ILI9341 在 WRX 上升沿锁存）→ 若该命令带参数，则把 D/CX 拉高，继续以同样方式写参数字节 → CSX 拉高结束。

```
        _________________________                    ______
CSX                            |______________________|
        ____________________________________________
D/CX   （命令阶段=低电平）_____|（参数阶段=高电平）
        __________________     ____________     ______
WRX                       |___|            |___|
        ================== === ============ === =====
D[15:0] ================== 命令码 ============ 参数 ===
```

写像素数据（填 GRAM）则更简单：CSX 拉低、D/CX 拉高，然后连续往数据线送 RGB565 颜色值即可，ILI9341 内部有地址自增，像素会自动按窗口顺序填充。

---

## 2. STM32F407VET6 的 FSMC 简介

### 2.1 FSMC 是什么

FSMC（Flexible Static Memory Controller，灵活的静态存储控制器）是 STM32 片内专门用于**扩展外部存储器**的外设。它可以驱动 SRAM、NOR FLASH、NAND FLASH、PC 卡等器件；F429 上的升级版 FMC 还能驱动 SDRAM（F407 不支持 SDRAM）。

用 FSMC 驱动 LCD 的思路极其巧妙：**MCU 对 LCD 的写操作本质上就是"把显示数据写到显存 GRAM 里"，与访问外部 SRAM 一模一样**——而 8080 接口的 CSX/WRX/RDX/D/CX 时序，恰好可以用 FSMC 的 NOR FLASH 模式 B 时序模拟出来（详见第 4 节）。

### 2.2 FSMC 的功能框图

FSMC 框图按信号流向可拆成四部分：

**① 通讯引脚**。FSMC 引脚与 GPIO 复用，需要查数据手册的复用表配置（FSMC 固定用 **AF12**）。与 NOR/PSRAM/LCD 相关的引脚类别：

**表 2-1 FSMC（NOR/PSRAM 模式）信号**

| FSMC 信号 | 性质 | 对应 LCD 信号 |
| --- | --- | --- |
| FSMC_D[15:0] | 双向数据线 | LCD_DB[15:0] |
| FSMC_NE[1:4] | 片选（输出） | LCD_CS |
| FSMC_NWE | 写使能（输出） | LCD_WR |
| FSMC_NOE | 输出使能/读（输出） | LCD_RD |
| FSMC_A[25:0] | 地址线（输出） | LCD_RS（用其中一根地址线模拟） |

**② 存储控制器**。分 NOR/PSRAM/SRAM 控制器和 NAND/PC 卡控制器两部分，由寄存器组配置：

- **FSMC_BCR1~4（控制寄存器）**：配置存储器类型、数据宽度、写使能等；
- **FSMC_BTR1~4（读时序寄存器）**：配置读时序的 ADDSET/DATAST 等时间参数；
- **FSMC_BWTR1~4（写时序寄存器）**：扩展模式下单独配置写时序。

**③ 时钟控制**。FSMC 挂在 AHB 总线上，时钟直接来自 **HCLK（168MHz）**；只有驱动同步突发型存储器时才需要 CLKDIV 分频出 FSMC_CLK，驱动 LCD 用不到。

**④ 地址映射**。FSMC 把外部存储器映射到 STM32 的地址空间，详见 2.3 节。

### 2.3 FSMC 的地址映射——理解 FSMC 的关键

这是 FSMC 最精妙的地方：配置好 FSMC 后，**STM32 访问外部存储器就像访问内部数组一样，直接用指针读写某个地址即可**。FSMC 的地址空间位于 External RAM 区域，分 4 个 Bank：

**表 2-2 FSMC Bank 地址映射**

| Bank | 用途 | 片选信号 | 地址范围 |
| --- | --- | --- | --- |
| Bank1 NOR/SRAM 1 | NOR/PSRAM/SRAM | FSMC_NE1 | 0x60000000 ~ 0x63FFFFFF |
| Bank1 NOR/SRAM 2 | NOR/PSRAM/SRAM | FSMC_NE2 | 0x64000000 ~ 0x67FFFFFF |
| Bank1 NOR/SRAM 3 | NOR/PSRAM/SRAM | FSMC_NE3 | 0x68000000 ~ 0x6BFFFFFF |
| Bank1 NOR/SRAM 4 | NOR/PSRAM/SRAM | FSMC_NE4 | 0x6C000000 ~ 0x6FFFFFFF |
| Bank2 NAND FLASH | NAND | — | 0x70000000 ~ 0x73FFFFFF |
| Bank3 NAND FLASH | NAND | — | 0x80000000 ~ 0x83FFFFFF |
| Bank4 PC 卡 | PC Card | — | 0x90000000 ~ 0x9FFFFFFF |

片选与地址是**联动**的：只要 CPU 访问 0x60000000~0x63FFFFFF 区间的地址，FSMC 就自动把 NE1 拉低并按配置的时序发起一次总线传输——**不需要任何 GPIO 操作**。这正是"用指针操作 LCD"的硬件基础。

---

## 3. 液晶屏与开发板的接线

本节给出 **2.8 寸 240×320 并口屏（ILI9341）** 与 STM32F407VET6 的完整接线。本工程约定的关键引脚是：**LCD_CS = PD7（FSMC_NE1）、LCD_RS = PD12（FSMC_A17）、LCD_BL = PD2（普通 GPIO）、LCD_RST = SYS_RSTA**；其余信号按下面这张表与 FSMC 的数据/读写信号线一一对应。如果屏模块自带板对板插座直接插在开发板的 LCD 座上，实际连接与下表一致（开发板已把这些信号连到 FSMC 引脚）。

### 3.1 完整接线表

**表 3-1 LCD 与 STM32F407VET6 的引脚对应关系**

| LCD 信号 | STM32 引脚 | FSMC 复用功能 | 说明 |
| --- | --- | --- | --- |
| LCD_D0 | PD14 | FSMC_D0 | 数据线 |
| LCD_D1 | PD15 | FSMC_D1 | 数据线 |
| LCD_D2 | PD0 | FSMC_D2 | 数据线 |
| LCD_D3 | PD1 | FSMC_D3 | 数据线 |
| LCD_D4~D12 | PE7~PE15 | FSMC_D4~D12 | 数据线 |
| LCD_D13 | PD8 | FSMC_D13 | 数据线 |
| LCD_D14 | PD9 | FSMC_D14 | 数据线 |
| LCD_D15 | PD10 | FSMC_D15 | 数据线 |
| LCD_RD | PD4 | FSMC_NOE | 读信号 |
| LCD_WR | PD5 | FSMC_NWE | 写信号 |
| **LCD_CS** | **PD7** | **FSMC_NE1** | 片选 → 映射到 Bank1 区域 1 |
| **LCD_RS** | **PD12** | **FSMC_A17** | 数据/命令选择 → 用地址线 A17 模拟 |
| LCD_RST | **SYS_RSTA** | —（GPIO/系统复位） | 屏幕复位，低有效 |
| LCD_BL | **PD2** | —（普通 GPIO） | 背光控制，高电平点亮 |

> **与通用教程的差异说明**：很多资料把 LCD_RS 接在 FSMC_A0 上（此时命令/数据地址相差 2）。本开发板为了排布方便把 **RS 接到了 A17（PD12）**，地址计算方式与 A0 方案完全相同，只是偏移位从 0 变成 17（见 4.2 节）。另外 **CS 用的是 NE1（PD7）**，所以整个屏映射在 Bank1 区域 1，基地址是 **0x60000000**。
> **引脚名称的对应关系**（模块丝印各家不同，作用是一样的）：`LCD_CS` 有的模块标成 `LCD_CD`/`CSX` → 接 **FSMC_NE1**；`LCD_RS` 有的标成 `LCD_DC`/`D/CX` → 接 **FSMC 地址线**（本板 A17）；`LCD_WR`=`WRX`/`LCD_RD`=`RDX` → 接 FSMC_NWE/NOE。**判断方法很简单：片选必须接在 NE 系列引脚上，数据/命令选择必须接在 A 系列地址线上**——接错这两根，屏幕一定不亮或花屏。
> **FSMC 引脚全部是 AF12 复用**：CubeMX 中使能 FSMC 后这些引脚会自动被占用，请勿再分配给其它外设。PD2（背光）和 SYS_RSTA（复位）是普通 GPIO，不属于 FSMC。

### 3.2 接线注意

1. 屏的供电与逻辑电平都是 3.3V，由开发板插座直接供电，无需电平转换；
2. LCD_BL（PD2）为普通推挽输出即可，若需要调亮度，也可改用 TIM 的 PWM 输出驱动（本笔记用高低电平开关）；
3. LCD_RST 接 SYS_RSTA 时，屏幕随系统复位自动复位；若要程序单独复位屏幕，需把该信号改接到普通 GPIO。

---

## 4. 用 FSMC 模拟 8080 接口

### 4.1 信号对应关系

对比 FSMC NOR 模式与 8080 接口的信号，几乎一一对应：

**表 4-1 FSMC NOR 模式信号与 8080 信号对比**

| FSMC-NOR 信号 | 性质 | 8080 信号 | 性质 |
| --- | --- | --- | --- |
| FSMC_NEx | 片选 | CSX | 片选 |
| FSMC_NWE | 写使能 | WRX | 写使能 |
| FSMC_NOE | 读使能 | RDX | 读使能 |
| FSMC_D[15:0] | 数据线 | D[15:0] | 数据线 |
| FSMC_Ax | 地址线 | D/CX（RS） | 数据/命令选择 |

前四组直接对应，唯一的差异是：**8080 的 D/CX 用一根"电平信号"区分命令和数据，而 FSMC 只有地址线**。解决办法是拿一根地址线（本板为 **A17**）当 D/CX 用：

- 访问的地址让 **A17 = 1** → RS 为高电平 → ILI9341 认为传输的是**数据**；
- 访问的地址让 **A17 = 0** → RS 为低电平 → ILI9341 认为传输的是**命令**。

### 4.2 命令地址与数据地址的计算（重点）

这里有一个极易出错的细节——**HADDR 与 FSMC 地址线之间的错位**。STM32 内部用 HADDR 总线寻址外部器件，HADDR 以**字节**为单位；而 FSMC 配置为 **16 位数据宽度**时，FSMC_A[0] 对应的是 HADDR[1]，即**内部地址整体右移一位**后才送到地址线上：

```
HADDR[25:0]  >> 1  →  FSMC_A[25:0]
即：FSMC_A17 = 1  ⟺  HADDR 的第 (17+1) = 18 位为 1
```

因此命令/数据地址的计算为（基地址 0x60000000，NE1 区域）：

```
命令地址 = 0x60000000 & ~(1 << (17+1)) = 0x60000000
数据地址 = 0x60000000 |  (1 << (17+1)) = 0x60040000
```

**验证**：写 `0x60040000` 时，HADDR bit18 = 1 → FSMC_A17 输出高电平 → RS = 高 → ILI9341 收到的是数据，正确。若你的板子 RS 接的是 A0，则数据地址 = 0x60000000 | (1 << 1) = 0x60000002，计算方式完全一致。

在代码里写成宏：

列表 1: 代码清单 4-1 FSMC 命令/数据地址宏（bsp_lcd.h）

```c
/* FSMC Bank1 NOR/SRAM 区域 1（NE1，PD7）基地址 */
#define FSMC_LCD_BASE        ((uint32_t)0x60000000)

/* RS 接 FSMC_A17：地址第 (17+1) 位为 1 时传输数据，为 0 时传输命令 */
#define LCD_CMD_ADDR         (FSMC_LCD_BASE)                 /* A17 = 0 */
#define LCD_DATA_ADDR        (FSMC_LCD_BASE | (1UL << 18))   /* A17 = 1 */

/* 用指针直接操作 LCD——配置好 FSMC 后，这两句宏就是全部的"写命令/写数据" */
#define LCD_WRITE_CMD(cmd)   (*(__IO uint16_t *)(LCD_CMD_ADDR)  = (cmd))
#define LCD_WRITE_DATA(dat)  (*(__IO uint16_t *)(LCD_DATA_ADDR) = (dat))
#define LCD_READ_DATA()      (*(__IO uint16_t *)(LCD_DATA_ADDR))
```

> **指针访问的本质**：`*(__IO uint16_t *)0x60040000 = 0x2C` 这一行 C 语句，编译后是一条 STRH 存储指令；CPU 执行它时，FSMC 自动完成"NE1 拉低 → A17 输出对应电平 → 数据线输出 0x002C → NWE 拉低再拉高 → NE1 拉高"的完整 8080 写时序。**这就是 FSMC 模拟 8080 的全部秘密——软件上看不到任何时序代码。**

### 4.3 访问模式与时序计算

FSMC 驱动 LCD 使用 **NOR FLASH 的访问模式 B**（Mode B）。模式 B 的读写时序由 FSMC_BTR 寄存器中的两个参数主导：

- **ADDSET（AddressSetupTime）**：地址建立阶段长度，单位 HCLK 周期；
- **DATAST（DataSetupTime）**：数据建立阶段长度，单位 HCLK 周期。

HCLK = 168MHz，1 个 HCLK 周期 = 1000/168 ≈ 5.95 ns。模式 B 下读写周期与这两个参数的关系为：

```
读周期 trc  = (ADDSET+1) + (DATAST+1) + 2  个 HCLK
写周期 twc  = (ADDSET+1) + (DATAST+1)      个 HCLK
```

**ILI9341** 的 8080 接口时序要求（见其数据手册 AC Characteristics）：**写周期 tWC(min) ≈ 66 ns**、地址建立 tAST(min) ≈ 0 ns、数据建立 tDST(min) ≈ 10 ns。按 ADDSET = 5、DATAST = 15 计算：

```
写周期 twc = ((5+1) + (15+1)) × 5.95 ns ≈ 130.9 ns  ≫ 66 ns ✓
读周期 trc = ((5+1) + (15+1) + 2) × 5.95 ns ≈ 142.8 ns ✓
```

这组值是**实测收敛的结果**，比手册要求宽了一倍：320×240 整屏 76800 个像素 × 130.9ns ≈ **10ms** 刷完一屏，对秒级刷新传感器数据的应用完全无感，换来的是**任何时序裕量不足的模组都能稳跑**。

> **排查经验（本工程踩过的坑，值得记住）**：一开始怀疑"一次连写 76800 个像素、写到后面丢数据"，于是把 ADDSET 从 4 加到 5、DATAST 从 8 加到 15。**后来定位到真正原因是 MADCTL 的 MV 位（见 6.5 节），跟时序无关**——但放宽后的时序一直保留：它把"时序临界"这个变量彻底排除掉，后面调方向时才不会把"方向问题"误判成"时序问题"。**调屏的铁律是：一次只改一个变量，能用余量换来的确定性就不要吝啬。**

> **关于这两个式子的说明**：上面是工程上常用的经验式（模式 A / 模式 B 的差别在于读操作是否插入额外的总线周转时间，不同资料写法略有出入）。**对驱动的正确性而言，关键只有一条：时序要留够余量，最终以实测波形为准**——先按 ADDSET = 5、DATAST = 15 配好，能稳定刷屏就不必再抠。**DATAST 每加 1 就多约 6ns，加得越多刷屏越慢**：本笔记配置下一次 16 位写周期约 **131ns**，这也是后文计算"刷一屏要多少 CPU 时间"的基准（320×240 = 7.68 万像素 × 131ns ≈ **10ms**）。

> **排错直觉（按"命中率"排序）**：
> 1. **画面能显示但右侧/尾部有一条花带或整块丢失** → 先查 MADCTL 是否带了 **MV 位**（详见 6.5 节），这是本工程真正的原因，跟时序没关系；
> 2. **颜色错乱、随机色块** → DATAST 太小，数据未稳定即被锁存，加大 DATAST；
> 3. **完全白屏** → FSMC 根本没配通，先查 NE1 与 A17 的引脚复用、Write Operation 是否 Enabled；
> 4. **画面整体旋转 90°** → 方向问题，也是 MADCTL（6.5 节）。
>
> **先纯色刷屏、再自检图、最后才看内容**——这个顺序能把"硬件/时序/方向/内容"四类问题分开，一次只面对一个。

---

## 5. STM32CubeMX 配置工程

### 5.1 新建工程与系统时钟

1. CubeMX 欢迎页 → **New Project**，搜索 `STM32F407VET6`，选 LQFP100 封装；
2. **RCC** → HSE = Crystal/Ceramic Resonator（8MHz 外部晶振）；
3. **Clock Configuration**：PLL 源 HSE，PLL_M=8、PLL_N=336、PLL_P=2，**SYSCLK = 168MHz，HCLK = 168MHz**（FSMC 直接吃 HCLK，这决定了 ADDSET/DATAST 的实际时间）。

### 5.2 配置 FSMC（NOR Flash/PSRAM/SRAM/ROM/LCD）

1. 左侧 **Connectivity → FSMC**，勾选 **Memory type = LCD Interface**；
2. **Chip Select** 选 **NE1**（对应 PD7）；**LCD Register Select** 选 **A17**（对应 PD12）——CubeMX 会自动把 PD14/PD15/PD0/PD1/PE7~PE15/PD8~PD10 配成数据线、PD4=NOE、PD5=NWE、PD7=NE1、PD12=A17，全部 AF12；
![](Pasted%20image%2020261025152138.png)


3. **Parameter Settings** 按下表填写：

**表 5-1 FSMC Parameter Settings（LCD Interface，NE1 + A17）**

| 配置项                                       | 取值            | 说明                    |
| ----------------------------------------- | ------------- | --------------------- |
| Memory type                               | LCD Interface | 本质就是 NOR 模式 B         |
| LCD Register Select                       | A17           | RS 引脚 = PD12          |
| Data                                      | 16 bits       | RGB565 一像素 16 位       |
| Address setup time in HCLK clock cycles   | 5             | ADDSET = 5            |
| Data setup time in HCLK clock cycles      | 15            | DATAST = 15（见 4.3 节计算，twc ≈ 131ns） |
| Bus turn around time in HCLK clock cycles | 0             | LCD 不需要               |
| Extended mode                             | Disable       | 读写共用一套时序              |
| Wait                                      | Disable       | ILI9341 不接 NWAIT     |
| Write operation                           | Enabled       | 必须使能写，否则只能读           |
![](Pasted%20image%2020261025152325.png)

4. **NVIC / DMA**：FSMC 本身不产生中断与 DMA 请求，这里**不用勾选**（LCD 的 DMA 在第 8 章用 DMA2 内存到内存方式单独配置）。

> **关于配置时可能出现的警告**：勾选 NE1 后，CubeMX 有时会在 FSMC 一栏给出 *Partly disabled conflict with … NE1 Chip Select* 之类的黄色提示。它的含义是"FSMC 占用的一批 GPIO（PD/PE 口的 AF12 引脚）原本还复用着别的外设功能，那部分功能已被自动禁用"，属于**提示而非错误**。核对方法：按 Ctrl+D 看冲突明细，只要冲突的另一方是你用不到的外设（如 ETH、SDIO、其它 USART），且 Pinout 视图里本笔记用到的脚（PD7 = NE1、PD12 = A17、PD4/PD5 = NOE/NWE、PD14/PD15/PD0/PD1/PE7~PE15/PD8~PD10 = 数据线、PD2 = 背光）都不是"硬冲突"，就可以放心忽略。反之若冲突方是你确实要用的外设（如想用 PD8/PD9 做 USART3），就必须给那个外设换到别的引脚。

### 5.3 配置背光 PD2 与软件 I2C 总线

1. **System Core → GPIO** → 点击 **PD2**，选 **GPIO_Output**；参数：Output level = Low（先关背光）、**Output Push-Pull**、Pull-up、Very High，User Label 填 `LCD_BL`；
![](Pasted%20image%2020261025152609.png)
2. 同一个 GPIO 面板里，把 **PA1 / PA0** 配置为 **Output Open Drain + Pull-up + Very High**（软件 I2C 的 SCL/SDA，与《IIC 通信》笔记 5.4 节完全一致，初始电平 High）；
3. 若板子上 SYS_RSTA 不是系统复位而是普通 GPIO，则把它也配置为推挽输出，别名 `LCD_RST`；
4. 如需串口辅助调试，照旧配置 USART1（PA9/PA10，115200-8-N-1）。
### 5.4 生成代码

Project Manager 填工程名（如 `FSMC_LCD_Sensor`），工具链选 MDK-ARM 或 CubeIDE，建议勾选 *Generate peripheral initialization as a pair of .c/.h files per peripheral*，然后 **GENERATE CODE**。

生成后重点文件：

- `fsmc.c`：`MX_FSMC_Init()` —— 填充 `SRAM_HandleTypeDef` 与时序结构体，调用 `HAL_SRAM_Init()`；GPIO 复用配置在 `HAL_SRAM_MspInit()`（`fsmc.c` 或 `stm32f4xx_hal_msp.c`）里；
- `gpio.c`：`MX_GPIO_Init()` —— 含 PD2 背光、PA1/PA0 开漏（软件 I2C）配置。

列表 2: 代码清单 5-1 CubeMX 生成的 FSMC 初始化核心（fsmc.c，注释为笔记添加）

```c
SRAM_HandleTypeDef hsram1;

void MX_FSMC_Init(void)
{
  FSMC_NORSRAM_TimingTypeDef Timing = {0};

  hsram1.Instance  = FSMC_NORSRAM_DEVICE;
  hsram1.Extended  = FSMC_NORSRAM_EXTENDED_DEVICE;

  hsram1.Init.NSBank             = FSMC_NORSRAM_BANK1;          /* NE1 → Bank1 区域1 */
  hsram1.Init.DataAddressMux     = FSMC_DATA_ADDRESS_MUX_DISABLE;
  hsram1.Init.MemoryType         = FSMC_MEMORY_TYPE_NOR;        /* LCD Interface 本质即 NOR 模式B */
  hsram1.Init.MemoryDataWidth    = FSMC_NORSRAM_MEM_BUS_WIDTH_16;
  hsram1.Init.BurstAccessMode    = FSMC_BURST_ACCESS_MODE_DISABLE;
  hsram1.Init.WaitSignalPolarity = FSMC_WAIT_SIGNAL_POLARITY_LOW;
  hsram1.Init.WrapMode           = FSMC_WRAP_MODE_DISABLE;
  hsram1.Init.WaitSignalActive   = FSMC_WAIT_TIMING_BEFORE_WS;
  hsram1.Init.WriteOperation     = FSMC_WRITE_OPERATION_ENABLE; /* 必须允许写 */
  hsram1.Init.WaitSignal         = FSMC_WAIT_SIGNAL_DISABLE;
  hsram1.Init.ExtendedMode       = FSMC_EXTENDED_MODE_DISABLE;  /* 读写共用 Timing */
  hsram1.Init.AsynchronousWait   = FSMC_ASYNCHRONOUS_WAIT_DISABLE;
  hsram1.Init.WriteBurst         = FSMC_WRITE_BURST_DISABLE;
  hsram1.Init.PageSize           = FSMC_PAGE_SIZE_NONE;

  Timing.AddressSetupTime      = 5;    /* ADDSET：地址建立，5 个 HCLK ≈ 29.8ns */
  Timing.AddressHoldTime       = 15;   /* 模式 B 下无效，随意 */
  Timing.DataSetupTime         = 15;   /* DATAST：数据建立，15 个 HCLK ≈ 89.3ns */
  Timing.BusTurnAroundDuration = 0;
  Timing.CLKDivision           = 16;   /* 异步模式无效，随意 */
  Timing.DataLatency           = 17;   /* 异步模式无效，随意 */
  Timing.AccessMode            = FSMC_ACCESS_MODE_A;  /* CubeMX 的 LCD Interface 生成的是模式 A */

  if (HAL_SRAM_Init(&hsram1, &Timing, NULL) != HAL_OK)
  {
    Error_Handler();
  }
}

/* HAL_SRAM_MspInit 中 CubeMX 已自动完成：
   __HAL_RCC_FSMC_CLK_ENABLE();
   GPIOD/GPIOE 相关引脚配置为 GPIO_MODE_AF_PP + GPIO_AF12_FSMC */
```

---

## 6. LCD 驱动程序设计

### 6.1 程序分层

```
Core/Src/main.c          ← 主循环：初始化 → 采集 → 刷新（只剩 HAL 初始化与 while(1)）
MDK-ARM/
├── iic.h / IIC.C            ← 软件 I2C 时序层（PA1=SCL、PA0=SDA），含 I2C_Probe() 探针
├── BH1750.H / bh1750.c      ← 光照传感器（自动试 0x46 / 0xB8 两个地址）
├── LIS3DH.h / lisd3h.c      ← 三轴加速度（自动试 0x32 / 0x30 两个地址）
├── LCD.h / lcd.c            ← LCD 底层：初始化、开窗、软件翻转、画点、刷屏、自检图
├── font_asc2_1608.c         ← 8×16 ASCII 点阵字库（唯一的数据文件）
└── app_ui.c / app_ui.h      ← 显示层：版面布局 + 数值刷新（见 7.7 节）
```
![](Pasted%20image%2020261025152747.png)

> **文件名对照**：本笔记正文为叙述方便仍沿用 `bsp_` 前缀（`bsp_lcd` ↔ `LCD.h` / `lcd.c`，`bsp_soft_i2c` ↔ `iic.h` / `IIC.C`，`bsp_bh1750` ↔ `BH1750.H` / `bh1750.c`，`bsp_lis3dh` ↔ `LIS3DH.h` / `lisd3h.c`），**第 6 章的代码清单已经是工程里的实际文件内容**，可以逐字对拷。本工程实际只挂了 BH1750 + LIS3DH 两颗传感器，HTU21D / PCF8563 按同样思路加即可（见 7.7 节）。

### 6.2 LCD 底层驱动

列表 3: 代码清单 6-1 LCD 底层接口（LCD.h，与本工程源码逐字一致）

```c
#ifndef __LCD_H_
#define __LCD_H_

#include "stm32f4xx_hal.h"

/* ---------- FSMC 地址映射（计算过程见 4.2 节） ----------
   NE1 片选基址 0x60000000，RS 接 FSMC_A17。
   16 位数据总线时，内部地址位 A[18] 才对应外部引脚 A17，
   所以命令/数据切换的偏移量是 1<<18（不是 1<<17）。 */
#define FSMC_LCD_BASE      ((uint32_t)0x60000000U)        /* NE1 片选，最低 16 位地址 */
#define LCD_CMD_ADDR       (FSMC_LCD_BASE)                /* A17=0 → 命令 */
#define LCD_DATA_ADDR      (FSMC_LCD_BASE | (1UL << 18))  /* A17=1 → 数据 */

#define LCD_WRITE_CMD(c)   (*(__IO uint16_t *)(LCD_CMD_ADDR)  = (uint16_t)(c))
#define LCD_WRITE_DATA(d)  (*(__IO uint16_t *)(LCD_DATA_ADDR) = (uint16_t)(d))

/* ---------- 屏幕分辨率：横屏 320 x 240 ----------
   注意：这两个宏同时是"逻辑坐标系"的边界，也是开窗裁剪的边界。
   它们描述的是**使用方向**（横屏 320x240），不是面板出厂方向。 */
#define LCD_WIDTH     320
#define LCD_HEIGHT    240

/* ---------- GRAM 起始偏移 ----------
   个别模组的可视区在 GRAM 里不从 (0,0) 开始（常见于 ST7735 类，1~2 像素）。
   ILI9341 一般填 0；若整幅画面整体偏移、边上多出一条杂色带，再试着调这里 */
#define LCD_X_OFFSET  0
#define LCD_Y_OFFSET  0

/* ---------- 屏幕朝向（按实测标定，推导过程见 6.5 节） ----------
   本屏 GRAM 就是 320 列 x 240 行；MADCTL 保持 0x00 时实测：
       水平方向 = +X（列号越大越靠右）
       垂直方向 = -Y（行号 0 在屏幕最下面）
   于是逻辑坐标要这样落到 GRAM：GRAM_X = x、GRAM_Y = 239 - y。

   两个开关用来兜底，反了就把对应值改一下：
       LCD_SW_FLIP_Y = 1  上下翻转（本屏默认需要）
       LCD_SW_FLIP_X = 1  左右镜像 */
#define LCD_SW_FLIP_X  0
#define LCD_SW_FLIP_Y  1

/* ---------- 扫描方向：MADCTL(0x36) ----------
   bit7 MY 行反向 | bit6 MX 列反向 | bit5 MV 行列交换 | bit3 BGR(R/B 互换)
   本屏必须保持 0x00：一旦带上 MV(0x20)，可寻址列数会被换成 240，
   x 在 240~319 的像素就全部写不进 GRAM —— 这就是"右侧 80 列丢失"的真因。
   若红蓝颠倒，改成 0x08 */
#define LCD_MADCTL     0x00

/* ---------- 上电自检画面 ----------
   1 = 开机先显示 3 秒测试图（白框 + 四角编号 + 16 级彩条），
       用来看方向、镜像、以及有没有哪块区域没刷到；调好后改 0 */
#define LCD_SELFTEST  1

/* ---------- RGB565 颜色 ---------- */
#define RGB565(r, g, b)  ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))
#define WHITE   0xFFFF
#define BLACK   0x0000
#define RED     0xF800
#define GREEN   0x07E0
#define BLUE    0x001F
#define YELLOW  0xFFE0
#define GREY    0xC618

/* ---------- 配色约定：白底黑字 ---------- */
#define LCD_BG_COLOR   WHITE
#define LCD_FG_COLOR   BLACK

/* ---------- 字库：8x16 点阵，ASCII 0x20~0x7E 共 95 个字符 ----------
   数据在 font_asc2_1608.c 里，每字符 16 字节，一字节一行，MSB 在左。
   这里只是 extern 声明，**该 .c 文件必须加入工程**，否则链接报 undefined
   （本工程最初就漏了这个文件，编译能过、链接一定失败，见 6.3 节） */
extern const uint8_t asc2_1608[95][16];

/* ---------- 背光：PD2 高电平点亮 ---------- */
#define LCD_BL_ON()    HAL_GPIO_WritePin(GPIOD, GPIO_PIN_2, GPIO_PIN_SET)
#define LCD_BL_OFF()   HAL_GPIO_WritePin(GPIOD, GPIO_PIN_2, GPIO_PIN_RESET)

/* ---------- 对外接口 ---------- */
void LCD_Init(void);
void LCD_OpenWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h);
void LCD_SetCursor(uint16_t x, uint16_t y);
void LCD_DrawPoint(uint16_t x, uint16_t y, uint16_t color);
void LCD_Fill(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color);
void LCD_Clear(uint16_t color);
void LCD_ShowChar(uint16_t x, uint16_t y, char ch, uint16_t color, uint16_t bgcolor);
void LCD_ShowString(uint16_t x, uint16_t y, uint16_t maxW,
                    uint16_t color, uint16_t bgcolor, const char *str);
void LCD_SelfTest(void);

#endif
```

列表 4: 代码清单 6-2 ILI9341 初始化与基本绘图（bsp_lcd.c）

```c
#include "bsp_lcd.h"

/**
  * @brief  厂商专用初始化表：一条命令 + 若干个参数
  * @note   ILI9341 与大多数 8080 控制器一样，除标准 MIPI DCS 命令外还有一段
  *         "电源/伽马/时序"私有寄存器（0xCB/0xCF/0xE8/0xEA/0xED/0xF7/0xC0/
  *         0xC1/0xC5/0xC7/0xB1/0xB6/0xE0/0xE1…），必须以屏厂随屏资料为准。
  *         这里用"命令 + 参数数组"的表结构描述它，好处是新增/删除条目时
  *         不必改动任何逻辑代码。
  *         下面这组数值是 2.8 寸 240×320 模块上最通行的通用初始化值（多数
  *         模块直接用就能正常显示）；若你的模块颜色/对比度明显不对，就换成
  *         屏厂给的序列，只改这张表即可。
  */
typedef struct {
  uint16_t cmd;
  uint8_t  nArgs;
  uint16_t args[16];   /* 伽马表最长 15 个参数 —— 写 10 会直接编译报错 */
} lcd_cmd_t;

static const lcd_cmd_t lcd_vendor_init[] = {
  /* 通电时序、泵压与驱动能力 */
  {0xCB, 5, {0x39, 0x2C, 0x00, 0x34, 0x02}},   /* Power Control A */
  {0xCF, 3, {0x00, 0xC1, 0x30}},               /* Power Control B */
  {0xE8, 3, {0x85, 0x00, 0x78}},               /* Driver Timing Control A */
  {0xEA, 2, {0x00, 0x00}},                     /* Driver Timing Control B */
  {0xED, 4, {0x64, 0x03, 0x12, 0x81}},         /* Power On Sequence Control */
  {0xF7, 1, {0x20}},                           /* Pump Ratio Control */
  {0xC0, 1, {0x23}},                           /* Power Control 1（GVDD 电平） */
  {0xC1, 1, {0x10}},                           /* Power Control 2 */
  {0xC5, 2, {0x3E, 0x28}},                     /* VCOM Control 1 */
  {0xC7, 1, {0x86}},                           /* VCOM Control 2 */

  /* 刷新率与显示功能 */
  {0xB1, 2, {0x00, 0x18}},                     /* Frame Rate ≈ 79Hz */
  {0xB6, 3, {0x08, 0x82, 0x27}},               /* Display Function Control：320 行 */

  /* 伽马校正（模块个体差异最大的部分，颜色发白/发暗先改这里） */
  {0xF2, 1, {0x00}},                           /* 3Gamma 关闭 */
  {0x26, 1, {0x01}},                           /* Gamma Set */
  {0xE0, 15, {0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08, 0x4E, 0xF1,
              0x37, 0x07, 0x10, 0x03, 0x0E, 0x09, 0x00}},   /* Positive Gamma */
  {0xE1, 15, {0x00, 0x0E, 0x14, 0x03, 0x11, 0x07, 0x31, 0xC1,
              0x48, 0x08, 0x0F, 0x0C, 0x31, 0x36, 0x0F}},   /* Negative Gamma */
};

/* 按表依次发送命令及其参数 */
static void LCD_WriteCmdList(const lcd_cmd_t *list, uint16_t count)
{
  uint16_t i;
  uint8_t  j;

  for (i = 0; i < count; i++)
  {
    LCD_WRITE_CMD(list[i].cmd);
    for (j = 0; j < list[i].nArgs; j++)
    {
      LCD_WRITE_DATA(list[i].args[j]);
    }
  }
}

/**
  * @brief  ILI9341 寄存器初始化：厂商序列 + 标准 DCS 命令
  * @note   标准命令（0x3A/0x36/0x11/0x29）由 MIPI DCS 规范定义，各家屏通用；
  *         厂商序列只影响电源与画质，即使暂时没有屏厂资料，靠这几条标准命令
  *         也能点亮出基本画面
  */
static void LCD_REG_Config(void)
{
  LCD_WRITE_CMD(0x01);                          /* 软件复位 */
  HAL_Delay(120);                               /* 手册要求复位后等待 */

  LCD_WriteCmdList(lcd_vendor_init,
                   sizeof(lcd_vendor_init) / sizeof(lcd_vendor_init[0]));

  LCD_WRITE_CMD(0x3A);  LCD_WRITE_DATA(0x55);   /* 像素格式 = RGB565（16bit/pixel） */
  LCD_WRITE_CMD(0x11);                          /* Sleep Out */
  HAL_Delay(120);                               /* 手册要求 120ms 才允许发后续命令 */

  /* 0x36(MADCTL) 放在 Sleep Out 之后：ST7789 / GC9306 这类控制器在睡眠状态下
     会直接忽略 MADCTL。本屏取 0x00（原因见 6.5 节，千万别加 MV 位） */
  LCD_WRITE_CMD(0x36);  LCD_WRITE_DATA(LCD_MADCTL);
  HAL_Delay(10);

  LCD_WRITE_CMD(0x29);                          /* Display ON */
}

/**
  * @brief  LCD 总初始化：关背光 → 复位等待 → 寄存器配置 → 清屏 → 开背光
  * @note   调用前必须已完成 MX_FSMC_Init() 与 MX_GPIO_Init()
  */
void LCD_Init(void)
{
  LCD_BL_OFF();            /* 先关背光，避免初始化期间看到乱码/闪白 */
  HAL_Delay(20);           /* RST 接 SYS_RSTA 时屏幕随系统复位已复位；
                              若另接普通 GPIO，请在此处输出 10ms 低电平再拉高 */
  LCD_REG_Config();
  LCD_Clear(LCD_BG_COLOR); /* 清成约定背景色，后续 main.c 不必再清屏 */
  LCD_BL_ON();
}

/**
  * @brief  开显示窗口：设置 GRAM 写入的坐标范围（命令 0x2A / 0x2B）
  * @note   开窗后连续写像素，ILI9341 内部地址自动递增；越界参数直接丢弃，
  *         避免 w-1 / h-1 下溢成 0xFFFF 把坐标写成天文数字
  */
void LCD_OpenWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
  uint16_t x2, y2;

  if (w == 0 || h == 0) return;
  if (x >= LCD_WIDTH || y >= LCD_HEIGHT) return;

  /* 裁掉超出屏幕的部分，保证窗口合法 */
  if ((uint32_t)x + w > LCD_WIDTH)  w = LCD_WIDTH  - x;
  if ((uint32_t)y + h > LCD_HEIGHT) h = LCD_HEIGHT - y;

  /* 逻辑坐标 → GRAM 坐标（本屏水平 +X、垂直 -Y，见 6.5 节）
     翻转时窗口起点要换成"另一端"，否则填出来的块会整体跑偏 */
#if LCD_SW_FLIP_X
  x = (uint16_t)((LCD_WIDTH - 1) - (x + w - 1));
#endif
#if LCD_SW_FLIP_Y
  y = (uint16_t)((LCD_HEIGHT - 1) - (y + h - 1));
#endif

  x  = (uint16_t)(x + LCD_X_OFFSET);
  y  = (uint16_t)(y + LCD_Y_OFFSET);

  x2 = (uint16_t)(x + w - 1);
  y2 = (uint16_t)(y + h - 1);

  LCD_WRITE_CMD(0x2A);                     /* X 坐标范围 */
  LCD_WRITE_DATA(x  >> 8); LCD_WRITE_DATA(x  & 0xFF);
  LCD_WRITE_DATA(x2 >> 8); LCD_WRITE_DATA(x2 & 0xFF);

  LCD_WRITE_CMD(0x2B);                     /* Y 坐标范围 */
  LCD_WRITE_DATA(y  >> 8); LCD_WRITE_DATA(y  & 0xFF);
  LCD_WRITE_DATA(y2 >> 8); LCD_WRITE_DATA(y2 & 0xFF);
}

/**
  * @brief  把"待写入点"定位到 (x,y)：只开 1×1 的窗口，不发 0x2C
  * @note   调用后需自行发送 LCD_WRITE_CMD(0x2C) 再写数据
  */
void LCD_SetCursor(uint16_t x, uint16_t y)
{
  LCD_OpenWindow(x, y, 1, 1);
}

/**
  * @brief  在窗口内填充单一颜色
  * @note   一次开窗 + 连续写像素，是最高效的填充方式
  */
void LCD_Fill(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color)
{
  uint32_t total;

  if (w == 0 || h == 0) return;
  if (x >= LCD_WIDTH || y >= LCD_HEIGHT) return;
  if ((uint32_t)x + w > LCD_WIDTH)  w = LCD_WIDTH  - x;
  if ((uint32_t)y + h > LCD_HEIGHT) h = LCD_HEIGHT - y;

  total = (uint32_t)w * h;

  LCD_OpenWindow(x, y, w, h);
  LCD_WRITE_CMD(0x2C);                 /* Memory Write：之后的数据进 GRAM */
  while (total--)
  {
    LCD_WRITE_DATA(color);
  }
}

void LCD_Clear(uint16_t color)
{
  uint16_t y;

  /* 分段填充：一次连写 76800 个像素对时序裕量小的模组不够稳，
     切成 12 段、每段重新开窗，单段只有 6400 个像素，可靠得多。
     代价只是多 11 次开窗（132 次总线写），相对 76800 次像素写可忽略 */
  for (y = 0; y < LCD_HEIGHT; y = (uint16_t)(y + 20))
  {
    uint16_t h = (uint16_t)(((LCD_HEIGHT - y) > 20) ? 20 : (LCD_HEIGHT - y));

    LCD_Fill(0, y, LCD_WIDTH, h, color);
  }
}

/**
  * @brief  画一个点
  * @note   每次调用都要重发 0x2A/0x2B/0x2C 共 13 次总线写，
  *         是"像素成本"的 13 倍。只有零星画点才用它，
  *         成片绘图请用 LCD_Fill 或按字符/图像开窗
  */
void LCD_DrawPoint(uint16_t x, uint16_t y, uint16_t color)
{
  if (x >= LCD_WIDTH || y >= LCD_HEIGHT) return;

  LCD_SetCursor(x, y);
  LCD_WRITE_CMD(0x2C);
  LCD_WRITE_DATA(color);
}

/**
  * @brief  显示一个 ASCII 字符（8×16 点阵）
  * @note   按"整字符开一次 8×16 窗口"的方式写，而不是逐像素 LCD_DrawPoint——
  *         这样 128 个像素只花 1 次开窗（12 次写）+ 1 次 0x2C + 128 次数据写，
  *         而逐点方式要 128 次开窗，开销差 13 倍
  */
void LCD_ShowChar(uint16_t x, uint16_t y, char ch, uint16_t color, uint16_t bgcolor)
{
  const uint8_t *font;
  uint8_t  row, bit;
  uint8_t  data;

  if (ch < ' ' || ch > '~') ch = ' ';      /* 不可显示的字符统一打成空格 */
  if ((uint32_t)x + 8 > LCD_WIDTH || (uint32_t)y + 16 > LCD_HEIGHT) return;

  font = asc2_1608[(uint8_t)ch - 0x20];

  LCD_OpenWindow(x, y, 8, 16);
  LCD_WRITE_CMD(0x2C);

  /* 窗口第一个地址落在哪一端，决定了字模该从哪一行/哪一列开始送：
       Y 反向时，窗口起点是字符的最底行 → 从 font[15] 往上送
       X 反向时，窗口起点是字符的最右列 → 从 bit0 往 bit7 送
     漏改这一处，字符就会上下颠倒（画面其他部分却是正的） */
  for (row = 0; row < 16; row++)
  {
#if LCD_SW_FLIP_Y
    data = font[15 - row];
#else
    data = font[row];
#endif

    for (bit = 0; bit < 8; bit++)
    {
#if LCD_SW_FLIP_X
      LCD_WRITE_DATA((data & (0x01 << bit)) ? color : bgcolor);
#else
      LCD_WRITE_DATA((data & (0x80 >> bit)) ? color : bgcolor);
#endif
    }
  }
}

/**
  * @brief  显示字符串（遇 '\0' 结束；超过 maxW 宽度自动截断）
  * @param  maxW: 本行允许占用的最大宽度（像素），必须是 8 的整数倍才不出现半个字符
  */
void LCD_ShowString(uint16_t x, uint16_t y, uint16_t maxW,
                    uint16_t color, uint16_t bgcolor, const char *str)
{
  uint16_t chars = maxW / 8;

  while (chars-- && *str != '\0')
  {
    LCD_ShowChar(x, y, *str, color, bgcolor);
    x += 8;
    str++;
  }
}

/**
  * @brief  上电自检画面：一眼看出方向对不对、有没有镜像、有没有没刷到的区域
  * @note   正着看应该是：四条白边闭合、左上 1(红) 右上 2(绿) 左下 3(蓝) 右下 4(黄)、
  *         16 条彩条从左到右铺满整宽。
  *         1 和 2 对调 → 左右镜像，改 LCD_SW_FLIP_X
  *         1 和 3 对调 → 上下颠倒，改 LCD_SW_FLIP_Y
  *         白框某条边缺一段/那块是雪花 → 该区域根本没被寻址到（查 MADCTL 的 MV）
  */
void LCD_SelfTest(void)
{
  static const uint16_t bars[8] = {
    RED, GREEN, BLUE, YELLOW, 0x07FF, 0xF81F, WHITE, 0x8410
  };
  uint16_t i, x;

  LCD_Clear(BLACK);

  /* 1. 四边白框（四条边都在，才说明整个可视区都被寻址到了） */
  LCD_Fill(0, 0, LCD_WIDTH, 1, WHITE);
  LCD_Fill(0, (uint16_t)(LCD_HEIGHT - 1), LCD_WIDTH, 1, WHITE);
  LCD_Fill(0, 0, 1, LCD_HEIGHT, WHITE);
  LCD_Fill((uint16_t)(LCD_WIDTH - 1), 0, 1, LCD_HEIGHT, WHITE);

  /* 2. 顶部每 40 像素一个刻度，画面被拉伸/压缩会立刻看出来 */
  for (x = 40; x < LCD_WIDTH; x = (uint16_t)(x + 40))
  {
    LCD_Fill(x, 1, 1, 5, WHITE);
  }

  /* 3. 中间 16 条彩条，铺满整个宽度 */
  for (i = 0; i < 16; i++)
  {
    LCD_Fill((uint16_t)(i * 20), 70, 20, 80, bars[i & 0x07]);
  }

  /* 4. 四角编号 */
  LCD_Fill(8, 10, 40, 22, RED);
  LCD_ShowString(24, 13, 40, WHITE, RED, "1");
  LCD_Fill((uint16_t)(LCD_WIDTH - 48), 10, 40, 22, GREEN);
  LCD_ShowString((uint16_t)(LCD_WIDTH - 32), 13, 40, WHITE, GREEN, "2");
  LCD_Fill(8, (uint16_t)(LCD_HEIGHT - 32), 40, 22, BLUE);
  LCD_ShowString(24, (uint16_t)(LCD_HEIGHT - 29), 40, WHITE, BLUE, "3");
  LCD_Fill((uint16_t)(LCD_WIDTH - 48), (uint16_t)(LCD_HEIGHT - 32), 40, 22, YELLOW);
  LCD_ShowString((uint16_t)(LCD_WIDTH - 32), (uint16_t)(LCD_HEIGHT - 29),
                 40, BLACK, YELLOW, "4");

  /* 5. 一行文字，顺便确认字库与取模顺序 */
  LCD_ShowString(96, 170, 128, WHITE, BLACK, "SELFTEST 320X240");
}
```

**要点分析**：

- `LCD_WRITE_DATA()` 一行 C 代码背后就是一次完整的 FSMC 写周期（NE1 拉低、A17=1、NWE 脉冲，ADDSET=5 / DATAST=15 下约 131ns），**命令与数据的区别完全由地址决定**，代码里看不到任何电平操作；
- **开窗是一次"贵"操作**（12 次总线写），所以驱动设计的核心原则是"**尽量少开窗、每次多写**"：`LCD_Fill()` 一次开窗写几万个像素；`LCD_ShowChar()` 按字符开窗；只有 `LCD_DrawPoint()` 这种零星场合才"一点一开窗"，它比批量写慢约 13 倍——用它画整屏会明显卡顿；
- `LCD_Fill()` 整屏 320×240 = 76800 个像素 × 131ns ≈ **10ms**，且全程占用 CPU——这正是第 8 章引入 DMA 的动机；
- 字库是**唯一的外部数据依赖**：`asc2_1608` 在头文件里只是 `extern` 声明，真正的定义在 `font_asc2_1608.c`（见 6.3 节，本笔记同目录已提供完整文件）。它是 `const` 常量数组，编译后直接落在 Flash 里，不占 RAM；
- 全部显示函数都做了边界裁剪，传错坐标时最多"不显示"，不会把 GRAM 写成乱码。

### 6.3 字库文件 font_asc2_1608.c（asc2_1608 的定义）

先澄清一个容易误解的地方：**`asc2_1608` 里的"1608"与 LCD 型号、屏幕分辨率没有任何关系**，它是点阵字库的命名法——`asc2` = ASCII 字符集，`16` = 字高 16 像素，`08` = 字宽 8 像素，所以 `asc2_1608` 就是"**8×16 的 ASCII 点阵字库**"。同系列还有 `asc2_0806`（6×8）、`asc2_1206`（6×12）、`asc2_2412`（12×24）、`asc2_3216`（16×32）等，数字大的字更大、一屏能放的字更少。而 **LCD1602 / LCD1608 那类是"字符型液晶模块"**（只能显示内部固化的字符，厂商才用 `LCD+型号` 命名），与本笔记这种"图形 TFT + 点阵字库自己取模"完全是两码事。

`LCD_ShowChar()` 里的 `asc2_1608` 是一个 95×16 = 1520 字节的常量数组，**定义在单独的文件里**——这是工程上的通行做法（字库属于"素材数据"，跟驱动逻辑分开维护）。本笔记同目录已提供生成好的 `font_asc2_1608.c`，直接加入工程即可编译。

> **字号与本屏的匹配**：320（宽）× 240 的横屏下，8×16 字库一行能排 40 个字符、一屏能排 14 行，对 2.8 寸屏来说字偏小但清晰；如果觉得太小，可以换 12×24 字库（同系列 `asc2_2412`，一行 26 个字符）。换字号要同步改两处：`LCD_ShowChar()` 的开窗尺寸（8,16 → 12,24）与取模读取方式（12 位宽时每行要读 2 个字节），另外布局常量 `ROW_W`、行距也要跟着调大。本笔记按 8×16 讲解。

**① 数据格式**（必须与驱动代码的取模顺序一一对应，否则会显示成乱码/镜像/反白）：

**表 6-1 asc2_1608 的字模格式**

| 项目 | 取值 | 在 `LCD_ShowChar()` 中的对应 |
| --- | --- | --- |
| 点阵大小 | 8（宽）× 16（高） | `LCD_OpenWindow(x, y, 8, 16)` |
| 每字符字节数 | 固定 16 字节 | `font[row]`，row = 0~15 |
| 取模方向 | 逐行式（一个字节 = 一整行） | 外层循环 `row`、内层循环 `bit` |
| 位序 | MSB 在左（bit7 = 该行最左像素） | `data & (0x80 >> bit)` |
| 颜色极性 | 阴码：1 = 笔画点亮 | `? color : bgcolor` |

**② 三种获取（替换）方式**，任选其一，格式对就行：

1. **直接用本笔记提供的** `font_asc2_1608.c`（**与本工程源码逐字节一致**：用 Windows 宋体在 8×16 像素框内逐字符渲染、二值化后逐行取模得到；笔画 1 像素，2.8 寸屏上偏清秀但不断线，实测比常见的加粗 VGA 点阵更适合这个小尺寸）；
2. **拷屏厂/教程附带的字库**：正点原子、野火等教程的 `font.h` 里都有 ASCII 8×16 字库，注意核对它的格式是否为"逐行式 + MSB 在左 + 阴码"，不一致就要改 `LCD_ShowChar()` 的两行取模代码，或者自己转换；
3. **用 PCtoLCD2002 自行生成**：模式选"字符模式"，设置"**阴码、逐行式、顺向（高位在前）、十六进制、C51 格式**"，字宽×字高填 8×16，取模范围勾 ASCII（0x20~0x7E），导出后把数组名改成 `asc2_1608`、下标改成 `[95][16]` 即可。

**③ 自检方法**（比逐字节核对快得多）：只保留 `'A'` 一行数据，其余全填 `0x00`，编译下载后屏幕上应出现一个端正的 `A`；如果出现的是上下颠倒、左右镜像或"笔画是背景色"的反白字，就依次对应"逐行式配成了逐列式""顺向配成了逆向""阴码配成了阳码"三种取模设置不符。

列表 5: 代码清单 6-3 字库文件 font_asc2_1608.c（节选，完整文件 95 个字符在本笔记目录下）

```c
/* font_asc2_1608.c —— 8×16 ASCII 点阵字库（0x20 ~ 0x7E，共 95 个字符）
 *
 * 数据格式（与 lcd.c 中 LCD_ShowChar() 的取模顺序严格对应）：
 *   ① 每个字符固定 16 字节，自上而下每字节对应一行；
 *   ② 每字节的 bit7(MSB) 是该行最左侧像素，bit0 是最右侧像素；
 *   ③ 数据位为 1 表示"笔画点亮"（显示前景色），0 表示背景（显示背景色）。
 *   这三点合起来就是取模软件里的"阴码、逐行式、顺向、十六进制"设置。
 *
 * 数据来源：用 Windows 宋体（SimSun）在 8×16 像素框内逐字符渲染，再按阈值
 *   二值化、逐行取模得到，取模设置等价于 PCtoLCD2002 的"阴码 / 逐行式 /
 *   顺向 / 十六进制"。字形基线在第 13 行、笔画 1 像素。也可以整体替换成
 *   屏厂/教程附带的同格式字库，或用 PCtoLCD2002 按上述设置重新生成，
 *   驱动代码无需改动。
 */

#include <stdint.h>

const uint8_t asc2_1608[95][16] = {
  { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 },  /* 0x20  'space' */
  ...
  { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x60, 0x60, 0x00, 0x00 },  /* 0x2E  '.' */
  { 0x00, 0x00, 0x00, 0x18, 0x24, 0x42, 0x42, 0x42, 0x42, 0x42, 0x42, 0x42, 0x24, 0x18, 0x00, 0x00 },  /* 0x30  '0' */
  { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00 },  /* 0x3A  ':' */
  { 0x00, 0x00, 0x00, 0x10, 0x10, 0x18, 0x28, 0x28, 0x24, 0x3C, 0x44, 0x42, 0x42, 0xE7, 0x00, 0x00 },  /* 0x41  'A' */
  ...
  { 0x20, 0x5A, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 },  /* 0x7E  '~' */
};
```

> 以 `'A'` 为例核对一遍数据与屏幕的对应关系：第 3 行 `0x10 = 0001 0000`，按 `0x80 >> bit` 逐位判断只有从左数第 4 个像素亮，正是 A 的尖顶；第 9 行 `0x3C = 0011 1100` 连续 4 个像素，是 A 的横杠；第 13 行 `0xE7 = 1110 0111` 左右各 3 个像素、中间空，是 A 的两条腿。**能这样对着数据读出字形，就说明格式理解到位了。**

### 6.4 换分辨率 / 换控制器时要改什么

本笔记按 **ILI9341 + 240×320（横屏 320×240）** 编写。将来换屏（比如换成 3.5 寸 320×480、4.3 寸 480×272、或者换成 ILI9325/R61581 等驱动器）时，一张表说清改动范围：

**表 6-2 换屏改动清单**

| 项目 | 本笔记取值 | 换屏/换分辨率时怎么改 |
| --- | --- | --- |
| `LCD_WIDTH` / `LCD_HEIGHT` | 320 × 240 | **必须按屏改**。它同时是开窗裁剪的边界，写大了会出现"右侧一条错位花带"，写小了会出现"右下角显示不全" |
| GRAM 的真实尺寸 | 320 列 × 240 行（6.5 节实测） | 换屏先用自检图确认"列、行各是多少"，**别照抄屏参**——填错的表现是角标两两重叠或整块不出现 |
| MADCTL（0x36） | `0x00`（不带 MV、不带 BGR） | **绝不能带 MV（0x20）**：MV 会把可寻址列数从 320 变成 240，x ≥ 240 的像素直接丢弃——本工程第一条"尾部花屏"就是这么来的；**红蓝互换**时才加 0x08 |
| 画面方向 | `LCD_SW_FLIP_X = 0`、`LCD_SW_FLIP_Y = 1` | 换屏后按 6.5.3 节用两轮标定，**不要猜 MADCTL 的 8 个值**；翻转让开窗起点跑到另一端，字符送数顺序要跟着反（见 6.5.4 节） |
| 厂商初始化序列 | 表驱动 16 条（代码清单 6-2） | **换控制器时唯一必须重写的大块**：把新控制器手册/屏厂资料里的电源、伽马、时序寄存器照抄成表的一行 |
| 标准 DCS 命令 | 0x01 / 0x11 / 0x29 / 0x3A=0x55 / 0x2A / 0x2B / 0x2C | 各家通用（0x2A/0x2B 是列/页地址设置、0x2C 是写 GRAM），**基本不用改** |
| FSMC 时序 | ADDSET = 5、DATAST = 15（twc ≈ 131ns） | 换控制器要查它的 tWC/tDST 要求，查不到就先用这组保守值。**注意：边界整齐、位置固定的花带不是时序问题**（那是 MV 位，见 6.5 节），时序不足造成的花屏是随机彩点 |
| 数据总线宽度 | 16 位 | 若模块是 8080-**8 位**版，要改 FSMC 的 `MemoryDataWidth`，并把每个像素拆成高低两字节写 |
| 字库与布局 | `asc2_1608`（8×16），行宽 304 像素 | 分辨率变了要重算行宽/行距（见 6.3 节字号、7.7 节版面常量）；字太小就换 12×24 字库（`asc2_2412`） |

> **为什么改动范围这么小？** 因为 8080 协议、FSMC 地址映射、驱动分层这三件事与"屏多大、用哪颗控制器"无关：**换屏只动 `LCD.h` / `lcd.c` 的时序与初始化表、方向开关、以及 `LCD_WIDTH/HEIGHT` 两个宏；第 7 章的传感器采集链路一行都不用改**——这正是分层设计的回报。

### 6.5 屏幕方向标定——本工程最花时间的一个坑

这一节值得单独写：**"画面方向不对"看起来是个 5 分钟的小问题，实际上它能让驱动层反复返工三次**。原因是几乎没人讲清楚一件事——**MADCTL（0x36）不只是"转屏开关"，它会改变可寻址的地址范围**。

#### 6.5.1 三次失败的试验记录

本工程的目标是"面板横放、画面 320×240 正立"。按常规做法改 MADCTL，得到的结果依次是：

**试验 1**：`MADCTL = 0x20`（MV，即"行列交换"），逻辑坐标直通（GRAM_X = x、GRAM_Y = y）

| 观察到的现象 | 推论 |
| --- | --- |
| 画面整体转了 90° | 逻辑 x 走到了垂直方向、逻辑 y 走到了水平方向 |
| **x = 272~311 的两个角标完全不显示** | **x ≥ 240 的像素根本没写进 GRAM** |
| y = 208 的角标只走到约 2/3 宽的位置 | 水平方向只用了 240/320 的行程 |

**试验 2**：`MADCTL = 0x00` + 软件 90° 旋转（GRAM_X = 239 − y、GRAM_Y = x）

| 观察到的现象 | 推论 |
| --- | --- |
| 上下两个角标"重叠"成一对 | 送入的 GRAM_Y = 272~311 与 8~47 落到了同一处 |
| 两对分别在屏幕左右两侧 | 水平方向就是 GRAM_X 正向 |

→ **GRAM_Y 只有 240 个地址**，超出部分被控制器钳位。于是确定：**GRAM 是 320 列 × 240 行**，`LCD_WIDTH/LCD_HEIGHT` 从头到尾都是对的。

**试验 3**：`MADCTL = 0x00`，`GRAM_X = x`、`GRAM_Y = 239 − y` → **画面正立，全部正常。**

#### 6.5.2 从三次现象反推出的两个结论

**结论一：MV 位会缩小 x 方向的可寻址范围，这是"右侧花屏/丢列"的真因。**

本屏 GRAM 是 240 列 × 320 行（面板横放后，GRAM 的**列**走屏幕垂直方向、**行**走水平方向）。开 MV 之后，控制器把行列语义对调，但**能装 320 个像素的存储体并没有因此变多**——按 320 写 x，超出 240 的部分全部丢弃。

这就解释了一个极易误判的现象：**"屏幕右边（或尾部）有一条不显示 / 是雪花"**。绝大多数资料会告诉你这是"FSMC 时序太快、数据没锁存住"，于是不停地加大 DATAST——**方向完全错了**。真正的判据是：**丢失的区域边界整齐、每次都恰好是同一片**（时序问题的花屏是随机的、彩色的、边界模糊的）。

**结论二：这块屏在 `MADCTL = 0x00` 下的真实坐标方向是**

```
水平方向 = +X   （GRAM 列号越大越靠右）
垂直方向 = -Y   （GRAM 行号 0 在屏幕最下面）
```

所以逻辑坐标必须这样落到 GRAM：

```c
GRAM_X = x
GRAM_Y = 239 - y
```

#### 6.5.3 如何在 5 分钟内标定一块新屏

不要靠猜 MADCTL 的 8 个值，用"**喂已知坐标、看落点**"的方法，两轮就能定死。前提是先有自检图（`LCD_SelfTest()`，见代码清单 6-2）：四个角分别是 1 红（左上）、2 绿（右上）、3 蓝（左下）、4 黄（右下）。

**第 1 轮：先定 GRAM 尺寸，再定方向。** 把 `LCD_SW_FLIP_X/Y` 都置 0、`LCD_MADCTL = 0x00`，也就是"逻辑坐标原样送进 GRAM"，然后看：

| 你看到的 | 说明 | 下一步 |
| --- | --- | --- |
| 4 个角标都在，但整体转了 90° | GRAM 的行列与屏幕方向交叉 | 需要软件旋转，不是翻转能解决的 |
| 4 个角标都在，只是镜像/颠倒 | 方向差 180° 或镜像 | 只用 `FLIP_X` / `FLIP_Y` 就能修 |
| **有的角标不见了 / 两两重叠** | **x 或 y 超出了 GRAM 范围** | 说明另一个方向才是长边，先把 GRAM 尺寸定下来 |

**第 2 轮：按落点定符号。** 假设已确认"水平 = GRAM_X、垂直 = GRAM_Y"（不交叉），那么：

| 现象 | 改法 |
| --- | --- |
| 1 跑到左下、3 跑到左上（上下颠倒） | `LCD_SW_FLIP_Y = 1` |
| 1 跑到右上、2 跑到左上（左右镜像） | `LCD_SW_FLIP_X = 1` |
| 1 跑到右下（既翻转又镜像） | 两个都置 1 |

#### 6.5.4 为什么用软件翻转，而不是 MADCTL 的 MY/MX 位

理论上 `0x80`（MY）就能翻转垂直方向。本工程仍然选择在 `LCD_OpenWindow()` 里做两次减法，理由有三条：

1. **可控**：这颗屏的 MADCTL 实测行为与"手册语义"对不上（MV 会让 320 列变 240 列，这一点手册里没有明确写），**它的 8 个值里到底哪个等价于"垂直翻转"是不可预测的**；软件翻转则是确定的两次减法；
2. **可读**：`LCD.h` 里两个 `#define` 就把方向说清楚了，换人接手不用去查 MADCTL 的位定义；
3. **零成本**：翻转只发生在开窗时（每个 `LCD_Fill` / `LCD_ShowChar` 一次），不是每像素一次，编译后就是几条 SUB 指令。

> **但要连带改一处**：翻转之后，窗口的第一个地址落在了"另一端"，字符点阵的送数顺序必须跟着反。`LCD_ShowChar()` 里 `font[15 - row]`（Y 反向时从字符底行往上送）和 `bit` 的正反向就是这个原因。**漏改这一处，画面上别的都是正的、只有字是倒的**——这也是最好认的一个症状。

#### 6.5.5 固化下来的配置

```c
#define LCD_MADCTL     0x00   /* 绝不能带 MV 位 */
#define LCD_SW_FLIP_X  0
#define LCD_SW_FLIP_Y  1      /* GRAM_Y = 239 - y */
```

配合 `LCD_WIDTH = 320`、`LCD_HEIGHT = 240`，所有写入都落在 0~319 列 / 0~239 行内，**不存在任何越界钳位**，重叠、丢列、花带一并消失。

> **调试顺序建议**：`LCD_Clear` 纯色 → `LCD_SelfTest()` 自检图 → 传感器界面。自检图的四角编号是"方向是否正确的唯一证据"，比"看着像歪了"靠谱得多。**自检图通过之后，再把 `LCD_SELFTEST` 改成 0 关掉。**

---

## 7. 在 LCD 上显示 IIC 传感器数据

### 7.1 整体思路

《IIC 通信》笔记中，BH1750（光照）、HTU21D（温湿度）、PCF8563（时钟）、LIS3DH（三轴）四个传感器挂在 **PA1(SCL)/PA0(SDA) 软件 I2C 总线**上。本章不重复讲解 I2C 驱动代码（直接复用该笔记第 8、9 章的 `bsp_soft_i2c.c`、`bsp_sensor_io.c` 及各器件驱动），只讲**数据如何流到屏幕上**：

```
传感器 ──软件I2C──> 器件驱动 Read 函数 ──> 全局数据缓存 ──> 格式化字符串 ──> LCD 字符显示函数 ──> FSMC 写 GRAM
```

复用的器件层接口（与《IIC 通信》笔记 9.2.3 节完全一致，本笔记不再改动）：

**表 7-1 从 IIC 笔记复用的器件层接口**

| 器件 | 头文件 | 初始化 | 读取 | 返回值的坑 |
| --- | --- | --- | --- | --- |
| BH1750 光照 | `bsp_bh1750.h` | `void BH1750_Init(void)` | `float BH1750_ReadLux(void)` | 读取失败返回 **-1.0** |
| HTU21D 温湿度 | `bsp_htu21d.h` | `void HTU21D_Init(void)` | `float HTU21D_ReadTemp(void)` / `HTU21D_ReadHumidity(void)` | 同上 |
| PCF8563 时钟 | `bsp_pcf8563.h` | —（无需初始化） | `void PCF8563_ReadTime(PCF8563_Time_t *)` | 时间是否可信要调 `uint8_t PCF8563_IsTimeValid(void)`：**返回 1 = 可信，0 = 曾掉电**；返回 0 时用 `void PCF8563_WriteTime(const PCF8563_Time_t *)` 重新设定 |
| LIS3DH 三轴 | `bsp_lis3dh.h` | `uint8_t LIS3DH_Init(void)` | `void LIS3DH_ReadAcc(short *acc)` | Init 读到 WHO_AM_I = **0x33** 才返回 **1**，返回 **0** 表示器件不在线 |

> **这些函数定义在哪？——不在本笔记里，也不用重写。** 上表四个器件层属于《IIC 通信》笔记第 9 章（该笔记代码清单 9-2 ~ 9-5），源码分别在 `bsp_bh1750.c`、`bsp_htu21d.c`、`bsp_pcf8563.c`、`bsp_lis3dh.c` 及其同名头文件中，`LIS3DH_Init()`、`PCF8563_IsTimeValid()`、`LIS3DH_ReadAcc()` 都已在那边**声明并完整实现**。
>
> 所以本笔记第 7 章的 main.c 只做两件事：`#include` 这四个头文件，然后调用——**应用层不重复声明也不重复实现驱动层**。看到 `LIS3DH_Init()`、`PCF8563_IsTimeValid()` 不必去本笔记里找定义，直接看《IIC 通信》笔记即可。移植时把这 6 个驱动文件（`bsp_soft_i2c`、`bsp_sensor_io`、`bsp_bh1750`、`bsp_htu21d`、`bsp_pcf8563`、`bsp_lis3dh`）与本笔记的 `bsp_lcd`、`lcd_dma`、`font_asc2_1608` 一起加入工程就能编译（字库文件的说明见 6.3 节）。

核心约定：主循环每 1 秒采集一轮传感器数据，`sprintf` 格式化后**整行重写**（先铺背景色、再画字符）到 LCD 的固定行。整行重写比"精确擦除差异位"简单得多，且天然不会残留旧字符。

### 7.2 像素、点阵与 GRAM：屏幕是怎么"记住"一帧画面的

第 1.2 节只给了一句结论："显示内容存在控制器的 GRAM 里"。这一节把它展开：一个像素到底是什么、在 GRAM 里占多少位、怎么寻址、写进去之后屏又是怎么把它变成画面的。**这三件事是后面字符定位（7.3）和版面设计（7.4）的全部依据——每一个坐标、每一个数字，最终都要落到"往哪个地址写什么值"上。**

#### 7.2.1 一个像素是什么

320×240 的屏上有 320 × 240 = **76,800 个发光单元**，每个单元就是一个**像素（pixel）**。

彩色 TFT 的每个像素并不是"一个点"，而是**三个并排的子像素**：

```
一个像素的物理结构（俯视，放大很多倍）
  ┌───────┬───────┬───────┐
  │   R   │   G   │   B   │   ← 三片红/绿/蓝滤色片
  └───────┴───────┴───────┘
      ↑       ↑       ↑
      └───────┴───────┴── 同一片背光，靠各自液晶层的透光率决定亮多少

每个子像素背后：一个薄膜晶体管(TFT)当开关 + 一个电容保持电压
```

所以"一个像素的颜色" = R、G、B 三个通道各给一个亮度值。控制器只做一件事：**按行不停地扫描，把 GRAM 里的数字变成每个子像素的电压**。于是"屏上显示什么"完全等价于"GRAM 里存了什么"——这就是为什么后面所有绘图函数，最终都会归结为"往 GRAM 的某个地址写一个 16 位数"。

#### 7.2.2 一个像素在 GRAM 里占 16 位：RGB565

本工程初始化时发了一条 `0x3A 0x55`（代码清单 6-2），含义是 **像素格式 = 16 bit/pixel**。这 16 位这样切：

**表 7-2 RGB565 的位分配**

| 位 | 15 … 11 | 10 … 5 | 4 … 0 |
| --- | --- | --- | --- |
| 通道 | R（红） | G（绿） | B（蓝） |
| 位宽 | 5 | 6 | 5 |
| 级数 | 32 级 | 64 级 | 32 级 |

32 × 64 × 32 = **65,536 色**。`LCD.h` 里的宏就是这个式子：

```c
#define RGB565(r, g, b)  ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))
```

- `(r & 0xF8) << 8`：丢掉 R 的低 3 位（8 位 → 5 位），再左移 8 位落到 bit15…11；
- `(g & 0xFC) << 3`：丢掉 G 的低 2 位（8 位 → 6 位），落到 bit10…5；
- `b >> 3`：直接取 B 的高 5 位，留在 bit4…0。

实算一次本工程标题栏的深靛蓝 `RGB565(22, 42, 74)`：

| 通道 | 原值 | 取高位 | 移位 | 贡献 |
| --- | --- | --- | --- | --- |
| R | 22 = 0x16 | 0x10 | << 8 | 0x1000 |
| G | 42 = 0x2A | 0x28 | << 3 | 0x0140 |
| B | 74 = 0x4A | 0x09 | 不移 | 0x0009 |
| 合计 | | | | **0x1149** |

**为什么是 16 位而不是 24 位？**

| 指标 | RGB565 | RGB888 |
| --- | --- | --- |
| 每像素 | 2 字节 | 3 字节 |
| 320×240 一屏 | 153,600 B ≈ **150 KB** | 230,400 B ≈ 225 KB |
| 刷一屏的总线写次数（16 位宽） | 76,800 次 | 153,600 次（每次只装 12 位有效） |
| 实际观感 | 大面积渐变处可见轻微色带 | 肉眼几乎无差别 |

在 320×240 的小屏上，面板本身的色域、视角和背光品质远差于"8 位降到 5/6/5 位"这点量化误差，省下的带宽和显存是划算的。只有画大面积平滑渐变时才看得出 5 位红的色带——本工程全是文字和色块，不受影响。

#### 7.2.3 为什么画面必须存在屏里：150 KB 放不进 128 KB 的 SRAM

这一条决定了整个驱动的架构：

**表 7-3 一屏像素的开销**

| 项目 | 计算 | 结果 |
| --- | --- | --- |
| 像素个数 | 320 × 240 | 76,800 |
| 每像素字节数 | 16 bit | 2 B |
| 一帧完整画面 | 76,800 × 2 | **153,600 B = 150 KB** |
| STM32F407VET6 的 SRAM | — | **128 KB**（还要放栈、堆、HAL 句柄、I2C 缓冲） |

也就是说，**"在 MCU 里开一块和屏幕一样大的显存、渲染好再整屏推过去"这个最直观的方案，在这颗芯片上根本放不下**。所以本工程用的是"**直接写屏**"：

- 显示内容的唯一副本在控制器的 GRAM 里（屏内部自带 150 KB 显存，由屏厂配好）；
- MCU 用 `LCD_OpenWindow()` 划出一个矩形，再用 `0x2C` 连续灌像素，**每一笔都直接落到屏的显存上**；
- MCU 端不需要任何帧缓存，因此 `LCD_Fill()` / `LCD_ShowChar()` 都是"算一个像素、写一个像素"。

代价是"没有中间帧"：所有绘制都是就地修改，于是才需要 7.7 节的"先铺底色再写字"来避免残影，也才需要第 8 章的"一行 10 KB 行缓冲"用一小块 RAM 换 DMA 刷屏。

#### 7.2.4 一次 16 位写 = 一个像素

FSMC 被配成 16 位数据宽度（第 5 章），像素格式也是 16 位，两者刚好对齐：**对 `LCD_DATA_ADDR` 的一次写，就是把一个像素的颜色塞进 GRAM 的一个格子**。

```c
LCD_WRITE_DATA(RGB565(220, 48, 48));   /* 一次总线写 → 当前地址那个像素变红 → 列地址自动 +1 */
```

顺着这个等式，每个绘图动作的"代价"可以直接算出来：

**表 7-4 常用绘制动作的总线写次数**

| 动作 | 像素数 | 16 位写次数 |
| --- | --- | --- |
| 涂一个像素 | 1 | 1 |
| 画一个 8×16 字符 | 8 × 16 = 128 | 128 |
| 写一行 38 字符的文字 | 38 × 128 | 4,864 |
| 铺一条 304 像素宽、16 像素高的行（`FillRow`） | 304 × 16 = 4,864 | 4,864 |
| 清一次整屏 | 76,800 | **76,800** |

对照第 4 章算出的写周期（约 131 ns），一次清屏 ≈ 76,800 × 131 ns ≈ **10 ms**。这个数字在第 8 章分析 CPU 占用时会反复用到——它是判断"能不能在 1 秒的刷新周期里整屏重画"的依据。

#### 7.2.5 GRAM 的寻址：CASET / RASET / RAMWR 与自动递增

GRAM 不是"一个平铺的大数组让你随便寻址"，而是**先设一个矩形窗口，再顺序灌数据**。三条命令：

| 命令 | 名称 | 作用 |
| --- | --- | --- |
| `0x2A` | CASET（Column Address Set） | 设定窗口的**列**范围 XS…XE |
| `0x2B` | RASET（Row Address Set） | 设定窗口的**行**范围 YS…YE |
| `0x2C` | RAMWR（Memory Write） | 之后的每个数据都写进窗口的"当前格"，然后**当前格自动移到下一格** |

"自动移到下一格"的方向是：**沿列方向 +1，走到窗口右端（XE）后回到下一行的左端（XS）**：

```
CASET = [2, 5]   RASET = [1, 3]        窗口是 4 列 × 3 行

          X=2    X=3    X=4    X=5
  Y=1      ①  →   ②  →   ③  →   ④
                                  ↓   （列到 XE 后回到 XS，行 +1）
  Y=2      ⑤  →   ⑥  →   ⑦  →   ⑧
                                  ↓
  Y=3      ⑨  →   ⑩  →   ⑪  →   ⑫
                                  ↓   （窗口填满，之后的写入行为各厂家不同）
```

这条规则带来两个直接后果，都是本工程实际踩过的：

1. **开窗之后只管连续灌数据，不用再算坐标**——`LCD_Fill()` 里那个 `while (total--) LCD_WRITE_DATA(color)` 完全依赖它；一个 8×16 字符灌 128 个像素，中间也不用重新开窗。这就是"开一次窗、写一大片"能比"每个像素都设一次地址"快几十倍的原因；
2. **灌的像素数必须正好等于 w × h**。窗口填满之后继续写会发生什么，各家控制器不一致（有的回卷到窗口起点，有的忽略，有的写到窗口外）。本工程从不依赖"填满之后"的行为：`LCD_Fill()` 按 `w*h` 精确计数，`LCD_ShowChar()` 固定 16 行 × 8 列 = 128 次，字符永远不会串到相邻格子上。

> **回头解释 6.5 节那次"尾部花屏"**：当时 `LCD_Clear()` 一次连写 76,800 个像素、历时约 10 ms，其间总线一刻不停。写周期裕量只有几纳秒时，越往后越容易漏掉个别像素，最终表现就是某块区域残留雪花。**把长写切成 20 行一段（单段 6,400 像素）、每段之间重发一遍开窗命令**，等于给总线留了喘息，比一味降低时钟频率有效得多。

#### 7.2.6 写入与扫描是异步的

控制器内部有一台独立的"扫描发动机"：它不管 MCU 在做什么，**以约 60 Hz 的固定频率把 GRAM 一行一行读出来，送给 source driver 变成电压**。

```
MCU 侧（随时、异步）                  控制器侧（固定 60 Hz）
写像素 ──┐                          第   1 行 ──> 面板
写像素 ──┼──> GRAM（150 KB） ──>    第   2 行 ──> 面板
写像素 ──┘                          ...
                                    第 240 行 ──> 面板      （约 16.7 ms 一轮）
```

由此可以推出三条与写代码直接相关的结论：

1. **最终画面 = 最后一次写入的结果**，与中间经历了什么无关。这正是"先铺底色、再画字符"能成立的原因：中间的半成品在 16.7 ms 内就被覆盖，人眼只看到最终态；
2. **撕裂（tearing）**：若在一帧扫描的中途改画面，屏幕会出现上半部分新、下半部分旧。刷一屏约 10 ms，与 16.7 ms 的帧周期同量级，所以整屏重画时偶尔能看到一条横线扫过。本工程每轮只改三成面积、且都是不连续的小块，实际几乎看不出来；
3. **软件翻转为什么绝对安全**：`LCD_SW_FLIP_Y` 只改变"往哪个地址写"，不改变 GRAM 的组织。控制器永远从第 0 行扫到第 239 行，谁落在第 0 行就显示谁——这与 6.5 节"用软件翻转取代 MADCTL 的 MY/MX 位"是同一件事的两面。

---

### 7.3 字符显示位置的计算原理

有了"一次写 = 一个像素""写之前先开窗"这两个前提，字符定位就变成了纯粹的算术：**一个字符占哪个矩形、下一个字符从哪里开始、一行放不下怎么办**。

#### 7.3.1 字模：16 个字节怎么变成一个字母

`font_asc2_1608.c` 里每个字符是 **16 个字节**，按"从上到下、每字节一行、高位在左"排列。以本工程字库中 `'A'` 的真实数据为例：

```c
/* 'A' 0x41 */
{0x00,0x00,0x00,0x10,0x10,0x18,0x28,0x28,0x24,0x3C,0x44,0x42,0x42,0xE7,0x00,0x00},
```

把每个字节展开成 8 个二进制位（bit7 在左、bit0 在右），`1` 画点、`0` 留空：

```
字节[ 0] 0x00 → ........       ← 第 0 行：空
字节[ 1] 0x00 → ........
字节[ 2] 0x00 → ........
字节[ 3] 0x10 → ...#....       ← 0x10 = 0001 0000，只有 bit4 是 1
字节[ 4] 0x10 → ...#....
字节[ 5] 0x18 → ...##...
字节[ 6] 0x28 → ..#.#...
字节[ 7] 0x28 → ..#.#...
字节[ 8] 0x24 → ..#..#..
字节[ 9] 0x3C → ..####..
字节[10] 0x44 → .#...#..
字节[11] 0x42 → .#....#.
字节[12] 0x42 → .#....#.
字节[13] 0xE7 → ###..###       ← 底部的两个衬线脚
字节[14] 0x00 → ........
字节[15] 0x00 → ........
```

三个可以直接量出来的事实：

- **一个字符 = 8 列 × 16 行 = 128 个像素**，字模正好 16 字节 = 128 bit，**1 bit 对应 1 个像素**，没有任何压缩或灰度；
- 16 行的字框里，真正有笔画的只有第 3…13 行，**上下各留白 2~3 行**——这是 7.3.4 节"行距取 24 而不是 16"的直接依据；
- 字模是**二值位图**：每个像素只有"画前景色"和"画背景色"两种可能。所以同一套字库不能放大缩小、不能加粗、不能抗锯齿，只能整体换一套（`asc2_2412` 之类）。这也是 7.4 节"字号层级只能靠颜色和留白来做"的根因。

95 个可打印字符 × 16 B = **1,520 字节**，比一张 40×38 的图片还小，`const` 放在 Flash 里几乎不占空间。

#### 7.3.2 画一个字符 = 开一个 8×16 的窗 + 逐行灌 128 个像素

`lcd.c` 的实现（已去掉翻转分支，只留主干）：

```c
void LCD_ShowChar(uint16_t x, uint16_t y, char ch, uint16_t color, uint16_t bgcolor)
{
  const uint8_t *font;
  uint8_t row, bit, data;

  if (ch < ' ' || ch > '~') ch = ' ';                    /* 不可显示字符 → 空格 */
  if ((uint32_t)x + 8 > LCD_WIDTH || (uint32_t)y + 16 > LCD_HEIGHT) return;   /* 出界即放弃 */

  font = asc2_1608[(uint8_t)ch - 0x20];                  /* 取该字符的 16 字节 */

  LCD_OpenWindow(x, y, 8, 16);                           /* ① 划定 8×16 的矩形 */
  LCD_WRITE_CMD(0x2C);                                   /* ② 进入连续写 */

  for (row = 0; row < 16; row++)                         /* ③ 外层：16 行 */
  {
    data = font[row];
    for (bit = 0; bit < 8; bit++)                        /* ④ 内层：一行 8 个像素 */
    {
      LCD_WRITE_DATA((data & (0x80 >> bit)) ? color : bgcolor);
    }
  }
}
```

**为什么外层必须是"行"、内层必须是"列"？** 因为 7.2.5 节的自动递增是"列 +1、到右端换行"，而字模的组织方式是"一个字节 = 一行 8 个像素"。两者对齐，才能把一个字节的 8 个位顺着写下去、写完自动落到下一行。若把循环反过来（外层列、内层行），送出的像素顺序变成"竖着一列一列"，画面就是转置的乱码——**这是自定义字库配自定义控制器时最容易错的一处**。

窗口与字符格的对应关系：

```
         x       x+7
         ┌─────────┐
    y    │         │  ← 第 0 行：font[0] 的 bit7…bit0
         │         │
         │         │     每个像素 = 一次 LCD_WRITE_DATA()
         │         │     共 16 行 × 8 列 = 128 次
         │         │
   y+15  │         │  ← 第 15 行：font[15]
         └─────────┘
```

注意函数开头那行出界检查：`x + 8 > 320` 或 `y + 16 > 240` 时**整个字符一个像素都不画**，不是画一半。所以"贴着右边缘的文字少了一个字"是设计行为，不是丢数据——真需要"半个字"就得自己按像素画，本工程的条形图就是直接用 `LCD_Fill()` 画的，不经过字符函数。

#### 7.3.3 定位公式

把这套坐标关系写成公式，就是本章所有版面常量的出处：

**表 7-5 字符定位的四个公式**

| 量 | 公式 | 说明 |
| --- | --- | --- |
| 第 i 个字符的左上角 | `x = x0 + 8 × i`，`y = y0` | 字模宽度固定 8，只需起点和序号 |
| 该字符的窗口 | `CASET = [x, x+7]`，`RASET = [y, y+15]` | 由 `LCD_OpenWindow(x, y, 8, 16)` 完成 |
| 字符串占用的像素宽 | `8 × 字符数` | 8×16 是**等宽**点阵，不像矢量字体那样宽窄不一 |
| 下一行的起点 | `y += 行距`（本工程 24） | 行距 ≠ 字高，见 7.3.4 |

`LCD_ShowString()` 就是第一式的循环：

```c
void LCD_ShowString(uint16_t x, uint16_t y, uint16_t maxW,
                    uint16_t color, uint16_t bgcolor, const char *str)
{
  uint16_t chars = maxW / 8;               /* 这一行最多能放几个字符 */

  while (chars-- && *str != '\0')
  {
    LCD_ShowChar(x, y, *str, color, bgcolor);
    x += 8;                                /* 只动 x，一行内 y 不变 */
    str++;
  }
}
```

代入本工程的实际数字，常用位置可以手算出来：

**表 7-6 本工程几个实际坐标的手算结果**

| 元素 | 起点 (x, y) | 内容 | 字符数 | 占用像素 | 结束 x |
| --- | --- | --- | --- | --- | --- |
| 标题（居中） | (104, 7) | `SENSOR MONITOR` | 14 | 112 | 216 |
| 光照数值行 | (8, 58) | `Lux :  1234.5 lx` | 16 | 128 | 136 |
| X 轴数值 | (32, 110) | `+1023` | 5 | 40 | 72 |
| 合加速度行 | (8, 182) | `\|a\| 1002 mg  P +12 R  -5` | 24 | 192 | 200 |
| 状态行左侧 | (8, 208) | `BH1750 OK  LIS3DH OK` | 20 | 160 | 168 |
| 状态行右侧 | (264, 208) | `LEVEL` | 5 | 40 | 304 |

标题的 104 是这样来的：`(320 − 14×8) / 2 = (320 − 112) / 2 = 104`。**居中的本质只有一个——把左右剩余的像素宽度除以 2**，`TextCenter()` 里那三行就是这句话的代码。

再验证一次"不重叠"：状态行左侧到 x=168 结束，右侧从 264 开始，中间留了 96 像素空白，两块区域互不干扰。这类"手工分区"的验算，是 7.4.7 检查清单里必查的一条。

#### 7.3.4 行距为什么是 24 而不是 16

字高 16，但相邻两行起点相差 **24**，多出的 8 像素是行间空白。三个理由：

```
行距 16（字框紧贴）               行距 24（本工程）
┌──────────┐ y=40                ┌──────────┐ y=40
│  ABC     │                     │  ABC     │
└──────────┘ y=56                └──────────┘
   ↑ 只空 0~1 行                       ↓ 8 像素空白
┌──────────┐ y=56                ┌──────────┐ y=64
│  DEF     │                     │  DEF     │
└──────────┘                     └──────────┘
```

1. **字框本身自带留白**：7.3.1 量过，`'A'` 只用第 3…13 行，上下各空 2~3 行。行距 16 时，上一行的下留白（2 行）+ 下一行的上留白（3 行）= 5 行间隙，勉强够；再加 8 像素后变成 13 行，约等于一个字符高，读起来才不挤；
2. **整数好算**：240 / 24 = 10，一屏正好 10 行；换成 20 或 28 就会出现"最后一行露不全"的边界问题；
3. **与 `LCD_Clear()` 的分段对齐**：第 6 章的清屏按 20 行一段切分，24 的行距让段边界大概率落在行间空白里，视觉上不会出现"半行正在被刷新"的痕迹。

反过来说，行距取 32 时一屏只剩 7 行，对本工程"标题 + 5 个信息行 + 状态行"来说太浪费。

#### 7.3.5 定宽格式：位置计算里最容易被忽略的一条

字符位置只由"第几个字符"决定，所以**字符串长度一变，后面所有字符都会跟着位移**。看这两行的对比：

```
第一帧：Lux :  1234.5 lx      ← 光照正常
第二帧：Lux :     9.8 lx      ← 用手遮住传感器（未用定宽格式时的实际效果）
```

如果数值区不定宽，`lx` 会在第 10 个和第 14 个字符格之间跳来跳去，观感上像界面在抖，也容易和上一帧的残留叠在一起。

解决办法是**用定宽格式把字段宽度钉死**：

```c
sprintf(buf, "%+5d", acc[i]);          /* 最少 5 字符："+1023" / " -512" */
sprintf(buf, "|a|%5d mg", (int)mag);   /* 数值区恒定 5 字符 */
```

`%5d` 用空格左填充、`%+5d` 强制带符号，无论值是 `-5` 还是 `+1023`，格式化出来的字符数都不变，后面元素的起点也就跟着固定。**这是"位置计算"与"字符串格式化"的交界处**——也解释了 7.7 节为什么在 MicroLIB 下要绕开 `%f`：整数格式的宽度比浮点更好控制（各家 printf 实现里 `%7.1f` 的宽度语义并不完全一致）。

#### 7.3.6 两个静默失败：maxW 截断与边界丢弃

字符函数有两种"不报错、只是少显示点东西"的失败模式，排查时极易误判成"字库缺字"或"驱动写坏了"：

**表 7-7 三类"少显示"现象的机制**

| 现象 | 机制 | 代码位置 |
| --- | --- | --- |
| 一行末尾少几个字符 | `maxW / 8` 是**字符数上限**，超出的不画（`chars--` 到 0 就退出），既不是像素裁剪也不报错 | `LCD_ShowString()` |
| 靠右/靠下的字符整块消失 | `x + 8 > 320` 或 `y + 16 > 240` 时整个字符 `return`，不留半字 | `LCD_ShowChar()` |
| 字符压到条形图上 | 坐标没越界，是两个元素的矩形重叠了——这是版面错误，不是驱动错误 | `app_ui.c` 常量 |

所以 `maxW` 必须按"这一行最长的字符串"算，不能凭感觉。本工程 `TEXT_W = 320 − 8×2 = 304`，即 **38 个字符**；最长的一行（合加速度 + 倾角）24 字符，还有 14 字符余量。这点余量不是浪费，是给"以后再加一项数据"留的。

---

### 7.4 UI 版面设计原理

前两节解决"单个像素、单个字符怎么放"，本节解决"整屏怎么排"。这一节没有通用美学，只有一堆**由硬件和算术逼出来的约束**，以及在这些约束下做出的取舍。

#### 7.4.1 先把画布算清楚

**表 7-8 320×240 画布的可用空间**

| 量 | 计算 | 结果 |
| --- | --- | --- |
| 一行能放几个字符 | 320 / 8 | 40 |
| 无行距时能排几行 | 240 / 16 | 15 |
| 行距 24 时能排几行 | 240 / 24 | **10** |
| 一行的安全文字宽度 | 320 − 左右各 8 像素 | 304 像素 = 38 字符 |
| 常见误算 | 按 40 字符写满 | 最右那个字符会触发 7.3.6 的边界检查，整字消失 |

三个硬约束决定了版面长什么样：

1. **只有一种字号**：字库是 8×16 二值点阵，无法缩放（缩放等于重新取模）。所以"标题要显眼"只能靠**加深色底块 + 白字**来做视觉重量，不能靠放大字形；
2. **行数极少**：10 行。一屏只能讲清一件事，塞不下四五个信息块；
3. **等宽**：所有字符都是 8 像素，天然对齐，不需要像矢量字体那样算字距、kerning。

#### 7.4.2 分区：把屏幕当表格用

本工程的版面（`app_ui.c` 里那张常量表就是这张图）：

```
       x=0      x=8                            x=312 x=320
  y=0  ┌─────────────────────────────────────────────┐
       │             SENSOR MONITOR                  │ ← 标题栏 0…29（30 像素深色底）
  y=30 │                                             │
       │  LIGHT  (BH1750)                            │ y=38   小标题（静）
       │  Lux :  1234.5 lx                           │ y=58   数值（动）
  y=82 │  ───────────────────────────────────────    │ 1 像素分隔线
       │  ACCEL  (LIS3DH)   mg                       │ y=88   小标题（静）
       │  X  +1023  ##########|                      │ y=110  数值 + 条形图（动）
       │  Y   -512       |########                   │ y=132
       │  Z  +1000  ##########|                      │ y=154
 y=176 │  ───────────────────────────────────────    │ 1 像素分隔线
       │  |a| 1002 mg  P +12 R  -5                   │ y=182  汇总（动）
       │                                             │
 y=208 │  BH1750 OK  LIS3DH OK             LEVEL     │ 状态行（静 + 动）
 y=224 └─────────────────────────────────────────────┘
       ↑ 224…239 留白 16 像素
```

两个刻意的选择：

- **左右各留 8 像素边距**（`MARGIN_X = 8`）：一是让文字不顶边、视觉上"有框"；二是 8 正好一个字符宽，于是所有坐标都是 8 的倍数，排版时不用算零头；
- **底部留 16 像素空白**（`Y_STATUS = 208`，208 + 16 = 224 < 240）：画面不到边，避免"最后一行压着屏边"的廉价感；同时给"再加一行"留了位置。

分区的信息层级是按"自上而下"的阅读顺序排的：**谁在最上面、谁占的面积大、谁有背景色，谁就是这一屏的主角**。标题栏用 30 像素深色底宣告"这是一个监测界面"，两个小标题把屏一分为二（光照 / 加速度），底部状态行负责回答"数据可不可信"。

#### 7.4.3 动静分离：这一条决定了闪不闪

把元素按"是否每轮变化"分两层：

**表 7-9 静态层与动态层**

| 层 | 内容 | 何时画 | 面积 |
| --- | --- | --- | --- |
| 静态层 | 标题栏、两个小标题、两条分隔线、X/Y/Z 轴标签 | 只在 `App_UI_Init()` 里画一次 | 约 1.3 万像素 |
| 动态层 | 光照数值、三轴数值、三个条形图、汇总行、LEVEL/TILT | 每轮 `App_UI_Update()` 重画 | 约 **2.1 万像素（占整屏 28%）** |

**为什么必须分**：若每轮都 `LCD_Clear()` 再整屏重画，屏幕会以约 10 ms 的节奏"白一下再出现内容"，背光一亮点就能看出闪烁。分开之后，每轮只改写变化的那几块，面积不到整屏的三成，静态部分一次都不重画，观感就是"数字在跳、别的纹丝不动"。

代价是：**动态区域的矩形必须完全落在自己的格子里**。一旦越界压到静态文字，那块文字就永久丢失（直到下次 `App_UI_Init()`）。所以常量表里每个 y 都留了 4~8 像素间隙：

```
Y_LBL_LUX = 38 ── 字高 16 ──> 38 + 16 = 54
Y_VAL_LUX = 58                  ← 与上一个小标题隔 4 像素
58 + 16   = 74 ── 分隔线在 82    ← 隔 8 像素
Y_LBL_ACC = 88                  ← 与分隔线隔 6 像素
```

#### 7.4.4 重画范围 = 变化范围

动态区域里还有第二层优化：**只重画真正会变的那几列**。

```c
static void FillRow(uint16_t x, uint16_t y, uint16_t w, const char *s, uint16_t fg)
{
  LCD_Fill(x, y, w, 16, C_BG);                       /* ① 先铺底色 */
  LCD_ShowString(x, y, w, fg, C_BG, s);              /* ② 再写字 */
}
```

`LCD_ShowChar()` 本来就把 128 个像素全写一遍（笔画写前景、其余写背景），那 ① 是不是多余？看这个场景：

```
上一帧：Lux :  1234.5 lx
这一帧：Lux :     9.8 lx        ← 遮住传感器
                 └───────┘  这一段落在新字符串之外，
                            ② 根本不会碰它 → 旧数字残留，必须靠 ① 盖掉
```

所以 ① 的真实作用不是"给字符当背景"，而是**覆盖"字符串尾部之外"的区域**。这也解释了 `w` 为什么传整行宽 304 而不是字符串的实际宽度——按实际宽度传，上一帧比这一帧长时就会残留。

条形图同理：`DrawAxisBar()` 每轮先 `LCD_Fill()` 一整条 212×10 的背景，再画零位刻度和柱子，否则数值由正变负时，旧的正向柱子会留在屏幕左边。

#### 7.4.5 视觉编码：颜色不是装饰，是语法

只有一种字号、二值笔画，能用来区分信息的维度只剩"颜色 + 位置 + 线条"。本工程用了两套**互不混用**的颜色语义：

**表 7-10 颜色语义（RGB565 值均为实算结果）**

| 用途 | 颜色 | RGB565 | 出现的固定位置 |
| --- | --- | --- | --- |
| 结构（标题栏底、小标题） | 深靛蓝 `RGB565(22,42,74)` | `0x1149` | 顶部一条 + 两个分组标题 |
| 数值正文 | 近黑 `RGB565(16,16,16)` | `0x1082` | 所有数值 |
| 分隔线 / 零位刻度 | 浅灰 `RGB565(190,196,204)` | `0xBE39` | 两条横线 + 条形图中轴 |
| X 轴 | 红 `RGB565(220,48,48)` | `0xD986` | 轴标签 + 数值 + 条形图 |
| Y 轴 | 绿 `RGB565(32,150,78)` | `0x24A9` | 同上 |
| Z 轴 | 蓝 `RGB565(40,90,210)` | `0x2ADA` | 同上 |
| 状态 · 正常 | 绿（同 Y 轴） | `0x24A9` | 仅状态行 |
| 状态 · 警告 | 橙 `RGB565(226,132,32)` | `0xE424` | 仅状态行 |
| 状态 · 失败 | 红（同 X 轴） | `0xD986` | 仅状态行 |

三条经验：

- **轴色与状态色共用 RGB，但靠位置区分**：红/绿/蓝永远只出现在左半屏的 X/Y/Z 行，绿/橙/红永远只出现在底部状态行。位置固定，语义就不会串——这是"颜色不够用"时最实用的办法，也避免引入第 10 种颜色让画面变花；
- **正文不用纯黑**：用 `0x1082` 而不是 `0x0000`。纯黑配纯白在 TFT 上对比过于锐利，长时间注视会有"字在抖"的错觉；分隔线用浅灰而不是黑，是为了不和文字抢视线；
- **饱和色不做大面积填充**：5 位量化的红在整块填充时容易看出横向条纹（相邻像素电压串扰）。本工程的红色只用在 8×16 的小字和 10 像素高的细条上。

#### 7.4.6 让界面自己会说话

本工程给 UI 加了三样"不是数据显示、但比数据显示更有用"的东西，都是设计层面的决定：

**表 7-11 三个"非数据"元素的设计意图**

| 设计         | 解决什么问题                       | 实现                                                   |
| ---------- | ---------------------------- | ---------------------------------------------------- |
| **传感器状态行** | 不用连串口就知道哪个模块没接好              | `DrawSensorState()`：两颗都在 → 绿；缺一颗 → 橙；都没找到 → 红        |
| **双向条形图**  | 一眼看出正负与大小，也是验证"三轴方向对不对"最快的办法 | `DrawAxisBar()`：`px = mg × (BAR_W/2) / 2000`，屏幕中心为零点 |
| **降级显示**   | 数据不可用时不留空白、不出乱码              | 光照 `-----`、轴值 `---`、汇总行 `sensor offline`，文字用灰色       |

第 3 条是"能用"和"能排查"的分界线。传感器没接时，如果界面直接显示 `0` 或一屏乱码，人会怀疑驱动写错了；显示 `----- lx` + `sensor offline` + 红色的 `BH1750 --`，问题立刻被定位到"硬件没接"这一层。**UI 的第一职责不是好看，是让状态可见。**

#### 7.4.7 版面自检清单

改版面（或把本工程移植到别的分辨率）时，按这张表逐条过一遍，能挡掉绝大多数低级错误：

**表 7-12 版面设计检查清单**

| 检查项 | 判据 | 违反后的表现 |
| --- | --- | --- |
| 文字起点是否 8 的倍数 | `x % 8 == 0` | 字边缘落在像素中间，看着发虚 |
| 最长字符串是否放得下 | `strlen(s) × 8 ≤ maxW` | 行尾静默少字 |
| 元素是否压边 | `x + w ≤ 320`、`y + h ≤ 240` | 整字符消失或条形图被截断 |
| 动态区之间是否留间隙 | 相邻两行 `y` 差不小于字高 + 4 | 上下两行文字互相盖，出现重影 |
| 动态区是否压到静态文字 | 静态文字的矩形是否被动态区包含 | 静态文字被擦掉且不再恢复 |
| 位数变化是否移动后续元素 | 是否使用 `%5d` / `%+5d` 等定宽格式 | 界面跳动、单位乱跑 |
| 数据缺失是否有占位 | 每个数值位置离线时都有 `-----` 类占位 | 空白或乱码，无法区分硬件问题还是软件问题 |
| 对比度是否足够 | 前景与背景至少差 3 档亮度 | 背光调暗后看不清 |

到这里，"一个像素怎么存 → 一个字符怎么定位 → 一整屏怎么排"这条链就闭合了。接下来 7.5 节是编程要点、7.6 节是教学版代码、7.7 节是本工程实际在跑的 `app_ui.c`——**里面每一个数字，都能在前面三节里找到出处**。

---

### 7.5 编程要点

1. **一轮采集 ≈ 70ms**：HTU21D 在 No Hold 模式下每次测量要主机自己等（温度 50ms、湿度 16ms），BH1750 用的是连续测量模式、随时读都是最新值，PCF8563/LIS3DH 都是即读即得。这 70ms 是 `HAL_Delay()` 空转，**正好可以让 DMA 刷屏与它并行**（见第 8 章）——这是本工程里 DMA 收益最实在的一处；
2. **整行重写、先铺背景**：每行刷新时先用 `LCD_Fill()` 铺一遍背景色再画字符串，避免"新数值比旧数值短、尾巴残留旧数字"的经典问题（例如光照从 `1234.5` 掉到 `9.8`，若不清背景，屏幕上会留下 `9.8` 后面半截旧数字）。若想减少写入量，可把标签与数值分区：标签画一次不再动，数值区用**定宽格式**（`%7.1f`、`%6d`）保证每次宽度相同；
3. **别用 CPU 阻塞写把采集流程切开**：软件 I2C 采集期间 CPU 是满负荷的，中间插一段 `LCD_Fill`/`LCD_ShowString` 只会拉长采集时间。刷新只有两种合理姿势：① 采集完成后一次性刷完（第 6 章的方式，简单直接）；② 用第 8 章的 DMA 在 `HAL_Delay()` 等待窗口里发起（异步搬运，CPU 不参与）——**注意二者的区别是"谁在执行"，不是"什么时候做"**；
4. **软件 I2C 与 LCD 无硬件冲突**：软件 I2C 用 PA0/PA1 两个普通 GPIO，FSMC 用 PD/PE 口的 AF12 引脚，互不干扰——这是"FSMC + 软件 I2C"组合比"SPI 屏 + 硬件 I2C"更省心的地方；
5. **把传感器状态画到屏上**：`LIS3DH_Init()` 的返回值、`PCF8563_IsTimeValid()` 的结果都直接显示出来，"哪个模块没接好"一眼可见，不必连串口。

### 7.6 代码分析

列表 6: 代码清单 7-1 传感器数据显示主程序（main.c 的 USER CODE 区）

```c
#include "bsp_lcd.h"
#include "bsp_soft_i2c.h"
#include "bsp_sensor_io.h"
#include "bsp_bh1750.h"
#include "bsp_htu21d.h"
#include "bsp_pcf8563.h"
#include "bsp_lis3dh.h"
#include <stdio.h>

/* 显示布局（横屏 320×240）：顶部一行标题独占，其下 5 行数据
   行宽必须 ≤ LCD_WIDTH - 2×ROW_X = 304，且是 8 的整数倍（不出现半个字符） */
#define ROW_TIME    0
#define ROW_LUX     1
#define ROW_TEMP    2
#define ROW_HUM     3
#define ROW_ACC     4

#define ROW_X       8                       /* 行起始 x 坐标 */
#define ROW_W       304                     /* 每行刷新区域宽度 = 38 字符（最长的 Acc 行 33 字符） */
#define ROW_H       16                      /* 字高 */
#define TITLE_Y     8                       /* 标题行 y 坐标：独占顶部，不被数据刷新覆盖 */
#define ROW_Y(r)    (40 + (r) * 24)         /* 数据行 y 坐标：第 5 行底部 = 40+4×24+16 = 152 < 240 ✓ */

/* 刷新一行：先铺背景色彻底清掉旧内容，再写新字符串 */
static void LCD_RefreshRow(uint8_t row, const char *str)
{
  LCD_Fill(ROW_X, ROW_Y(row), ROW_W, ROW_H, LCD_BG_COLOR);
  LCD_ShowString(ROW_X, ROW_Y(row), ROW_W, LCD_FG_COLOR, LCD_BG_COLOR, str);
}

/* 画标题：只在上电时画一次（18 字符 = 144 像素，占 x = 8~152） */
static void LCD_DrawTitle(void)
{
  LCD_ShowString(ROW_X, TITLE_Y, ROW_W, LCD_FG_COLOR, LCD_BG_COLOR,
                 "I2C Sensor Monitor");
}

int main(void)
{
  float lux, temp, hum;
  short acc[3] = {0, 0, 0};
  PCF8563_Time_t now;
  char buf[48];
  uint8_t lisOk, rtcLost;

  HAL_Init();
  SystemClock_Config();        /* 168MHz，HCLK=168MHz 供 FSMC */
  MX_GPIO_Init();              /* 含 PD2 背光、PA1/PA0 软件 I2C 开漏 */
  MX_FSMC_Init();              /* NE1 + A17，模式 B，16 位 */
  MX_USART1_UART_Init();       /* 可选：串口同步打印，便于对照 */

  I2C_Init();                  /* 软件 I2C 总线释放为空闲高电平 */
  LCD_Init();                  /* LCD 复位 + ILI9341 配置 + 清屏 + 开背光 */

  /* ---------- 传感器初始化（复用 IIC 笔记 9.2.3 节的器件层） ---------- */
  BH1750_Init();
  HTU21D_Init();
  lisOk   = LIS3DH_Init();              /* 1 = 读到 WHO_AM_I = 0x33，器件在线 */
  rtcLost = (PCF8563_IsTimeValid() == 0) ? 1 : 0;   /* 1 = 曾掉电（模块没装纽扣电池）*/

  /* 掉电过就补一个初始时间（做法同 IIC 笔记代码清单 9-6），让屏上时钟立即可用；
     若只想看到告警、不想自动改时间，把这段删掉即可 */
  if (rtcLost)
  {
    PCF8563_Time_t init = { 0, 30, 12, 7, 3, 10, 26 };  /* 秒,分,时,日,星期,月,年 */
    PCF8563_WriteTime(&init);
  }

  LCD_DrawTitle();

  /* RTC 掉电时在标题右侧提示一次（标题行不会被数据刷新覆盖，所以只画一次）
     x = 168 起、11 字符 = 88 像素，占 168~256，不会与标题（8~152）重叠、也不越出 320 */
  if (rtcLost)
  {
    LCD_ShowString(ROW_X + 160, TITLE_Y, 96, LCD_FG_COLOR, LCD_BG_COLOR, "[RTC RESET]");
  }

  while (1)
  {
    /* 1. 一轮采集：软件 I2C，约 70ms，CPU 全程占用（其中约 66ms 是 HAL_Delay 空转） */
    lux  = BH1750_ReadLux();
    temp = HTU21D_ReadTemp();
    hum  = HTU21D_ReadHumidity();
    PCF8563_ReadTime(&now);
    LIS3DH_ReadAcc(acc);

    /* 2. 逐行刷新：sprintf 格式化 → 清背景 → 写字符串 */
    sprintf(buf, "Time : 20%02d-%02d-%02d %02d:%02d:%02d",
            now.year, now.month, now.day, now.hour, now.min, now.sec);
    LCD_RefreshRow(ROW_TIME, buf);

    /* 读取失败时驱动返回负值，屏幕上会出现明显的负数——这是最好的自检 */
    sprintf(buf, "Lux  : %7.1f lx", lux);
    LCD_RefreshRow(ROW_LUX, buf);

    sprintf(buf, "Temp : %7.2f C", temp);
    LCD_RefreshRow(ROW_TEMP, buf);

    sprintf(buf, "Humi : %7.2f %%RH", hum);
    LCD_RefreshRow(ROW_HUM, buf);

    if (lisOk)
    {
      sprintf(buf, "Acc  : X=%6d Y=%6d Z=%6d", acc[0], acc[1], acc[2]);
    }
    else
    {
      sprintf(buf, "Acc  : LIS3DH NOT FOUND");
    }
    LCD_RefreshRow(ROW_ACC, buf);

    HAL_Delay(900);              /* 采集约 70ms，凑整 1 秒一轮 */
  }
}
```

**分析**：

- 数据链路是"**器件驱动 → float/结构体 → sprintf → LCD_ShowString → FSMC 写 GRAM**"，I2C 与 LCD 完全解耦，任何一边出问题都能单独定位；
- 每次刷新一行 = 铺背景（304×16 = 4864 像素）+ 写字符（33 字符 × 128 像素 ≈ 4224 像素），共约 9000 次 FSMC 写 ≈ **0.75ms**；5 行合计约 3.8ms/秒，CPU 占用约 0.4%——**这也是"要不要为刷屏上 DMA"的判断依据：本工程 DMA 省下的 CPU 时间只有几毫秒/秒，收益有限，真正的价值在"把这 4ms 藏进 I2C 的等待里"以及将来做波形/图片显示时的可扩展性**（见第 8 章）；
- **注意"每行都铺背景"与"写入量"的权衡**：`LCD_ShowChar()` 本身就会写满每个字符格子（包括笔画之间的背景像素），所以 `LCD_Fill()` 其实是"防残留"的双保险——它的作用是盖住**字符串尾部之外**的区域（例如 Acc 行从 `LIS3DH NOT FOUND` 变成正常数值后，尾巴会短一截）。如果每行的字符串宽度恒定（`%7.1f`、`%6d` 这类定宽格式），就可以省掉 `LCD_Fill()`，写入量直接减半；反过来，一旦有"某行整体变短"的情况（如上面这种状态切换），就必须保留清背景；
- 若个别传感器未接，屏幕上会显示负数或 `NOT FOUND`，一眼能看出来——这比"黑屏"友好得多。

---

### 7.7 本工程的实际落地版本（app_ui.c）

代码清单 7-1 是"四传感器 + 逐行写"的教学版。本工程实际跑的是**两颗传感器版本**（BH1750 + LIS3DH），显示层拆成了独立的 `app_ui.c` / `app_ui.h`，`main.c` 里只剩 HAL 初始化和 `while(1)`。拆出来的好处很直接：**版面坐标集中在一个文件里，改布局既不碰驱动也不碰 main**。

对外只有两个函数：

| 函数 | 职责 |
| --- | --- |
| `uint8_t App_UI_Init(void)` | 清屏 → 画静态版面（标题栏、小标题、分隔线、轴标签）→ 探测两颗传感器（`BH1750_Probe()` / `LIS3DH_Init()`）→ 画一次状态行；返回 bit0 = BH1750 在线、bit1 = LIS3DH 在线 |
| `void App_UI_Update(void)` | 读一次传感器 → **只重画数值区与条形图** → 每 5 轮（约 1s）同步打一组串口 |

版面坐标全是 `#define`，行距 24 像素，正好是 8×16 字库再加 8 像素行间：

| 常量 | 取值 | 说明 |
| --- | --- | --- |
| `HDR_H` | 30 | 顶部标题栏高度 |
| `Y_LBL_LUX` / `Y_VAL_LUX` | 38 / 58 | 光照段的小标题与数值行 |
| `Y_ACC_X` / `Y_ACC_Y` / `Y_ACC_Z` | 110 / 132 / 154 | 三轴数值行（与 `LCD_ShowChar` 的 16 像素字高对齐） |
| `Y_MAG` | 182 | 合加速度与倾角行 |
| `Y_STATUS` | 208 | 底部状态行（左侧传感器状态、右侧 LEVEL/TILT） |
| `BAR_X` / `BAR_W` / `BAR_FS_MG` | 100 / 212 / 2000 | 条形图左边界、宽度、满量程（±2g） |

**四个直接决定"能不能稳定显示"的细节**：

1. **静态只画一次**：标题栏、小标题、分隔线、轴标签在 `App_UI_Init()` 里画完就不再碰，循环里只重画"数值 + 条形图"。把整屏 `LCD_Clear()` 放进循环是闪烁的根源；
2. **数值区先铺底色**：`FillRow()` = `LCD_Fill()` + `LCD_ShowString()`，lux 从 `1234.5` 掉到 `9.8` 时不会残留半截旧数字；
3. **浮点用整数定点打印**：工程勾了 **Use MicroLIB**，精简版 `printf` 不支持 `%f`（输出空串或乱码），所以 lux 先算出 `lux10 = lux × 10` 再用 `%u.%u` 拼小数点，角度四舍五入取整后 `%+4d`；
4. **条形图以屏幕中心为零点**：`px = mg × (BAR_W/2) / 2000`，正值向右、负值向左，翻转板子时数值正负号与柱子方向同时变——比只看数字直观得多，也是验证"三轴方向对不对"最快的办法。

---

## 8. CPU 占用优化与 DMA 刷屏

### 8.1 CPU 占用分析

本应用中 CPU 的开销主要有三块：

**表 8-1 每秒的 CPU 开销（按 168MHz、FSMC 一次 16 位写约 131ns 估算）**

| 环节 | 耗时量级 | 能否优化 |
| --- | --- | --- |
| 软件 I2C 采集一轮（4 个传感器） | ≈70ms / 秒，其中约 66ms 是 HTU21D No Hold 模式下的 `HAL_Delay()` 空转 | 等待期间 CPU 完全空闲，**正好可以让 DMA 刷屏并行填进去**（见 8.5 节）；要彻底降下来只能把总线改到 PB8/PB9 用硬件 I2C + DMA 收数（《IIC 通信》笔记第 7 章） |
| 逐行刷屏（5 行 × 304×16 ≈ 2.4 万像素，含开窗开销约 4.5 万次总线写） | ≈5.9ms / 秒（约占 CPU 的 0.6%） | **DMA 可接管**（见 8.2） |
| `sprintf` 格式化 | 几十 µs | 可忽略 |

**先给个结论**：以本工程每秒刷 5 行的规模，刷屏只占 CPU 的 0.6%，"为了省这几毫秒而上 DMA"本身收益很小。DMA 在这里的真正价值有两处：

1. **把搬运时间藏进 I2C 的等待窗口**——发起 DMA 后 CPU 立即去执行 HTU21D 的 50ms 等待，两者并行，等于刷屏"不要钱"；
2. **可扩展性**——一旦要做波形刷新、图片显示、滑动菜单，刷屏时间会涨到几十毫秒量级，那时 DMA 就是必需品，代码结构越早搭好越省事。

FSMC 本身**不产生 DMA 请求**（它是存储器接口，不是外设请求源），所以不能像 ADC/UART 那样"外设请求 DMA"。但可以用 **DMA2 的内存到内存（M2M）模式**把内部 SRAM 中的帧缓冲整块搬到 FSMC 映射地址——CPU 只负责"发起"，搬运过程零占用。

### 8.2 DMA 内存到内存搬运的原理

对 FSMC 映射区做 DMA 的关键认识是：**在 DMA 眼里，0x60000000 开头的 FSMC 地址区间和内部 SRAM 没有任何区别——它就是一段"内存"**。因此：

1. 在内部 SRAM 里建一块**局部帧缓冲**（如一行文字区域的像素数组）；
2. 先在帧缓冲里把字符点阵渲染好（写内部 RAM，速度极快）；
3. 开窗（`LCD_OpenWindow`）+ 发 `0x2C` 后，启动 DMA2 M2M 传输，源 = 帧缓冲，目的 = `LCD_DATA_ADDR`；
4. DMA 控制器自动把整段像素灌进 GRAM，**CPU 在这期间立刻返回**去干别的（比如执行下一轮 I2C 采集里的 `HAL_Delay()`）。

> **必须警惕的一个语义陷阱（本笔记早期版本的错误就出在这里）**：在 STM32F4 的 HAL 里，M2M 模式的**源地址被写进 PAR（外设端口寄存器）、目的地址被写进 M0AR（内存端口寄存器）**，也就是"**源 = Peripheral，目的 = Memory**"。所以：
>
> - `HAL_DMA_Start_IT(hdma, (uint32_t)帧缓冲, LCD_DATA_ADDR, 像素数)` 中，**帧缓冲进 PAR、LCD 数据口进 M0AR**；
> - **自增位要按这个映射来配**：`PeriphInc`（PINC）控制的是 **PAR 即源地址** → 必须 **ENABLE**（帧缓冲要逐个像素往后走）；`MemInc`（MINC）控制的是 **M0AR 即目的地址** → 必须 **DISABLE**（LCD 数据口地址固定不动，像素地址递增由 ILI9341 内部完成）。
>
> **如果按"直觉"把两者配反**（源不自增、目的自增），现象是：屏幕只显示第一个像素的颜色，或者干脆花屏/跑飞——因为 DMA 会拿同一个像素反复写 GRAM，同时把 LCD 数据口地址当数组往后"踩"。**这是 M2M 驱动 LCD 最容易踩的坑。**

其他几条约束：

- **M2M 模式严禁使用 Circular**（参考手册明确禁止），只能用 Normal：搬完即停；
- M2M 传输会占用 AHB 总线带宽，传输期间 CPU 访问 RAM/Flash 会被仲裁插入等待，所以 **DMA 并不会缩短墙钟时间，它缩短的是"CPU 被占用时间"**；
- 本工程未用 ADC；若将来把它与《ADC 采集配置》笔记合并，注意那边 **ADC1 用的是 DMA2 Stream0**，与本章冲突——需要给其中一个换 Stream（ADS 用 Stream0，LCD 用 Stream1）或复用同一个流并分时启动。

### 8.3 CubeMX 配置 DMA2

1. **System Core → DMA** → **MemToMem** → 点击 **Add**，CubeMX 生成 `hdma_memtomem_dma2_stream0`，勾选 **DMA2 Stream0 global interrupt**；
2. **parameter 里注意两件事**：① Mode 必须 **Normal**（M2M 不支持 Circular）；② **源、目的的自增设置**——CubeMX 的 MemToMem 面板在部分版本里只给一个"Increment Address"选项（两端同设置），**如果它不让你分别设置两端，就直接手写初始化代码**（代码清单 8-1），别硬凑；
3. 若走 CubeMX 生成：注意 `stm32f4xx_it.c` 里会由 CubeMX 自动加上 `DMA2_Stream0_IRQHandler()`，它会调用 CubeMX 自己的 `hdma_memtomem_dma2_stream0` 句柄——**此时不要再重复定义一次该中断函数**（否则链接报 multiple definition），而是复用 CubeMX 的句柄（在 `MX_DMA_Init()` 之外，把它的 `XferCpltCallback` 换成自己的回调即可）；
4. 本章 8.4 节给出的代码是**完全手写、不依赖 CubeMX 生成 DMA** 的版本，工程上最省心：只要在 DMA 配置里勾了 NVIC，或者干脆自己在 `LCD_DMA_Init()` 里配 NVIC 都行。

### 8.4 代码分析

列表 7: 代码清单 8-1 DMA 刷屏驱动（lcd_dma.h / lcd_dma.c）

```c
/* lcd_dma.h */
#ifndef __LCD_DMA_H
#define __LCD_DMA_H

#include "bsp_lcd.h"

/* 一行文字区域的帧缓冲尺寸（像素）：
   宽度必须 ≥ 实际一行的最大刷新宽度 ROW_W(304)，且与它同为 8 的整数倍 */
#define LINE_BUF_W   320
#define LINE_BUF_H   16

void LCD_DMA_Init(void);
HAL_StatusTypeDef LCD_DMA_FillBuffer(uint16_t x, uint16_t y,
                                     uint16_t w, uint16_t h,
                                     const uint16_t *pixels);
void LCD_ShowString_DMA(uint16_t x, uint16_t y, uint16_t maxW, const char *str);

#endif
```

```c
/* lcd_dma.c */
#include "lcd_dma.h"

static DMA_HandleTypeDef hdma_lcd;
static volatile uint8_t  dma_busy = 0;      /* 1 = 上一次搬运还没结束 */

static void LCD_DMA_CpltCallback(DMA_HandleTypeDef *hdma);
static void LCD_DMA_ErrorCallback(DMA_HandleTypeDef *hdma);

/**
  * @brief  初始化 DMA2 Stream0：帧缓冲 → FSMC 数据端口（内存到内存）
  * @note   关键三点：
  *         ① M2M 模式下"源 = Peripheral 端（PAR）、目的 = Memory 端（M0AR）"，
  *            所以 PeriphInc 控源、MemInc 控目的。本应用源要自增、目的固定，
  *            因此 PeriphInc = ENABLE、MemInc = DISABLE（与直觉相反，详见 8.2 节）
  *         ② Mode 必须是 Normal，M2M 禁止 Circular
  *         ③ FIFO 关闭 + 单次突发：M2M 用 FIFO/突发虽能提速，但要求地址按突发
  *            宽度对齐，且 FIFO 门槛设置不当时易出现"传一半停住"。FSMC 本就是
  *            慢速从设备，省这点时间没有意义，稳定性优先
  */
void LCD_DMA_Init(void)
{
  __HAL_RCC_DMA2_CLK_ENABLE();

  hdma_lcd.Instance                 = DMA2_Stream0;
  hdma_lcd.Init.Channel             = DMA_CHANNEL_0;          /* M2M 模式下通道号无效 */
  hdma_lcd.Init.Direction           = DMA_MEMORY_TO_MEMORY;
  hdma_lcd.Init.PeriphInc           = DMA_PINC_ENABLE;        /* 【源】帧缓冲逐个像素自增 */
  hdma_lcd.Init.MemInc              = DMA_MINC_DISABLE;       /* 【目的】LCD 数据口固定不动 */
  hdma_lcd.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;/* 源：16 位（RGB565 一像素） */
  hdma_lcd.Init.MemDataAlignment    = DMA_MDATAALIGN_HALFWORD;/* 目的：16 位 */
  hdma_lcd.Init.Mode                = DMA_NORMAL;
  hdma_lcd.Init.Priority            = DMA_PRIORITY_HIGH;
  hdma_lcd.Init.FIFOMode            = DMA_FIFOMODE_DISABLE;
  hdma_lcd.Init.FIFOThreshold       = DMA_FIFO_THRESHOLD_FULL;
  hdma_lcd.Init.MemBurst            = DMA_MBURST_SINGLE;
  hdma_lcd.Init.PeriphBurst         = DMA_PBURST_SINGLE;

  if (HAL_DMA_Init(&hdma_lcd) != HAL_OK)
  {
    Error_Handler();
  }

  /* 回调必须在 HAL_DMA_Init() 之后挂：F4 的 HAL_DMA_Init 会把句柄里的
     所有回调指针清空，先挂就等于白挂。若用 HAL_DMA_RegisterCallback()
     注册，同样要放在 Init 之后 */
  hdma_lcd.XferCpltCallback  = LCD_DMA_CpltCallback;
  hdma_lcd.XferErrorCallback = LCD_DMA_ErrorCallback;

  HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

/* 搬运完成：解锁 */
static void LCD_DMA_CpltCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma == &hdma_lcd) dma_busy = 0;
}

/* 搬运出错：也必须解锁，否则一次错误就把接口永久锁死，屏幕从此不再刷新 */
static void LCD_DMA_ErrorCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma == &hdma_lcd) dma_busy = 0;
}

/**
  * @brief  用 DMA 把一个矩形区域的像素写入 LCD
  * @param  pixels: 内部 SRAM 中的像素数组（RGB565，w*h 个 uint16_t）
  * @retval HAL_BUSY = 上一次搬运尚未完成；其余为 HAL 返回值
  * @note   注意执行顺序：必须在启动 DMA **之前**开窗并发出 0x2C，
  *         否则 DMA 灌进去的像素不会被当作 GRAM 数据
  */
HAL_StatusTypeDef LCD_DMA_FillBuffer(uint16_t x, uint16_t y,
                                     uint16_t w, uint16_t h,
                                     const uint16_t *pixels)
{
  HAL_StatusTypeDef st;

  if (dma_busy) return HAL_BUSY;
  if (w == 0 || h == 0) return HAL_ERROR;
  /* 这里必须自己挡越界：LCD_OpenWindow() 会把窗口裁到屏幕内，
     而 DMA 的传输个数用的是原始的 w*h——两者不一致时，多出来的像素
     会写到窗口之外，表现为屏幕右侧/下方出现一条错位色带 */
  if ((uint32_t)x + w > LCD_WIDTH || (uint32_t)y + h > LCD_HEIGHT) return HAL_ERROR;

  dma_busy = 1;

  LCD_OpenWindow(x, y, w, h);
  LCD_WRITE_CMD(0x2C);          /* 进入 Memory Write，DMA 只负责灌数据 */

  st = HAL_DMA_Start_IT(&hdma_lcd, (uint32_t)pixels,
                        LCD_DATA_ADDR, (uint32_t)w * h);
  if (st != HAL_OK)
  {
    dma_busy = 0;               /* 启动失败要立即解锁，否则接口再也调不动 */
  }
  return st;
}

/* 中断入口：写在 stm32f4xx_it.c 或本文件（全局只能有一份） */
void DMA2_Stream0_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&hdma_lcd);
}
```

列表 8: 代码清单 8-2 用 DMA 显示一行文字（先在 RAM 里渲染，再整块灌屏）

```c
#include "lcd_dma.h"

/* 一行文字区域的帧缓冲：320×16 = 5120 像素 = 10KB 内部 SRAM
   （SRAM1 + SRAM2 共 128KB，放一两行绰绰有余） */
static uint16_t line_buf[LINE_BUF_W * LINE_BUF_H];

/**
  * @brief  把字符串渲染进帧缓冲（纯内部 RAM 操作，不碰 FSMC）
  * @note   字库与 LCD_ShowChar 共用同一份 asc2_1608，取模顺序必须一致：
  *         每字符 16 字节、逐行、MSB 在左
  */
static void LCD_RenderString(uint16_t *buf, uint16_t bufW, uint16_t renderW,
                             const char *str)
{
  uint32_t total = (uint32_t)bufW * LINE_BUF_H;
  uint32_t i;
  uint16_t chMax = renderW / 8;       /* renderW 内最多几个字符 */
  uint16_t ch, row, col;
  uint8_t  data;
  char     c;
  const uint8_t *font;

  /* 1. 整行铺背景色（含空白区），保证覆盖掉上一次的内容 */
  for (i = 0; i < total; i++)
  {
    buf[i] = LCD_BG_COLOR;
  }

  /* 2. 逐字符取模渲染；超出 renderW 的字符直接不画（截断） */
  for (ch = 0; ch < chMax && str[ch] != '\0'; ch++)
  {
    c = str[ch];
    if (c < ' ' || c > '~') c = ' ';

    font = asc2_1608[(uint8_t)c - 0x20];
    for (row = 0; row < 16; row++)
    {
      data = font[row];
      for (col = 0; col < 8; col++)
      {
        buf[row * bufW + ch * 8 + col] =
            (data & (0x80 >> col)) ? LCD_FG_COLOR : LCD_BG_COLOR;
      }
    }
  }
}

/**
  * @brief  显示一行字符串（渲染到帧缓冲 + DMA 灌屏）
  * @note   发起 DMA 后本函数就返回了；若下一行要马上刷新，
  *         需等 dma_busy 清零（下面的兜底等待），或在主循环里让出时间
  */
void LCD_ShowString_DMA(uint16_t x, uint16_t y, uint16_t maxW, const char *str)
{
  uint32_t guard = 0;

  if (maxW > LINE_BUF_W) maxW = LINE_BUF_W;   /* 缓冲区固定宽度，超了会写穿 */
  if (maxW == 0) return;

  LCD_RenderString(line_buf, LINE_BUF_W, maxW, str);

  /* 兜底：上一行还在搬就等一会。正常情况这里最多等几十微秒
     （5120 像素 @ 约 24MB/s 也就 0.2ms），不会成为瓶颈 */
  while (LCD_DMA_FillBuffer(x, y, maxW, LINE_BUF_H, line_buf) == HAL_BUSY)
  {
    if (++guard > 1000000U) break;            /* 异常时不要死等 */
  }
}
```

**要点分析**：

1. **`HAL_DMA_Start_IT()` 的源/目的顺序按 M2M 的映射关系写**：第一个参数（源）进 PAR、第二个参数（目的）进 M0AR，自增位与之配对，配反了就花屏（见 8.2 节）；
2. **回调不是"重定义库函数"**：F4 HAL 里没有可以覆盖的 `HAL_DMA_XferCpltCallback()`，正确做法是把函数指针挂到句柄上（`hdma->XferCpltCallback = …`）或用 `HAL_DMA_RegisterCallback()`，并且**必须在 `HAL_DMA_Init()` 之后挂**；
3. **完成与出错都要解锁**：只解完成回调、不解出错回调，一次 DMA 错误就会让 `dma_busy` 永久为 1，屏幕"刷新一次之后就再也不动"——这是排查时最容易误判成"屏幕坏了"的软件故障；
4. **`0x2C` 必须在启动 DMA 之前发**：DMA 只往数据口灌字节，不负责发命令。若顺序反了，屏幕会显示上一次开窗区域的残留内容；
5. **渲染阶段是纯 RAM 操作**：`LCD_RenderString()` 只写内部 SRAM，不产生任何 FSMC 周期，所以即使没有 DMA，这套"先渲染到缓冲、再一次性写屏"的结构也比"逐点 `LCD_DrawPoint`"快得多（少了 13 倍的开窗开销）。

### 8.5 收益与并行的用法

把 8.4 节的接口接到主循环里，**关键不是"省了多少 CPU"，而是"让 DMA 去跑，CPU 立刻去做 I2C 的等待"**。下面两段只保留与 DMA 相关的关键调用，其余行见第 7 章代码清单 7-1：

```c
while (1)
{
  /* 1. 先采集（HTU21D 内部含 HAL_Delay，是 CPU 空转的窗口） */
  lux  = BH1750_ReadLux();                      /* 连续模式，即读即得 */
  temp = HTU21D_ReadTemp();                     /* 内部含 HAL_Delay(50) */

  /* 2. 把这一轮的数据刷到屏上：DMA 搬运，CPU 发起后即可返回 */
  sprintf(buf, "Temp : %7.2f C", temp);
  LCD_ShowString_DMA(ROW_X, ROW_Y(ROW_TEMP), ROW_W, buf);

  HAL_Delay(900);
}
```

更直白的写法是把刷新**塞进"等待窗口"**里——触发测量后立刻刷屏，让 50ms 等待与搬运并行：

```c
  /* 触发 No Hold 温度测量，然后在 50ms 等待里完成上一行数据的灌屏 */
  I2C_WriteCmd(HTU21D_ADDR_W, HTU21D_TRIG_T_NOHOLD);
  LCD_ShowString_DMA(ROW_X, ROW_Y(ROW_TEMP), ROW_W, buf_temp);  /* 发起即返回 */
  HAL_Delay(50);                                               /* 等待与搬运并行 */
  I2C_ReadBytes(HTU21D_ADDR_W, raw, 2);
```

**两种方式的量化对比**（刷新一行 304×16 = 4864 像素）：

| 方式 | 墙钟耗时 | CPU 占用 | 说明 |
| --- | --- | --- | --- |
| 逐点 `LCD_DrawPoint` | 约 8ms | 约 8ms | 每像素一次开窗（13 次总线写），最差 |
| 按字符开窗 `LCD_ShowString` | 约 0.7ms | 约 0.7ms | 本笔记第 6 章的默认实现，性价比最高 |
| 渲染 + DMA | 约 0.9ms（渲染 0.3ms + 搬运 0.6ms） | **约 0.3ms** | 墙钟时间几乎不变，但其中 0.6ms 可与 I2C 等待重叠 |

> **结论**：墙钟时间由 FSMC 写周期决定（16 位写 131ns，谁也绕不过），DMA 改变的是"这 0.6ms 由谁在执行"。**所以判断要不要用 DMA 的标准是："刷屏期间 CPU 有没有别的事可做"**——本工程有（I2C 的 66ms 等待），所以值得；如果主循环刷完屏就没事干，用不用都一样。

> **进阶方向**：若做波形显示/图片显示等大帧刷新，可把帧缓冲设为整行或半屏，配合 DMA 双缓冲交替渲染与推送，CPU 占用可再降一个数量级。本屏整屏 320×240×2B = **150KB**，已超过 F407 的 SRAM1+SRAM2（128KB），而且 **CCM 那 64KB 不能被 DMA 访问**（CCM 不挂 DMA 总线），所以"整屏一块帧缓冲"还是放不下——但可以**分成上下两块、每块 75KB 做 ping-pong 双缓冲**，比 4.3 寸大屏必须"分行搬运"的处境宽松得多。这也是小屏做动画/波形的一个实际优势。

> **本工程当前的状态**：精简版主循环只挂 BH1750 + LIS3DH，**没有 HTU21D 的 50ms 等待窗口**，刷屏又在 `HAL_Delay(200)` 里完成，所以 `app_ui.c` 用的是最直接的阻塞刷屏，并没有启用本章的 DMA 方案。本章的代码仍保留价值：一旦要画波形、贴图片或做滑动菜单（单帧几十毫秒），把 `LCD_ShowString()` 换成 `LCD_ShowString_DMA()` 即可，**换的只是"谁执行搬运"，上层调用方式不变**。

---

## 9. 下载验证与常见问题

### 9.1 验证步骤

1. 编译下载：屏幕先短暂黑一下（背光关 → 写寄存器 → 清屏），随即点亮；
2. **先看自检图**（`LCD_SELFTEST = 1` 时开机显示 3 秒）：应看到 **1 红左上、2 绿右上、3 蓝左下、4 黄右下**，四周白框闭合、16 条彩条铺满整宽。**这一屏是方向与寻址范围的唯一证据**——角标缺一个、两两重叠、或整体转了 90°，都先按 6.5 节标定，不要急着往下看内容；
3. **纯色验证硬件**（可选）：临时 `LCD_Clear(RED/GREEN/BLUE)`，应依次纯红、纯绿、纯蓝。红蓝互换 → MADCTL 加 0x08；满屏随机雪花 → 时序或接线；只有一条整齐的带子不对 → MV 位（6.5 节）；
4. 确认方向后把 `LCD_SELFTEST` 改 `0` 重新编译，进入传感器界面：顶部深色标题栏 → `LIGHT (BH1750)` 段 → `ACCEL (LIS3DH)` 三行数值 + 条形图 → `|a|` 合加速度与 `P/R` 倾角 → 底部状态行；
5. 串口（USART1，115200-8-N-1）同时打印 `BH1750 : OK` / `LIS3DH : OK`，之后约每秒一组 `Lux : ...` 与 `ACC : X=... Y=... Z=...`；
6. **用手遮住 BH1750**：Lux 应明显下降，手电照射升到上千 lx；
7. **翻转、侧立开发板**：X/Y/Z 的数值与条形图方向同步翻转；静止平放时 Z ≈ +1000、`|a|` ≈ 1000mg、右下角显示 `LEVEL`，倾斜超过 ±10° 变 `TILT`；
8. **拔掉某个模块再上电**：对应行显示 `-----` / `---` 与 `sensor offline`，左下状态文字变橙（缺一个）或红（都没找到），串口打印 `NOT FOUND` 并附带接线提示——这就是"把自检信息画到屏上"的价值；

### 9.2 常见问题速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| 模块只有 8 根线（VCC/GND/CS/RST/DC/MOSI/SCK/BL） | 买到的是 **SPI 版模块**，没有 8080 并口 | FSMC 方案不可用：换并口版模块，或改用 SPI 驱动（见第 1.2 节提醒） |
| 完全白屏、无任何显示 | FSMC 未配通（NE1/A17 引脚复用错、未使能写） | 检查 CubeMX 中 FSMC 的 NE1、Register Select=A17、Write Operation=Enabled；检查 DATAST 是否过小 |
| 花屏、颜色错乱、随机彩点 | DATAST/ADDSET 太小，数据未稳定即锁存 | 本工程用 ADDSET=5 / DATAST=15；**但"整齐的一条带子"不是时序问题**，见下面两条 |
| **红蓝两色互换**（纯红刷成蓝） | MADCTL（0x36）的 **BGR 位（0x08）** 与实际像素顺序不符 | 把 `0x00` 改成 `0x08`（或反之），见 6.4 节表 6-2 |
| 显示内容全是"命令"效果（如全屏一种异常色） | 命令/数据地址搞反（A17 偏移算错） | 数据地址必须是基地址 \| (1<<18)，不是 \| (1<<17) |
| 右侧/尾部一条整齐的花带，或某几个元素完全不显示 | **MADCTL 带了 MV 位**（列数被换成 240，x ≥ 240 全丢），或 `LCD_WIDTH` 与 GRAM 实际列数不符 | `LCD_MADCTL = 0x00`；用自检图确认 GRAM 尺寸（6.5 节）。**不要靠加大 DATAST 治这个症状** |
| **四个角标两两重叠，或整体转了 90°** | GRAM 的行列与屏幕方向交叉 / GRAM 尺寸判断错 | 按 6.5.3 节两轮标定：先定 GRAM 尺寸，再用 `LCD_SW_FLIP_X/Y` 定符号 |
| **画面镜像 / 上下颠倒** | 软件翻转开关与面板实际方向不符 | 改 `LCD_SW_FLIP_X`、`LCD_SW_FLIP_Y`（对照表见 6.5.3 节），**不要再去猜 MADCTL** |
| **图形正常、只有文字是倒的** | 翻转后窗口起点跑到另一端，字符点阵送数顺序没跟着反 | `LCD_ShowChar()` 里 Y 反向时用 `font[15 - row]`（6.5.4 节） |
| **串口有数、屏上却不动** | 主循环没调 `App_UI_Update()`，或 `LCD_SELFTEST` 的 `HAL_Delay(3000)` 之后没进入循环 | 确认 `while(1)` 里有 `App_UI_Update()` 与 `UI_PERIOD_MS` 延时 |
| **画面整体反色**（白底黑字变成黑底白字） | 显示反转命令（0x21）的状态与模块不符 | 在初始化序列里试加 `0x20`（关闭反转）或 `0x21`（开启反转）——ILI9341 模块这一条差异很常见 |
| 颜色发白、发暗、偏色 | 伽马/电源寄存器用的是通用值，与你的模块不完全匹配 | 用屏厂提供的初始化序列替换代码清单 6-2 的 `lcd_vendor_init[]`（只改这张表） |
| DMA 灌屏后整行只有一种颜色 / 花屏 | **M2M 模式下自增位配反**：源（PeriphInc）应自增、目的（MemInc）应固定 | 改为 `PeriphInc = ENABLE`、`MemInc = DISABLE`，并核对 `HAL_DMA_Start_IT(源, 目的, 个数)` 的实参顺序 |
| DMA 刷了一次之后屏幕再也不动 | 出错回调没清零 `dma_busy`（或被 `dma_busy` 挡住后一直返回 HAL_BUSY） | 在 `XferErrorCallback` 里同样清零；确认回调是挂在句柄上而不是"重定义库函数" |
| 编译报 multiple definition: `DMA2_Stream0_IRQHandler` | CubeMX 的 MemToMem 已生成一份中断转发，又手写了一份 | 删掉其中一份；走 CubeMX 生成时把回调挂到 CubeMX 的句柄上即可 |
| 想同时用 ADC 采集时 DMA 冲突 | 《ADC 采集配置》笔记里 ADC1 也用 DMA2 Stream0 | 给其中一个换 Stream（如 LCD 用 Stream1），或复用同一流分时启动 |
| 背光不亮但实测 FSMC 读写正常 | PD2 未配成输出或电平反了 | 查 MX_GPIO_Init 中 PD2；用万用表量 PD2 电平（部分模块是低电平点亮，按模块说明） |
| 传感器数据全是 -1 / 显示 NOT FOUND | 软件 I2C 总线不通（上拉电阻、PA0/PA1 接线），或 LIS3DH 的 WHO_AM_I 没读到 0x33 | 按《IIC 通信》笔记 8.3.3 节的方法排查总线 |
| 数值行有旧数字残留 | 刷新时没有先铺背景色 | 用 `FillRow()`（先 `LCD_Fill` 再 `LCD_ShowString`，见 7.7 节），或把数值格式改成定宽 |
| 字显示成反白 / 镜像 / 倒立 | 字库取模设置与驱动不匹配 | 见 6.3 节自检方法（阴码/阳码、逐行/逐列、顺向/逆向） |
| 改了 CubeMX 重新生成后 LCD 初始化代码丢失 | 代码写在了 CubeMX 管理区 | 自己的驱动放 `lcd.c`、`app_ui.c` 等独立文件，或写在 USER CODE 区 |
| **`printf` 的浮点输出是空串或乱码** | 工程勾了 **Use MicroLIB**，精简版 printf 不支持 `%f` | 改整数定点：`%u.%u` 拼小数、角度取整（7.7 节），或在 Target 选项里取消 MicroLIB |

---

## 10. 本章小结

1. **FSMC 驱动 LCD 的本质是"地址映射"**：配置好 NE1 + A17 + 16 位 + 模式 B 之后，LCD 命令口就是 `0x60000000`、数据口就是 `0x60040000`，用指针赋值即可完成 8080 写时序，软件层面看不到任何 GPIO 操作；
2. **RS 用地址线模拟**：A17=1 为数据、A17=0 为命令；16 位总线下 HADDR 右移一位，偏移位是 (17+1)=18 而不是 17——这是最容易算错的地方；
3. **时序余量要留够**：ILI9341 的 8080 写周期要求 ≥ 66ns，ADDSET=5 / DATAST=15 在 168MHz 下一次 16 位写约 131ns（22 个 HCLK），余量充足；但**"整齐的一条花带"要先去查 MADCTL 的 MV 位，而不是时序**（6.5 节）；
4. **开窗要少、每次多写**：一次开窗（0x2A/0x2B）要花 12 次总线写，所以填充用 `LCD_Fill`、字符按"整字符开一次窗口"来写；`LCD_DrawPoint` 一点一开窗，成本是批量写的 13 倍，只适合零星画点；
5. **显示链路分层**：软件 I2C（PA1/PA0）采集四个传感器 → 数据缓存 → sprintf 格式化 → 字符渲染 → FSMC 写 GRAM，两套子系统引脚不冲突、逻辑解耦，任一侧出问题都能单独定位；
6. **DMA 的正确姿势**：FSMC 不产生 DMA 请求，只能用 **DMA2 内存到内存**把帧缓冲灌进 GRAM；M2M 下"**源 = Peripheral（受 PeriphInc 控制）、目的 = Memory（受 MemInc 控制）**"，故 `PeriphInc = ENABLE`、`MemInc = DISABLE`，且 Mode 必须 Normal；回调要挂在句柄上且完成/出错都要解锁；
7. **关于 DMA 收益要诚实**：本工程刷屏只占 CPU 约 0.4%，DMA 不缩短墙钟时间（FSMC 的 83ns 写周期是硬上限），它的价值在"把搬运藏进 I2C 的 66ms 等待窗口"以及为将来大帧刷新做准备——**判断标准是"刷屏期间 CPU 有没有别的事可做"**；
8. **换屏只改四处**：`LCD_WIDTH/LCD_HEIGHT` 分辨率宏、`LCD_MADCTL`（**绝不能带 MV**）、`LCD_SW_FLIP_X/Y` 方向开关、厂商初始化表 `lcd_vendor_init[]`。**8080 协议、FSMC 地址映射公式、驱动分层与屏的分辨率和控制器都无关**——这就是把"驱动逻辑"和"屏的私有参数"分开写（表驱动）的意义（见 6.4 节表 6-2、6.5 节）。
