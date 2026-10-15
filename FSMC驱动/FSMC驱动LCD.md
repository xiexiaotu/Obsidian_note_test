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
#define FSMC_LCD_BASE      ((uint32_t)0x60000000)   /* NE1 区域1 基地址 */
#define LCD_CMD_ADDR       (FSMC_LCD_BASE)          /* A17=0：命令 */
#define LCD_DATA_ADDR      (FSMC_LCD_BASE | (1UL << 18))  /* A17=1：数据 */

#define LCD_WRITE_CMD(c)   (*(__IO uint16_t *)(LCD_CMD_ADDR)  = (uint16_t)(c))
#define LCD_WRITE_DATA(d)  (*(__IO uint16_t *)(LCD_DATA_ADDR) = (uint16_t)(d))

/* ---------- 屏幕参数 ---------- */
#define LCD_WIDTH    854     /* 横屏分辨率 854×480 */
#define LCD_HEIGHT   480

/* ---------- RGB565 常用颜色 ---------- */
#define WHITE   0xFFFF
#define BLACK   0x0000
#define RED     0xF800
#define GREEN   0x07E0
#define BLUE    0x001F
#define YELLOW  0xFFE0

/* ---------- 背光与复位 ---------- */
#define LCD_BL_ON()    HAL_GPIO_WritePin(GPIOD, GPIO_PIN_2, GPIO_PIN_SET)   /* PD2 高电平点亮 */
#define LCD_BL_OFF()   HAL_GPIO_WritePin(GPIOD, GPIO_PIN_2, GPIO_PIN_RESET)

void LCD_Init(void);
void LCD_OpenWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h);
void LCD_SetCursor(uint16_t x, uint16_t y);
void LCD_DrawPoint(uint16_t x, uint16_t y, uint16_t color);
void LCD_Fill(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color);
void LCD_Clear(uint16_t color);

#endif
```

列表 4: 代码清单 6-2 NT35510 初始化与基本绘图（bsp_lcd.c）

```c
#include "bsp_lcd.h"

/**
  * @brief  NT35510 寄存器初始化序列
  * @note   这段"命令 + 参数"序列由屏厂给出，含义包括：
  *         解除命令保护、配置内部电源/伽马/时序参数、设置 RGB565 像素格式、
  *         设置显示方向（0x36）、开显示（0x29）等。
  *         逐条含义可查《NT35510 数据手册》对应寄存器，工程上直接照抄即可。
  */
static void LCD_REG_Config(void)
{
  /* 解除写保护（CMD page select） */
  LCD_WRITE_CMD(0xF000); LCD_WRITE_DATA(0x55);
  LCD_WRITE_DATA(0xAA);  LCD_WRITE_DATA(0x52);
  LCD_WRITE_DATA(0x08);  LCD_WRITE_DATA(0x01);

  /* ……（其余电源、伽马、时序寄存器序列按屏厂资料照抄，共数十条，此处省略）…… */

  /* 像素格式：RGB565（COLMOD = 0x3A，参数 0x55 = 16bit/pixel） */
  LCD_WRITE_CMD(0x3A);   LCD_WRITE_DATA(0x55);

  /* 显示方向（MADCTL = 0x36）：0x00 竖屏 / 0x60 横屏，按安装方向调整 */
  LCD_WRITE_CMD(0x36);   LCD_WRITE_DATA(0x60);

  /* 开显示 */
  LCD_WRITE_CMD(0x11);   /* Sleep Out */
  HAL_Delay(120);        /* 手册要求退睡眠后至少等 120ms */
  LCD_WRITE_CMD(0x29);   /* Display ON */
}

/**
  * @brief  LCD 总初始化：硬件复位 → FSMC 已就绪 → 寄存器配置 → 开背光
  * @note   调用前必须已完成 MX_FSMC_Init() 与 MX_GPIO_Init()
  */
void LCD_Init(void)
{
  LCD_BL_OFF();            /* 先关背光，避免初始化期间看到乱码 */
  HAL_Delay(10);           /* 若 RST 接了 SYS_RSTA，系统复位已完成屏幕复位；
                              否则在此对 RST GPIO 输出 10ms 低电平再拉高 */
  LCD_REG_Config();
  LCD_Clear(BLACK);
  LCD_BL_ON();             /* 初始化完成，点亮背光 */
}

