# FSMC—驱动 LCD 屏显示（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F4xx 中文数据手册》FSMC 引脚复用表、《RM0090 STM32F407 参考手册》FSMC 章节、《NT35510 数据手册》、野火《STM32 HAL 库开发实战指南——基于霸天虎开发板》第 26 章（FSMC 模拟扩展 SRAM）与第 27 章（LCD 液晶显示）。
> **学习提示**：配合参考手册中 FSMC_BCR1~4、FSMC_BTR1~4、FSMC_BWTR1~4 寄存器的说明一起阅读，效果更佳，特别是 ADDSET / DATAST 时序位与访问模式 A/B/C/D 的部分。
> **特别说明**：本笔记内容以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 STM32 HAL 库。LCD 采用 **4.3 寸电容屏（NT35510 驱动器，8080 并口，RGB565，854×480）**，通过 **FSMC 的 NOR/PSRAM 模式 B** 模拟 8080 时序驱动；显示内容取自《IIC 通信》笔记中挂在 PA1/PA0 软件 I2C 总线上的 **BH1750 光照 / HTU21D 温湿度 / PCF8563 时钟 / LIS3DH 三轴**传感器数据。

---

## 1. LCD 与显示控制器简介

### 1.1 液晶显示器的基本概念

液晶显示器（LCD，Liquid Crystal Display）靠电压改变液晶分子的排列方向来控制背光的透过率，从而显示图像。衡量一块屏的基本参数：

- **像素**：图像的最小单元，一个像素就是一个光点；
- **分辨率**："行像素数 × 列像素数"，如本屏 854×480，即横向 854 个像素、纵向 480 个像素；
- **色彩深度**：每个像素用多少位表示颜色。本屏采用 **RGB565 格式**：红色 5 位、绿色 6 位、蓝色 5 位，共 16 位，即每个像素用 1 个 16 位数据（`uint16_t`）表示，可显示 2¹⁶ = 65536 种颜色；
- **点距**：相邻像素中心的距离，决定屏的精细程度。

### 1.2 显示控制器与 GRAM

单片机不可能自己逐点驱动液晶屏的几百上千个像素引脚，必须由**显示控制器**芯片代劳。本屏集成的控制器是 **NT35510**，它的核心是一块 **GRAM（Graphics RAM，图形存储器）**：

- GRAM 中**每个存储单元对应屏幕上的一个像素**；
- MCU 把像素的 RGB565 颜色值写入 GRAM，NT35510 就**周期性自动刷新屏幕**，MCU 不需要持续干预；
- MCU 通过 **8080 并行接口**向 NT35510 发送**控制命令**（如设置分辨率、开窗坐标）和**像素数据**（写入 GRAM）。

NT35510 可配置成 SPI 接口、8080 接口或 RGB 接口与 MCU 通讯。本屏的 IM[3:0] 配置引脚已在屏内部固定为 **8080 并口、16 位数据线**模式。

### 1.3 8080 并行接口的信号与时序

8080 接口因 Intel 8080 处理器总线而得名，是液晶屏最常见的 MCU 接口。本屏引出的 8080 相关信号如下：

**表 1-1 液晶屏 8080 接口信号说明**

| 信号线 | NT35510 对应 | 说明 |
| --- | --- | --- |
| LCD_DB[15:0] | D[15:0] | 16 位数据线，传输命令与像素数据 |
| LCD_RD | RDX | 读数据信号，低电平有效 |
| LCD_WR | WRX | 写数据信号，低电平有效 |
| LCD_RS | D/CX | 数据/命令选择：高电平 = 传输的是数据，低电平 = 传输的是命令 |
| LCD_CS | CSX | 片选，低电平有效 |
| LCD_RST | RESX | 复位，低电平有效 |
| LCD_BL | — | 背光控制，高电平点亮（可直接由普通 GPIO 控制） |

**写命令的时序过程**：片选 CSX 拉低 → D/CX 拉低（表示接下来是命令）→ WRX 拉低（数据线上出现命令码，NT35510 在 WRX 上升沿锁存）→ 若该命令带参数，则把 D/CX 拉高，继续以同样方式写参数字节 → CSX 拉高结束。

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

写像素数据（填 GRAM）则更简单：CSX 拉低、D/CX 拉高，然后连续往数据线送 RGB565 颜色值即可，NT35510 内部有地址自增，像素会自动按窗口顺序填充。

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

本笔记以野火 F407 霸天虎开发板配套的 4.3 寸屏（NT35510）的接线为准。屏通过板对板插座直接插在开发板的 LCD 座上，所有信号已与 STM32 的 FSMC 引脚对应连接。

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

- 访问的地址让 **A17 = 1** → RS 为高电平 → NT35510 认为传输的是**数据**；
- 访问的地址让 **A17 = 0** → RS 为低电平 → NT35510 认为传输的是**命令**。

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

**验证**：写 `0x60040000` 时，HADDR bit18 = 1 → FSMC_A17 输出高电平 → RS = 高 → NT35510 收到的是数据，正确。若你的板子 RS 接的是 A0，则数据地址 = 0x60000000 | (1 << 1) = 0x60000002，计算方式完全一致。

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

NT35510 数据手册要求：写周期 twc 最短 **66 ns**，读周期（trdl+trod）最短约 **65 ns**。按 ADDSET = 4、DATAST = 4 计算：

```
写周期 twc = ((4+1) + (4+1)) × 5.95 ns ≈ 59.5 ns ……略紧
读周期 trc = ((4+1) + (4+1) + 2) × 5.95 ns ≈ 71.4 ns > 65 ns ✓
```

写周期略低于 66ns 的要求，实测大部分 NT35510 屏仍能正常工作；若出现花屏或白屏，把 **DATAST 加大到 8**（twc ≈ 83ns）就十分稳妥。本笔记代码取 ADDSET = 4、DATAST = 8，留足余量——对秒级刷新传感器数据的应用来说，这点速度差异完全无感。

> **关于这两个式子的说明**：上面是工程上常用的经验式（模式 A / 模式 B 的差别在于读操作是否插入额外的总线周转时间，不同资料写法略有出入）。**对驱动的正确性而言，关键只有一条：时序要留够余量，最终以实测波形为准**——先按 ADDSET = 4、DATAST = 8 配好，能稳定刷屏就不必再抠；出现花屏就加 DATAST（每一步加 2~4），一直加到稳定为止。**DATAST 每加 1 就多约 6ns，加得越多刷屏越慢**：本笔记配置下一次 16 位写周期约 83ns，这也是后文计算"刷一屏要多少 CPU 时间"的基准（854×480 ≈ 41 万像素 × 83ns ≈ 34ms）。

> **排错直觉**：屏幕"能点亮但花屏/颜色错乱"多半是 DATAST 太小、数据还没稳定就被锁存；"完全白屏"多半是 FSMC 根本没配通（先查 NE1 与 A17 的引脚复用）。实测时先用纯色刷屏验证时序，再谈显示内容。

---

## 5. STM32CubeMX 配置工程

### 5.1 新建工程与系统时钟

1. CubeMX 欢迎页 → **New Project**，搜索 `STM32F407VET6`，选 LQFP100 封装；
2. **RCC** → HSE = Crystal/Ceramic Resonator（8MHz 外部晶振）；
3. **Clock Configuration**：PLL 源 HSE，PLL_M=8、PLL_N=336、PLL_P=2，**SYSCLK = 168MHz，HCLK = 168MHz**（FSMC 直接吃 HCLK，这决定了 ADDSET/DATAST 的实际时间）。

### 5.2 配置 FSMC（NOR Flash/PSRAM/SRAM/ROM/LCD）

1. 左侧 **Connectivity → FSMC**，勾选 **Memory type = LCD Interface**；
2. **Chip Select** 选 **NE1**（对应 PD7）；**LCD Register Select** 选 **A17**（对应 PD12）——CubeMX 会自动把 PD14/PD15/PD0/PD1/PE7~PE15/PD8~PD10 配成数据线、PD4=NOE、PD5=NWE、PD7=NE1、PD12=A17，全部 AF12；
3. **Parameter Settings** 按下表填写：

**表 5-1 FSMC Parameter Settings（LCD Interface，NE1 + A17）**