/**
  * @brief  开显示窗口：设置 GRAM 写入的坐标范围（命令 0x2A/0x2B）
  * @note   窗口内像素地址自动递增，开窗后连续写像素即可逐点填充
  */
void LCD_OpenWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
  LCD_WRITE_CMD(0x2A);                 /* 设置 X 坐标范围 */
  LCD_WRITE_DATA(x >> 8);
  LCD_WRITE_DATA(x & 0xFF);
  LCD_WRITE_DATA((x + w - 1) >> 8);
  LCD_WRITE_DATA((x + w - 1) & 0xFF);

  LCD_WRITE_CMD(0x2B);                 /* 设置 Y 坐标范围 */
  LCD_WRITE_DATA(y >> 8);
  LCD_WRITE_DATA(y & 0xFF);
  LCD_WRITE_DATA((y + h - 1) >> 8);
  LCD_WRITE_DATA((y + h - 1) & 0xFF);
}

/**
  * @brief  在窗口内填充单一颜色
  */
void LCD_Fill(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color)
{
  uint32_t total = (uint32_t)w * h;

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

void LCD_DrawPoint(uint16_t x, uint16_t y, uint16_t color)
{
  if (x >= LCD_WIDTH || y >= LCD_HEIGHT) return;
  LCD_OpenWindow(x, y, 1, 1);
  LCD_WRITE_CMD(0x2C);
  LCD_WRITE_DATA(color);
}
```

**要点分析**：

- `LCD_WRITE_DATA()` 一行 C 代码背后就是一次完整的 FSMC 写周期（NE1 拉低、A17=1、NWE 脉冲），**命令与数据的区别完全由地址决定**，代码里看不到任何电平操作；
- `LCD_Fill()` 里的 `while` 循环是 CPU 占用大户：854×480 整屏 409920 个像素，逐点用 CPU 写要花几十毫秒——这正是第 8 章引入 DMA 的原因；
- 字符/字符串显示函数（取模点阵逐点画点）篇幅所限不展开，工程上直接移植屏厂配套字库即可，底层就是 `LCD_DrawPoint()`。

---

## 7. 在 LCD 上显示 IIC 传感器数据

### 7.1 整体思路

《IIC 通信》笔记中，BH1750（光照）、HTU21D（温湿度）、PCF8563（时钟）、LIS3DH（三轴）四个传感器挂在 **PA1(SCL)/PA0(SDA) 软件 I2C 总线**上。本章不重复讲解 I2C 驱动代码（直接复用该笔记第 8、9 章的 `bsp_soft_i2c.c`、`bsp_sensor_io.c` 及各器件驱动），只讲**数据如何流到屏幕上**：

```
传感器 ──软件I2C──> 器件驱动 Read 函数 ──> 全局数据缓存 ──> 格式化字符串 ──> LCD 字符显示函数 ──> FSMC 写 GRAM
```

核心约定：主循环每 1 秒采集一轮传感器数据存入结构体，然后用 `sprintf` 格式化、`LCD_ShowString()` 在固定行显示。**为了避免整屏清屏造成的闪烁，只刷新数值区域**（先用背景色填充该矩形区域，再画字符）。

### 7.2 编程要点

1. **数据采集与显示刷新分离**：BH1750 测量需 120ms、HTU21D 需 16~50ms，加上软件 I2C 全程占用 CPU，一轮采集约 200ms——这期间不要碰 LCD；采集完一次性刷新；
2. **只刷数值、不刷标题**：标题文字（"光照 lx"）只在 `LCD_Init()` 后画一次，循环里仅更新数值行，屏幕完全不闪；
3. **数值变化才去写屏**：可再进一步加"与上一帧相同则跳过"，降低 FSMC 写次数；
4. **软件 I2C 与 LCD 无硬件冲突**：软件 I2C 用 PA0/PA1 两个普通 GPIO，FSMC 用 PD/PE 口的 AF12 引脚，互不干扰——这是"FSMC + 软件 I2C"组合比"SPI 屏 + 硬件 I2C"更省心的地方。

### 7.3 代码分析

列表 5: 代码清单 7-1 传感器数据显示主程序（main.c 的 USER CODE 区）

```c
#include "bsp_lcd.h"
#include "bsp_soft_i2c.h"
#include "bsp_bh1750.h"
#include "bsp_htu21d.h"
#include "bsp_pcf8563.h"
#include "bsp_lis3dh.h"
#include <stdio.h>

/* 显示用的行号约定（字符高 16 像素，行距 24 像素） */
#define ROW_TIME    0
#define ROW_LUX     1
#define ROW_TEMP    2
#define ROW_HUM     3
#define ROW_ACC     4

/* 在固定行刷新一段文字：先用背景色盖掉旧值，再写新字符串 */
static void LCD_RefreshRow(uint8_t row, const char *str)
{
  LCD_ShowString(8, 8 + row * 24, LCD_WIDTH - 16, 16, 16, (char *)str);
  /* LCD_ShowString 内部：对字符点阵逐位 LCD_DrawPoint，背景色填非笔画像素 */
}

int main(void)
{
  float lux, temp, hum;
  short acc[3];
  PCF8563_Time_t now;
  char buf[48];

  HAL_Init();
  SystemClock_Config();        /* 168MHz，HCLK=168MHz 供 FSMC */
  MX_GPIO_Init();              /* 含 PD2 背光、PA1/PA0 软件I2C 开漏 */
  MX_FSMC_Init();              /* NE1 + A17，模式B，16位 */
  MX_USART1_UART_Init();       /* 可选：串口同步打印便于对照 */

  I2C_Init();                  /* 软件 I2C 总线空闲 */
  LCD_Init();                  /* LCD 复位 + NT35510 寄存器配置 + 开背光 */

  /* ---------- 传感器初始化（与 IIC 笔记 9.2.3 节相同） ---------- */
  BH1750_Init();
  HTU21D_Init();
  LIS3DH_Init();

  /* ---------- 画静态标题（只画一次，此后循环不清屏） ---------- */
  LCD_Clear(WHITE);
  LCD_ShowString(8, 8 + ROW_TIME * 24, 300, 16, 16, "Time : --:--:--");
  LCD_ShowString(8, 8 + ROW_LUX  * 24, 300, 16, 16, "Lux  : -----.- lx");
  LCD_ShowString(8, 8 + ROW_TEMP * 24, 300, 16, 16, "Temp : ---.-- C");
  LCD_ShowString(8, 8 + ROW_HUM  * 24, 300, 16, 16, "Humi : ---.-- %RH");
  LCD_ShowString(8, 8 + ROW_ACC  * 24, 300, 16, 16, "Acc  : X=---- Y=---- Z=----");

  while (1)
  {
    /* 1. 一轮采集（软件 I2C，约 200ms，CPU 占用集中在这一段） */
    lux  = BH1750_ReadLux();
    temp = HTU21D_ReadTemp();
    hum  = HTU21D_ReadHumidity();
    PCF8563_ReadTime(&now);
    LIS3DH_ReadAcc(acc);

    /* 2. 逐行刷新数值（sprintf 格式化到字符串，再刷屏） */
    sprintf(buf, "Time : 20%02d-%02d-%02d %02d:%02d:%02d",
            now.year, now.month, now.day, now.hour, now.min, now.sec);
    LCD_RefreshRow(ROW_TIME, buf);

    sprintf(buf, "Lux  : %7.1f lx", lux);
    LCD_RefreshRow(ROW_LUX, buf);

    sprintf(buf, "Temp : %7.2f C", temp);
    LCD_RefreshRow(ROW_TEMP, buf);

    sprintf(buf, "Humi : %7.2f %%RH", hum);
    LCD_RefreshRow(ROW_HUM, buf);

    sprintf(buf, "Acc  : X=%6d Y=%6d Z=%6d", acc[0], acc[1], acc[2]);
    LCD_RefreshRow(ROW_ACC, buf);

    HAL_Delay(800);            /* 采集约耗 200ms，凑整 1 秒一轮 */
  }
}
```

**分析**：

- 数据链路是"**器件驱动 → float/结构体 → sprintf → LCD_ShowString → LCD_DrawPoint → FSMC 写 GRAM**"，I2C 与 LCD 完全解耦，任何一边出问题都能单独定位；
- `LCD_ShowString()` 是标准的取模显示函数（网上任一 STM32 LCD 教程都有），内部对非笔画像素填背景色，因此重复刷新同一行无需先清屏；
- 若个别传感器未接，相应 Read 函数返回值会停在物理不合理处（如 BH1750 返回 -1），屏幕上会显示负值，一眼能看出来——这比"黑屏"友好得多。

---

## 8. CPU 占用优化与 DMA 刷屏

### 8.1 CPU 占用分析

本应用中 CPU 的开销主要有三块：

| 环节 | 耗时量级 | 能否优化 |
| --- | --- | --- |
| 软件 I2C 采集一轮（4 个传感器） | ~200ms / 秒 | 软件 I2C 本质是 CPU 翻转 GPIO，**只能用改硬件 I2C（PB8/PB9）或拉长采集周期来降** |
| 逐点写 LCD 数值字符（5 行 × 约 30 字符） | 每字符 12×16=192 像素，共约 3 万像素 × 一次 FSMC 写 | **DMA 可接管**（见 8.2） |
| sprintf 格式化 | 几十 µs | 可忽略 |

其中软件 I2C 的 200ms 是"物理时序"开销，无法消除（除非把传感器总线改接到 PB8/PB9 换硬件 I2C + DMA 收数，见《IIC 通信》笔记第 7 章）；而 LCD 刷屏这一环，**FSMC 本身不产生 DMA 请求**（它是存储器接口不是外设请求源），但可以用 **DMA2 的内存到内存（M2M）模式**把内部 SRAM 中的帧缓冲整块搬到 FSMC 映射地址，CPU 只负责"发起"，搬运过程零占用。

### 8.2 DMA 内存到内存搬运的原理

对 FSMC 映射区做 DMA 的关键认识是：**在 DMA 眼里，0x60000000 开头的 FSMC 地址区间和内部 SRAM 没有任何区别——它就是一段"内存"**。因此：

1. 在内部 SRAM 里建一块**局部帧缓冲**（如一行文字区域的像素数组）；
2. 先在帧缓冲里把字符点阵渲染好（写内部 RAM，速度极快）；
3. 开窗（`LCD_OpenWindow`）后，启动 DMA2 M2M 传输，源 = 帧缓冲，目的 = `LCD_DATA_ADDR`；
4. DMA 控制器自动把整段像素灌进 GRAM，CPU 在这期间可以去干别的（比如开始下一轮 I2C 采集的等待延时——**DMA 传输与软件 I2C 延时可以重叠**，这是实打实的并行收益）。

### 8.3 CubeMX 配置 DMA2

1. **System Core → DMA** → **MemToMem** → 点击 **Add**，自动生成 `hdma_memtomem_dma2_stream0`；
2. 参数：Mode = **Normal**，Increment Address = **两端都打勾**？——**注意：目的端不能自增**！FSMC 的数据端口是固定地址 `LCD_DATA_ADDR`，每写一个像素 NT35510 内部地址自增，所以 **Peripheral（目的，即 LCD_DATA_ADDR）不自增、Memory（源，帧缓冲）自增**。M2M 模式下 CubeMX 面板简化为：Data Width = Half Word，Priority = High；
3. NVIC 勾选 **DMA2 Stream0 global interrupt**（用回调判断搬运完成）。

> 若 CubeMX 的 MemToMem 面板不允许区分两端自增（F4 的 M2M 默认两端同设置），就**手工写 DMA 初始化代码**（见代码清单 8-1），不走 CubeMX 的 MemToMem 生成——这在工程上是常规做法。

列表 6: 代码清单 8-1 DMA 刷屏驱动（lcd_dma.c）

```c
#include "bsp_lcd.h"
#include <string.h>

static DMA_HandleTypeDef hdma_lcd;
static volatile uint8_t dma_busy = 0;

/**
  * @brief  手工初始化 DMA2 Stream0：内部RAM → FSMC 数据端口
  * @note   关键点：源地址自增（像素数组），目的地址固定（LCD_DATA_ADDR），
  *         NT35510 的 GRAM 地址自增由开窗后连续写自动完成
  */
void LCD_DMA_Init(void)
{
  __HAL_RCC_DMA2_CLK_ENABLE();

  hdma_lcd.Instance                 = DMA2_Stream0;
  hdma_lcd.Init.Channel             = DMA_CHANNEL_0;
  hdma_lcd.Init.Direction           = DMA_MEMORY_TO_MEMORY;
  hdma_lcd.Init.PeriphInc           = DMA_PINC_DISABLE;    /* 目的固定：FSMC 数据口 */
  hdma_lcd.Init.MemInc              = DMA_MINC_ENABLE;     /* 源自增：帧缓冲 */
  hdma_lcd.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
  hdma_lcd.Init.MemDataAlignment    = DMA_MDATAALIGN_HALFWORD;
  hdma_lcd.Init.Mode                = DMA_NORMAL;
  hdma_lcd.Init.Priority            = DMA_PRIORITY_HIGH;
  hdma_lcd.Init.FIFOMode            = DMA_FIFOMODE_ENABLE;
  hdma_lcd.Init.FIFOThreshold       = DMA_FIFO_THRESHOLD_FULL;
  hdma_lcd.Init.MemBurst            = DMA_MBURST_INC4;
  hdma_lcd.Init.PeriphBurst         = DMA_PBURST_SINGLE;
  HAL_DMA_Init(&hdma_lcd);

  HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

/**
  * @brief  用 DMA 把一个矩形区域的像素写入 LCD
  * @param  pixels: 内部 SRAM 中的像素数组（RGB565，w*h 个 uint16_t）
  * @retval HAL_BUSY 表示上一次搬运尚未完成
  */
HAL_StatusTypeDef LCD_DMA_FillBuffer(uint16_t x, uint16_t y,
                                     uint16_t w, uint16_t h,
                                     const uint16_t *pixels)
{
  if (dma_busy) return HAL_BUSY;
  dma_busy = 1;

  LCD_OpenWindow(x, y, w, h);
  LCD_WRITE_CMD(0x2C);          /* 开窗 + Memory Write，DMA 只负责灌数据 */

  return HAL_DMA_Start_IT(&hdma_lcd, (uint32_t)pixels,
                          LCD_DATA_ADDR, (uint32_t)w * h);
}

/* DMA 完成回调：解锁 */
void HAL_DMA_XferCpltCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma == &hdma_lcd) dma_busy = 0;
}