| 配置项                                       | 取值            | 说明                    |
| ----------------------------------------- | ------------- | --------------------- |
| Memory type                               | LCD Interface | 本质就是 NOR 模式 B         |
| LCD Register Select                       | A17           | RS 引脚 = PD12          |
| Data                                      | 16 bits       | RGB565 一像素 16 位       |
| Address setup time in HCLK clock cycles   | 4             | ADDSET = 4            |
| Data setup time in HCLK clock cycles      | 8             | DATAST = 8（见 4.3 节计算） |
| Bus turn around time in HCLK clock cycles | 0             | LCD 不需要               |
| Extended mode                             | Disable       | 读写共用一套时序              |
| Wait                                      | Disable       | NT35510 不接 NWAIT      |
| Write operation                           | Enabled       | 必须使能写，否则只能读           |

4. **NVIC / DMA**：FSMC 本身不产生中断与 DMA 请求，这里**不用勾选**（LCD 的 DMA 在第 8 章用 DMA2 内存到内存方式单独配置）。

> **关于配置时可能出现的警告**：勾选 NE1 后，CubeMX 有时会在 FSMC 一栏给出 *Partly disabled conflict with … NE1 Chip Select* 之类的黄色提示。它的含义是"FSMC 占用的一批 GPIO（PD/PE 口的 AF12 引脚）原本还复用着别的外设功能，那部分功能已被自动禁用"，属于**提示而非错误**。核对方法：按 Ctrl+D 看冲突明细，只要冲突的另一方是你用不到的外设（如 ETH、SDIO、其它 USART），且 Pinout 视图里本笔记用到的脚（PD7 = NE1、PD12 = A17、PD4/PD5 = NOE/NWE、PD14/PD15/PD0/PD1/PE7~PE15/PD8~PD10 = 数据线、PD2 = 背光）都不是"硬冲突"，就可以放心忽略。反之若冲突方是你确实要用的外设（如想用 PD8/PD9 做 USART3），就必须给那个外设换到别的引脚。

### 5.3 配置背光 PD2 与软件 I2C 总线

1. **System Core → GPIO** → 点击 **PD2**，选 **GPIO_Output**；参数：Output level = Low（先关背光）、**Output Push-Pull**、Pull-up、Very High，User Label 填 `LCD_BL`；
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

  Timing.AddressSetupTime      = 4;    /* ADDSET：地址建立，4 个 HCLK ≈ 23.8ns */
  Timing.AddressHoldTime       = 15;   /* 模式 B 下无效，随意 */
  Timing.DataSetupTime         = 8;    /* DATAST：数据建立，8 个 HCLK ≈ 47.6ns */
  Timing.BusTurnAroundDuration = 0;
  Timing.CLKDivision           = 16;   /* 异步模式无效，随意 */
  Timing.DataLatency           = 17;   /* 异步模式无效，随意 */
  Timing.AccessMode            = FSMC_ACCESS_MODE_B;  /* 模式 B 模拟 8080 */

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
main.c                  ← 主循环：读传感器 → 刷新 LCD 显示
├── bsp_soft_i2c.c/h        ← 软件 I2C 时序层（直接复用《IIC 通信》笔记第 8 章）
├── bsp_sensor_io.c/h       ← 传感器访问原语（复用《IIC 通信》笔记代码清单 9-1）
├── bsp_bh1750/htu21d/…     ← 器件层（复用《IIC 通信》笔记 9.2.3 节）
├── bsp_lcd.c/h             ← LCD 底层：初始化、开窗、画点、刷屏
└── lcd_dma.c/h             ← DMA 刷帧缓冲（第 8 章）
```

### 6.2 LCD 底层驱动

列表 3: 代码清单 6-1 LCD 底层接口（bsp_lcd.h）

```c
#ifndef __BSP_LCD_H
#define __BSP_LCD_H

#include "stm32f4xx_hal.h"

/* ---------- FSMC 地址宏（计算过程见第 4.2 节） ---------- */
#define FSMC_LCD_BASE      ((uint32_t)0x60000000U)        /* NE1 区域1 基地址 */
#define LCD_CMD_ADDR       (FSMC_LCD_BASE)                /* A17=0：命令 */
#define LCD_DATA_ADDR      (FSMC_LCD_BASE | (1UL << 18))  /* A17=1：数据 */

#define LCD_WRITE_CMD(c)   (*(__IO uint16_t *)(LCD_CMD_ADDR)  = (uint16_t)(c))
#define LCD_WRITE_DATA(d)  (*(__IO uint16_t *)(LCD_DATA_ADDR) = (uint16_t)(d))

/* ---------- 屏幕参数（横屏 854×480） ---------- */
#define LCD_WIDTH    854
#define LCD_HEIGHT   480

/* ---------- RGB565 常用颜色 ---------- */
#define WHITE   0xFFFF
#define BLACK   0x0000
#define RED     0xF800
#define GREEN   0x07E0
#define BLUE    0x001F
#define YELLOW  0xFFE0

/* ---------- 配色约定：白底黑字，与 main.c 的刷新逻辑保持一致 ---------- */
#define LCD_BG_COLOR   WHITE
#define LCD_FG_COLOR   BLACK

/* ---------- 字库：8×16 点阵，ASCII 0x20~0x7E 共 95 个字符 ----------
   由取模软件（PCtoLCD2002，设置"阴码、逐行式、顺向、十六进制"）生成，
   存为 font_asc2_1608.c；每个字符 16 字节（高字节在上、MSB 在左） */
extern const uint8_t asc2_1608[95][16];

/* ---------- 背光：PD2，高电平点亮 ---------- */
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

#endif
```

列表 4: 代码清单 6-2 NT35510 初始化与基本绘图（bsp_lcd.c）

```c
#include "bsp_lcd.h"

/**
  * @brief  厂商专用初始化表：一条命令 + 若干个参数
  * @note   NT35510 这类控制器都有一大段"电源/伽马/时序"私有寄存器，
  *         必须以屏厂随屏资料给出的序列为准逐条填入。这里用"命令 + 参数数组"的
  *         表结构描述它，好处是新增/删除条目时不必改动任何逻辑代码。
  *         下面第一条只是用来演示表结构的写法（NT35510 的 CMD2 页选择），
  *         实际工程请把屏厂序列的每一条都照抄成一行。
  */
typedef struct {
  uint16_t cmd;
  uint8_t  nArgs;
  uint16_t args[10];
} lcd_cmd_t;