/* 中断入口（stm32f4xx_it.c 中也要有同样的转发） */
void DMA2_Stream0_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&hdma_lcd);
}
```

列表 7: 代码清单 8-2 用 DMA 显示一行文字（渲染到帧缓冲，再 DMA 灌屏）

```c
/* 一行文字区域：300 像素宽 × 16 像素高，4800 个 uint16_t ≈ 9.4KB 内部 RAM */
static uint16_t line_buf[300 * 16];

void LCD_ShowString_DMA(uint16_t x, uint16_t y, uint16_t w, const char *str)
{
  /* 1. 在内部 RAM 里渲染字符点阵（写 SRAM，无 FSMC 开销，极快） */
  uint32_t total = (uint32_t)w * 16;
  uint32_t i;
  for (i = 0; i < total; i++) line_buf[i] = WHITE;      /* 背景 */
  /* ……按字库点阵把笔画像素写成 BLACK（代码略，与 LCD_ShowString 的取模逻辑相同，
        区别只是写入目标是 line_buf 而不是直接 LCD_DrawPoint）…… */

  /* 2. 渲染完成后 DMA 整块灌屏，CPU 立即返回 */
  while (LCD_DMA_FillBuffer(x, y, w, 16, line_buf) == HAL_BUSY);
}
```

**效果对比**：逐点 `LCD_DrawPoint` 写一行 300×16 字符，4800 次 FSMC 写全部由 CPU 执行，约耗时 1~2ms 且全程占用 CPU；DMA 方式下 CPU 只花渲染点阵的时间（写内部 SRAM，一次访存约几个 ns 级指令），4800 个像素的搬运由 DMA 完成，**这 1~2ms 内 CPU 可以并行执行软件 I2C 的位操作**——原本串行的"采集 200ms + 刷屏 10ms"可以压到接近 200ms。

> **进阶方向**：若做波形显示/图片显示等大帧刷新，可把帧缓冲设为半屏或整行，配合 DMA 双缓冲交替渲染与推送，CPU 占用可再降一个数量级。整屏 854×480×2B = 800KB 超过 F407 的 192KB 内部 SRAM，所以**整屏帧缓冲放不下**，必须分行/分块——这也是为什么"局部刷新 + DMA 分行"是 F407 + 大屏的标配姿势。

---

## 9. 下载验证与常见问题

### 9.1 验证步骤

1. 编译下载，屏幕先黑一下（背光关 → 清屏 → 开背光），随后显示五行标题与数值；
2. **用手遮住 BH1750**，Lux 行数值应明显下降；手电照射升至上千 lx；
3. **对着 HTU21D 哈气**，湿度行明显上升；
4. **翻转/侧立开发板**，Acc 行的 X/Y/Z 数值随之变化，静止平放时某轴约 ±1000；
5. Time 行每秒递增（PCF8563 装了纽扣电池时断电后仍走时）。

### 9.2 常见问题速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| 完全白屏、无任何显示 | FSMC 未配通（NE1/A17 引脚复用错、未使能写） | 检查 CubeMX 中 FSMC 的 NE1、Register Select=A17、Write Operation=Enabled；检查 DATAST 是否过小 |
| 花屏、颜色错乱、随机色块 | DATAST/ADDSET 太小，数据未稳定即锁存 | DATAST 从 4 逐步加大到 8~15；确认 HCLK 确实是 168MHz |
| 显示内容全是"命令"效果（如全屏一种异常色） | 命令/数据地址搞反（A17 偏移算错） | 数据地址必须是基地址 \| (1<<18)，不是 \| (1<<17) |
| 背光不亮但实测 FSMC 读写正常 | PD2 未配成输出或电平反了 | 查 MX_GPIO_Init 中 PD2；用万用表量 PD2 电平 |
| 传感器数据全是 -1 或 0 | 软件 I2C 总线不通（上拉电阻、PA0/PA1 接线） | 按《IIC 通信》笔记 8.3.3 节的方法排查总线 |
| 屏幕显示但数值不刷新 | while 循环卡在 DMA busy 或 I2C 死等 | 检查 `dma_busy` 是否在回调中清零；I2C_WaitAck 加超时 |
| 改了 CubeMX 重新生成后 LCD 初始化代码丢失 | 代码写在了 CubeMX 管理区 | 自己的驱动放 bsp_lcd.c 等独立文件，或写在 USER CODE 区 |

---

## 10. 本章小结

1. **FSMC 驱动 LCD 的本质是"地址映射"**：配置好 NE1 + A17 + 16 位 + 模式 B 之后，LCD 命令口就是 `0x60000000`、数据口就是 `0x60040000`，用指针赋值即可完成 8080 写时序，软件层面看不到任何 GPIO 操作；
2. **RS 用地址线模拟**：A17=1 为数据、A17=0 为命令；16 位总线下 HADDR 右移一位，偏移位是 (17+1)=18 而不是 17——这是最容易算错的地方；
3. **时序余量要留够**：NT35510 写周期最短 66ns，ADDSET=4/DATAST=8 在 168MHz 下读 71ns、写约 83ns，稳妥可靠；花屏先查时序；
4. **显示链路分层**：软件 I2C（PA1/PA0）采集四个传感器 → 结构体缓存 → sprintf 格式化 → 字符渲染 → FSMC 写 GRAM，两 subsystem 互不干扰；
5. **CPU 占用优化两条路**：软件 I2C 的 200ms 是物理开销（要降只能改硬件 I2C 或拉长周期）；LCD 刷屏用 **DMA2 内存到内存** 把渲染好的帧缓冲灌进 GRAM，搬运期间 CPU 可与 I2C 采集并行，是最划算的优化。