static const lcd_cmd_t lcd_vendor_init[] = {
  /* {命令, 参数个数, {参数...}} —— 示例：进入厂商寄存器页（CMD2EN） */
  {0xF000, 5, {0x55, 0xAA, 0x52, 0x08, 0x01}},
  /* ……其余电源、伽马、时序条目按屏厂资料逐行填入…… */
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
  * @brief  NT35510 寄存器初始化：厂商序列 + 标准 DCS 命令
  * @note   标准命令（0x3A/0x36/0x11/0x29）是 MIPI DCS 规范定义的，
  *         任何一家屏都通用；厂商序列只影响画质（伽马、电压），
  *         即使暂时没有屏厂资料，靠这几条标准命令也能点亮出基本画面
  */
static void LCD_REG_Config(void)
{
  LCD_WRITE_CMD(0x01);                     /* 软件复位 */
  HAL_Delay(120);                          /* 手册要求复位后等待 */

  LCD_WriteCmdList(lcd_vendor_init,
                   sizeof(lcd_vendor_init) / sizeof(lcd_vendor_init[0]));

  LCD_WRITE_CMD(0x3A);  LCD_WRITE_DATA(0x55);   /* 像素格式 = RGB565（16bit/pixel） */
  LCD_WRITE_CMD(0x36);  LCD_WRITE_DATA(0x60);   /* MADCTL 显示方向：0x00 竖屏 / 0x60 横屏 */
  LCD_WRITE_CMD(0x11);                          /* Sleep Out */
  HAL_Delay(120);
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
  * @note   开窗后连续写像素，NT35510 内部地址自动递增；越界参数直接丢弃，
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
  x2 = x + w - 1;
  y2 = y + h - 1;

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
  LCD_Fill(0, 0, LCD_WIDTH, LCD_HEIGHT, color);
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
  for (row = 0; row < 16; row++)
  {
    data = font[row];                      /* 一行 8 个像素，MSB 在左 */
    for (bit = 0; bit < 8; bit++)
    {
      LCD_WRITE_DATA((data & (0x80 >> bit)) ? color : bgcolor);
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
```

**要点分析**：

- `LCD_WRITE_DATA()` 一行 C 代码背后就是一次完整的 FSMC 写周期（NE1 拉低、A17=1、NWE 脉冲，约 83ns），**命令与数据的区别完全由地址决定**，代码里看不到任何电平操作；
- **开窗是一次"贵"操作**（12 次总线写），所以驱动设计的核心原则是"**尽量少开窗、每次多写**"：`LCD_Fill()` 一次开窗写几万个像素；`LCD_ShowChar()` 按字符开窗；只有 `LCD_DrawPoint()` 这种零星场合才"一点一开窗"，它比批量写慢约 13 倍——用它画整屏会明显卡顿；
- `LCD_Fill()` 整屏 409920 个像素 × 83ns ≈ **34ms**，且全程占用 CPU——这正是第 8 章引入 DMA 的动机；
- 字库文件 `font_asc2_1608.c` 由取模软件生成（PCtoLCD2002：阴码、逐行式、顺向、十六进制），是一个 `const uint8_t asc2_1608[95][16]` 的常量数组，不占用 RAM、直接放在 Flash 里；也可以用屏厂/教程自带的字库文件，只要点阵格式与 `LCD_ShowChar()` 的取模顺序一致即可；
- 全部显示函数都做了边界裁剪，传错坐标时最多"不显示"，不会把 GRAM 写成乱码。

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
> 所以本笔记第 7 章的 main.c 只做两件事：`#include` 这四个头文件，然后调用——**应用层不重复声明也不重复实现驱动层**。看到 `LIS3DH_Init()`、`PCF8563_IsTimeValid()` 不必去本笔记里找定义，直接看《IIC 通信》笔记即可。移植时把 6 个驱动文件（`bsp_soft_i2c`、`bsp_sensor_io`、`bsp_bh1750`、`bsp_htu21d`、`bsp_pcf8563`、`bsp_lis3dh`）与本笔记的 `bsp_lcd`、`lcd_dma` 一起加入工程就能编译。

核心约定：主循环每 1 秒采集一轮传感器数据，`sprintf` 格式化后**整行重写**（先铺背景色、再画字符）到 LCD 的固定行。整行重写比"精确擦除差异位"简单得多，且天然不会残留旧字符。

### 7.2 编程要点

1. **一轮采集 ≈ 70ms**：HTU21D 在 No Hold 模式下每次测量要主机自己等（温度 50ms、湿度 16ms），BH1750 用的是连续测量模式、随时读都是最新值，PCF8563/LIS3DH 都是即读即得。这 70ms 是 `HAL_Delay()` 空转，**正好可以让 DMA 刷屏与它并行**（见第 8 章）——这是本工程里 DMA 收益最实在的一处；
2. **整行重写、先铺背景**：每行刷新时先用 `LCD_Fill()` 铺一遍背景色再画字符串，避免"新数值比旧数值短、尾巴残留旧数字"的经典问题（例如光照从 `1234.5` 掉到 `9.8`，若不清背景，屏幕上会留下 `9.8` 后面半截旧数字）。若想减少写入量，可把标签与数值分区：标签画一次不再动，数值区用**定宽格式**（`%7.1f`、`%6d`）保证每次宽度相同；
3. **别用 CPU 阻塞写把采集流程切开**：软件 I2C 采集期间 CPU 是满负荷的，中间插一段 `LCD_Fill`/`LCD_ShowString` 只会拉长采集时间。刷新只有两种合理姿势：① 采集完成后一次性刷完（第 6 章的方式，简单直接）；② 用第 8 章的 DMA 在 `HAL_Delay()` 等待窗口里发起（异步搬运，CPU 不参与）——**注意二者的区别是"谁在执行"，不是"什么时候做"**；
4. **软件 I2C 与 LCD 无硬件冲突**：软件 I2C 用 PA0/PA1 两个普通 GPIO，FSMC 用 PD/PE 口的 AF12 引脚，互不干扰——这是"FSMC + 软件 I2C"组合比"SPI 屏 + 硬件 I2C"更省心的地方；
5. **把传感器状态画到屏上**：`LIS3DH_Init()` 的返回值、`PCF8563_IsTimeValid()` 的结果都直接显示出来，"哪个模块没接好"一眼可见，不必连串口。

### 7.3 代码分析

列表 5: 代码清单 7-1 传感器数据显示主程序（main.c 的 USER CODE 区）

```c
#include "bsp_lcd.h"
#include "bsp_soft_i2c.h"
#include "bsp_sensor_io.h"
#include "bsp_bh1750.h"
#include "bsp_htu21d.h"
#include "bsp_pcf8563.h"
#include "bsp_lis3dh.h"
#include <stdio.h>

/* 显示布局：顶部一行标题独占，其下 5 行数据；字符高 16 像素、行距 24 像素 */
#define ROW_TIME    0
#define ROW_LUX     1
#define ROW_TEMP    2
#define ROW_HUM     3
#define ROW_ACC     4

#define ROW_X       8                       /* 行起始 x 坐标 */
#define ROW_W       320                     /* 每行刷新区域宽度（= 40 字符） */
#define ROW_H       16                      /* 字高 */
#define TITLE_Y     8                       /* 标题行 y 坐标：独占顶部，不被数据刷新覆盖 */
#define ROW_Y(r)    (48 + (r) * 24)         /* 数据行 y 坐标：上方 40 像素留给标题 */

/* 刷新一行：先铺背景色彻底清掉旧内容，再写新字符串 */
static void LCD_RefreshRow(uint8_t row, const char *str)
{
  LCD_Fill(ROW_X, ROW_Y(row), ROW_W, ROW_H, LCD_BG_COLOR);
  LCD_ShowString(ROW_X, ROW_Y(row), ROW_W, LCD_FG_COLOR, LCD_BG_COLOR, str);
}

/* 画标题：只在上电时画一次；数据行从 y=48 起，不会覆盖它 */
static void LCD_DrawTitle(void)
{
  LCD_ShowString(ROW_X, TITLE_Y, ROW_W, LCD_FG_COLOR, LCD_BG_COLOR,
                 "----- I2C Sensor Monitor -----");
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
  LCD_Init();                  /* LCD 复位 + NT35510 配置 + 清屏 + 开背光 */

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

  /* RTC 掉电时在标题右侧提示一次（标题行不会被数据刷新覆盖，所以只画一次） */
  if (rtcLost)
  {
    LCD_ShowString(ROW_X + 248, TITLE_Y, 96, LCD_FG_COLOR, LCD_BG_COLOR, "[RTC RESET]");
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
- 每次刷新一行 = 铺背景（320×16 = 5120 像素）+ 写字符（33 字符 × 128 像素 ≈ 4224 像素），共约 9300 次 FSMC 写 ≈ **0.8ms**；5 行合计约 4ms/秒，CPU 占用约 0.4%——**这也是"要不要为刷屏上 DMA"的判断依据：本工程 DMA 省下的 CPU 时间只有几毫秒/秒，收益有限，真正的价值在"把这 4ms 藏进 I2C 的等待里"以及将来做波形/图片显示时的可扩展性**（见第 8 章）；
- **注意"每行都铺背景"与"写入量"的权衡**：`LCD_ShowChar()` 本身就会写满每个字符格子（包括笔画之间的背景像素），所以 `LCD_Fill()` 其实是"防残留"的双保险——它的作用是盖住**字符串尾部之外**的区域（例如 Acc 行从 `LIS3DH NOT FOUND` 变成正常数值后，尾巴会短一截）。如果每行的字符串宽度恒定（`%7.1f`、`%6d` 这类定宽格式），就可以省掉 `LCD_Fill()`，写入量直接减半；反过来，一旦有"某行整体变短"的情况（如上面这种状态切换），就必须保留清背景；
- 若个别传感器未接，屏幕上会显示负数或 `NOT FOUND`，一眼能看出来——这比"黑屏"友好得多。

---

## 8. CPU 占用优化与 DMA 刷屏

### 8.1 CPU 占用分析

本应用中 CPU 的开销主要有三块：

**表 8-1 每秒的 CPU 开销（按 168MHz、FSMC 一次 16 位写约 83ns 估算）**

| 环节 | 耗时量级 | 能否优化 |
| --- | --- | --- |
| 软件 I2C 采集一轮（4 个传感器） | ≈70ms / 秒，其中约 66ms 是 HTU21D No Hold 模式下的 `HAL_Delay()` 空转 | 等待期间 CPU 完全空闲，**正好可以让 DMA 刷屏并行填进去**（见 8.5 节）；要彻底降下来只能把总线改到 PB8/PB9 用硬件 I2C + DMA 收数（《IIC 通信》笔记第 7 章） |
| 逐行刷屏（5 行 × 320×16 区域 ≈ 4.7 万次 FSMC 写） | ≈4ms / 秒（约占 CPU 的 0.4%） | **DMA 可接管**（见 8.2） |
| `sprintf` 格式化 | 几十 µs | 可忽略 |

**先给个结论**：以本工程每秒刷 5 行的规模，刷屏只占 CPU 的 0.4%，**"为了省这 4ms 而上 DMA"本身收益很小**。DMA 在这里的真正价值有两处：

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
> - **自增位要按这个映射来配**：`PeriphInc`（PINC）控制的是 **PAR 即源地址** → 必须 **ENABLE**（帧缓冲要逐个像素往后走）；`MemInc`（MINC）控制的是 **M0AR 即目的地址** → 必须 **DISABLE**（LCD 数据口地址固定不动，像素地址递增由 NT35510 内部完成）。
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

列表 6: 代码清单 8-1 DMA 刷屏驱动（lcd_dma.h / lcd_dma.c）

```c
/* lcd_dma.h */
#ifndef __LCD_DMA_H
#define __LCD_DMA_H

#include "bsp_lcd.h"

/* 一行文字区域的帧缓冲尺寸（像素） */
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

列表 7: 代码清单 8-2 用 DMA 显示一行文字（先在 RAM 里渲染，再整块灌屏）

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

**两种方式的量化对比**（刷新一行 320×16）：

| 方式 | 墙钟耗时 | CPU 占用 | 说明 |
| --- | --- | --- | --- |
| 逐点 `LCD_DrawPoint` | 约 5~6ms | 约 5~6ms | 每像素一次开窗，开销 13 倍，最差 |
| 按字符开窗 `LCD_ShowString` | 约 0.8ms | 约 0.8ms | 本笔记第 6 章的默认实现，性价比最高 |
| 渲染 + DMA | 约 0.8ms（渲染 0.3ms + 搬运 0.5ms） | **约 0.3ms** | 墙钟时间几乎不变，但其中 0.5ms 可与 I2C 等待重叠 |

> **结论**：墙钟时间由 FSMC 写周期决定（16 位写 83ns，谁也绕不过），DMA 改变的是"这 0.5ms 由谁在执行"。**所以判断要不要用 DMA 的标准是："刷屏期间 CPU 有没有别的事可做"**——本工程有（I2C 的 66ms 等待），所以值得；如果主循环刷完屏就没事干，用不用都一样。

> **进阶方向**：若做波形显示/图片显示等大帧刷新，可把帧缓冲设为整行或半屏，配合 DMA 双缓冲交替渲染与推送，CPU 占用可再降一个数量级。整屏 854×480×2B = 800KB 超过 F407 的 192KB 内部 SRAM，所以**整屏帧缓冲放不下**，必须分行/分块——这也是为什么"局部刷新 + DMA 分行"是 F407 + 大屏的标配姿势。

---

## 9. 下载验证与常见问题

### 9.1 验证步骤

1. 编译下载：屏幕先黑一下（背光关 → 寄存器配置 → 清屏），随后点亮，顶部一行标题、其下五行数值；
2. **用手遮住 BH1750**，Lux 行数值应明显下降；手电照射升至上千 lx；
3. **对着 HTU21D 哈气**，湿度行明显上升；
4. **翻转/侧立开发板**，Acc 行的 X/Y/Z 数值随之变化，静止平放时某轴约 ±1000；
5. Time 行每秒递增（PCF8563 装了纽扣电池时断电后仍走时）；若模块没装电池，上电时标题行右侧会出现 `[RTC RESET]`，说明程序检测到掉电并写入了一个初始时间（代码清单 7-1 里给的是 2026-10-07 12:30:00），随后时间从该点继续走；
6. **拔掉某个模块再上电**：BH1750/HTU21D 行会显示负值，Acc 行显示 `LIS3DH NOT FOUND`——这验证了"自检信息画到屏上"的设计。

### 9.2 常见问题速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| 完全白屏、无任何显示 | FSMC 未配通（NE1/A17 引脚复用错、未使能写） | 检查 CubeMX 中 FSMC 的 NE1、Register Select=A17、Write Operation=Enabled；检查 DATAST 是否过小 |
| 花屏、颜色错乱、随机色块 | DATAST/ADDSET 太小，数据未稳定即锁存 | DATAST 从 4 逐步加大到 8~15；确认 HCLK 确实是 168MHz |
| 显示内容全是"命令"效果（如全屏一种异常色） | 命令/数据地址搞反（A17 偏移算错） | 数据地址必须是基地址 \| (1<<18)，不是 \| (1<<17) |
| DMA 灌屏后整行只有一种颜色 / 花屏 | **M2M 模式下自增位配反**：源（PeriphInc）应自增、目的（MemInc）应固定 | 改为 `PeriphInc = ENABLE`、`MemInc = DISABLE`，并核对 `HAL_DMA_Start_IT(源, 目的, 个数)` 的实参顺序 |
| DMA 刷了一次之后屏幕再也不动 | 出错回调没清零 `dma_busy`（或被 `dma_busy` 挡住后一直返回 HAL_BUSY） | 在 `XferErrorCallback` 里同样清零；确认回调是挂在句柄上而不是"重定义库函数" |
| 编译报 multiple definition: `DMA2_Stream0_IRQHandler` | CubeMX 的 MemToMem 已生成一份中断转发，又手写了一份 | 删掉其中一份；走 CubeMX 生成时把回调挂到 CubeMX 的句柄上即可 |
| 想同时用 ADC 采集时 DMA 冲突 | 《ADC 采集配置》笔记里 ADC1 也用 DMA2 Stream0 | 给其中一个换 Stream（如 LCD 用 Stream1），或复用同一流分时启动 |
| 背光不亮但实测 FSMC 读写正常 | PD2 未配成输出或电平反了 | 查 MX_GPIO_Init 中 PD2；用万用表量 PD2 电平 |
| 传感器数据全是 -1 / 显示 NOT FOUND | 软件 I2C 总线不通（上拉电阻、PA0/PA1 接线），或 LIS3DH 的 WHO_AM_I 没读到 0x33 | 按《IIC 通信》笔记 8.3.3 节的方法排查总线 |
| 数值行有旧数字残留 | 刷新时没有先铺背景色 | 用本笔记的 `LCD_RefreshRow`（先 `LCD_Fill` 再写字符串），或把数值格式改成定宽 |
| 改了 CubeMX 重新生成后 LCD 初始化代码丢失 | 代码写在了 CubeMX 管理区 | 自己的驱动放 bsp_lcd.c 等独立文件，或写在 USER CODE 区 |

---

## 10. 本章小结

1. **FSMC 驱动 LCD 的本质是"地址映射"**：配置好 NE1 + A17 + 16 位 + 模式 B 之后，LCD 命令口就是 `0x60000000`、数据口就是 `0x60040000`，用指针赋值即可完成 8080 写时序，软件层面看不到任何 GPIO 操作；
2. **RS 用地址线模拟**：A17=1 为数据、A17=0 为命令；16 位总线下 HADDR 右移一位，偏移位是 (17+1)=18 而不是 17——这是最容易算错的地方；
3. **时序余量要留够**：NT35510 写周期最短 66ns，ADDSET=4/DATAST=8 在 168MHz 下一次 16 位写约 83ns，稳妥可靠；花屏先加 DATAST；
4. **开窗要少、每次多写**：一次开窗（0x2A/0x2B）要花 12 次总线写，所以填充用 `LCD_Fill`、字符按"整字符开一次窗口"来写；`LCD_DrawPoint` 一点一开窗，成本是批量写的 13 倍，只适合零星画点；
5. **显示链路分层**：软件 I2C（PA1/PA0）采集四个传感器 → 数据缓存 → sprintf 格式化 → 字符渲染 → FSMC 写 GRAM，两套子系统引脚不冲突、逻辑解耦，任一侧出问题都能单独定位；
6. **DMA 的正确姿势**：FSMC 不产生 DMA 请求，只能用 **DMA2 内存到内存**把帧缓冲灌进 GRAM；M2M 下"**源 = Peripheral（受 PeriphInc 控制）、目的 = Memory（受 MemInc 控制）**"，故 `PeriphInc = ENABLE`、`MemInc = DISABLE`，且 Mode 必须 Normal；回调要挂在句柄上且完成/出错都要解锁；
7. **关于 DMA 收益要诚实**：本工程刷屏只占 CPU 约 0.4%，DMA 不缩短墙钟时间（FSMC 的 83ns 写周期是硬上限），它的价值在"把搬运藏进 I2C 的 66ms 等待窗口"以及为将来大帧刷新做准备——**判断标准是"刷屏期间 CPU 有没有别的事可做"**。
