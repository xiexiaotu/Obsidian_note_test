# ADC—气体与空气质量采集（基于 STM32F407VET6 + STM32CubeMX）

> **本章参考资料**：《STM32F407 中文数据手册》、《RM0090 STM32F407 参考手册》ADC 章节，以及 MP-4、MP503 传感器模块各自的说明书。
> **学习提示**：配合参考手册中 ADC_SQR1/SQR2/SQR3、SMPR1/SMPR2、CR1/CR2、DR 寄存器的说明一起阅读，效果更佳，特别是涉及序列与采样时间位定义的部分。
> **特别说明**：本笔记以 **STM32F407VET6**（LQFP100 封装）资源讲解，外设配置全部通过 **STM32CubeMX** 完成，代码基于 STM32 HAL 库。采集目标：**PC4 读取 MP-4 燃气传感器模拟值，PC3 读取 MP503 空气质量传感器模拟值**。

---

## 1. ADC 简介

STM32F407VET6 片内共有 **3 个 ADC**（ADC1、ADC2、ADC3），每个 ADC 分辨率可选 **12 位 / 10 位 / 8 位 / 6 位**，各有 **16 个外部通道**；ADC1 还挂有内部通道（温度传感器、VREFINT、VBAT）。ADC 支持独立模式、双重模式和三重模式，绝大多数单片采集场景用 **ADC1 独立模式**即可，本笔记的双通道采集就是这种用法。

与串口对应的是"电平与协议"，与 ADC 对应的是"模拟世界与数字世界的边界"：传感器（气体、温度、光照）输出的都是连续变化的电压，MCU 只能处理 0/1，所以要用 ADC 把电压"拍照"成数字量。MP-4 和 MP503 恰好就是这类模拟电压输出器件，ADC 是读取它们的唯一正解。

---

## 2. ADC 功能框图剖析

掌握功能框图就掌握了 ADC 的整体脉络，框图按"信号流动方向"从左到右讲：输入范围 → 通道 → 序列 → 触发 → 转换时间 → 数据寄存器 → 中断/DMA。看懂这 7 个环节，CubeMX 里的每个勾选项都能对应到具体的硬件行为。
![](Pasted%20image%2020261007115923.png)

### 2.1 电压输入范围

VREF+/VREF- 决定 ADC 量程的两个端点：VREF- 对应码值 0，VREF+ 对应满量程码值。ADC 把落在量程内的输入电压线性映射为刻度值（码值）。

ADC 输入范围为 **VREF- ≤ VIN ≤ VREF+**。F407VET6 的 VREF+ 与 VDDA 在片内相连（开发板通常都接 3.3V），VREF- 接 VSSA，因此默认采集范围是 **0 ~ 3.3V**：0V 对应码值 0，3.3V 对应码值 4095（12 位）。

**输入电压超出量程会发生什么？**

**表 2-1 输入电压越界的表现与风险**

| 输入电压 | ADC 看到的 | 读数结果 | 风险 |
| --- | --- | --- | --- |
| 低于 0V（如 -0.1V） | 低于零刻度 | 读数 0，分不清负了多少 | 引脚内部 ESD 二极管导通，电流倒灌 |
| 0 ~ 3.3V | 量程之内 | 0 ~ 4095，线性可信 | 无 |
| 略超（如 3.5V） | 超过满刻度 | 读数**饱和在 4095**（削顶） | 逼近引脚绝对最大电压 VDD+0.3V = 3.6V |
| 大幅超（如 5V） | 严重超量程 | 恒为 4095，信号完全丢失 | 长期可能损伤引脚 |

**结合本实验算一笔账**：假如气敏元件输出节点直接接一个 5V 满幅信号到 PC4，一方面 5V 已越过 3.6V 的引脚耐压红线，另一方面读数会一直"顶格"卡在 4095——**软件看到的是一条纹丝不动的水平线，很容易误判成"浓度恒定没变化"，这比直接报错更危险，因为它悄悄给了个假数据**。本实验的传感器板用**板载 4.7kΩ 串联 + 4.7kΩ 下拉**的分压结构，已把节点电压天然限制在 **≤2.5V**（推导见 3.3 节），落在 0~3.3V 量程内，因此无需外加衰减、也无需软件还原。

**需要测量更宽范围时**：若被测信号带负电压（例如交流波形采样），需先用电阻分压+偏置把整段波形平移进 0~3.3V 才能测。本实验两个气体传感器输出都是 0V 起步的单向信号，不涉及平移，只需保证不超上限。

### 2.2 输入通道

ADC 的比较+编码电路只有一套，而可采集的引脚有很多——**通道**就是 ADC 输入端的多路选择开关，决定某一时刻把哪个引脚的电压接到转换核心：切到 PC3 测的就是 MP503，切到 PC4 测的就是 MP-4。

F407 每个 ADC 有 16 个外部通道 + 3 个内部通道。外部通道与 GPIO 的映射是**芯片出厂时硬连线固定的**，不是你想用哪个脚就能用哪个脚，所以**查映射表选脚是硬件设计的第一步**。本实验用的 PC3、PC4 恰好都是 ADC1 的外部通道：

**表 2-2 STM32F407VET6 ADC1 外部通道映射（LQFP100，节选）**

| 引脚 | ADC1 通道 | ADC2/ADC3 通道 | 本实验用途 |
| --- | --- | --- | --- |
| PA0~PA7 | IN0~IN7 | IN0~IN7 | — |
| PB0/PB1 | IN8/IN9 | IN8/IN9 | — |
| PC0~PC2 | IN10~IN12 | IN10~IN12 | — |
| **PC3** | **IN13** | IN13 | **MP503 空气质量（PC3/AIR）** |
| **PC4** | **IN14** | IN14 | **MP-4 燃气（PC4/GAS）** |
| PC5 | IN15 | IN15 | — |

> **举例说明为什么"换脚要查表"**：假如你哪天想把 MP-4 挪到 PB0，查表可知 PB0 是 CH8，代码里通道宏从 `ADC_CHANNEL_14` 改成 `ADC_CHANNEL_8` 即可；但若想挪到 PC6，那是**没有** ADC 通道的（PC6 是 USART6_TX），ADC 采集就得换方案。引脚自由度是硬件预留的，软件改不出来。

![](Pasted%20image%2020261007120249.png)

PC3/PC4 同时挂在 ADC1、ADC2、ADC3 上，三选一即可；本笔记统一使用 **ADC1**。

> 顺带一提：3 个内部通道（温度传感器、VREFINT、VBAT）只有 ADC1 能完整访问，想测芯片结温或供电电压，把通道切到这几个内部通道即可，用法与外部通道相同，只是不需要接任何引脚。

外部 16 个通道在转换时分为两类：

- **规则通道**：常规采集用的通道，最多 16 路，按"规则序列"排队转换。本实验的两个通道都是规则通道。
- **注入通道**：最多 4 路，具备**插队**能力——规则队列转换到一半时，注入通道可抢先转换，办完再从规则队列中断处继续，关系类似中断之于主程序。适合"必须随时抓取"的紧急信号（如过零检测、电流尖峰）。本实验的气体信号慢变，不涉及，理解概念即可。

### 2.3 转换顺序

既然 ADC 转换核心只有一套，多通道就必须**排队**，队号就是 **Rank**：Rank1 最先被转换，Rank2 第二个……本实验两路信号的次序定为"空气质量 → 燃气"。

规则序列由 SQR3（第 1~6 个转换）、SQR2（第 7~12 个）、SQR1（第 13~16 个 + 总长度 L[3:0]）三个寄存器决定——名字里的 SQ1、SQ2…就是"队伍第 1 位、第 2 位…"，寄存器的作用只是把通道号填进对应位置。

Rank 还决定了 **DMA 缓冲区里数据摆放的位置**，这直接关系代码正确性：

```
Rank1 = CH13(PC3/MP503)  →  一轮扫描第 1 个转换  →  adc_value[0]
Rank2 = CH14(PC4/MP-4)   →  一轮扫描第 2 个转换  →  adc_value[1]
```

> **举例（串位陷阱）**：如果有人好心把两个 Rank 对调（CH14 排 Rank1），代码一行没改，`adc_value[0]` 里装的就已经是燃气值了——串口打印会把"空气质量"和"燃气"的数字**互换且毫无报错**，数值看起来都"正常"，这类 bug 极难发现。所以记住：**数组下标跟 Rank 走，不跟引脚走**。

这些寄存器位 CubeMX 都会自动填，理解 Rank 概念主要用于读懂生成代码和排查"数据串通道"问题。

### 2.4 触发源

通道和序列都排好后，还需要一个"开始转换"的信号。**启动方式有两类：软件触发和硬件事件触发。**

1. **软件触发**：CPU 执行到 `HAL_ADC_Start()` / `HAL_ADC_Start_DMA()` 这行代码即启动转换，何时开始由程序流程决定。本实验启动后靠连续转换自动循环，就属于这种方式；
2. **外部事件触发**：由定时器（TIM 的 TRGO/CC 事件）、EXTI 等硬件信号产生启动脉冲，转换时刻由硬件节拍决定，与程序执行进度无关。适合需要严格等间隔采样的场景。

> **举例说明什么时候必须用定时触发**：测 50Hz 工频信号想画波形，要求每隔 200µs 精确采一点。若用软件触发（在主循环里 `HAL_ADC_Start` + 延时），主循环里任何一次 `printf`、任何一次中断都会让采样时刻抖动，画出的波形就"忽快忽慢"；换成 TIM 每 200µs 硬件触发一次，采样间隔由硬件保证，CPU 打瞌睡都不影响精度。本实验气体浓度秒级慢变，秒表精度绰绰有余，无需定时器。

### 2.5 转换时间

一次转换分两段：先花若干个时钟周期把引脚电压接入并对片内采样电容充电（**采样时间**，可配置），再花 12 个周期逐位比较得到码值（**量化时间**，12 位分辨率固定 12 周期）。总时间 = 采样 + 量化。

**① ADC 时钟**：ADCCLK 由 PCLK2 分频而来，**最大 36MHz**。F407VET6 常用配置下 PCLK2 = 84MHz（APB2 ÷2），CubeMX 的 ADC 时钟一般选 **÷4 = 21MHz** 或 ÷6 = 14MHz。本实验取 **÷4 = 21MHz**。

> 注意 84MHz 不能 1 分频直用——84 > 36，超出手册上限，转换结果不可信。这就是时钟树里 ADC 只能挂 21MHz 的原因。

**② 采样时间**：每个通道可选 3、15、28、56、84、112、144、480 个 ADCCLK 周期。采样时间的物理意义是**给片内采样电容留够充电窗口**：信号源内阻越高充电越慢，窗口不足则电容没充满就开始量化，读数系统性偏低且随温度漂移。

- 低阻源（如电位器滑动端，几百 Ω）：3 周期就够；
- 本实验：从 ADC 引脚向信号源看，等效内阻 = 下拉电阻 R1207/R1185(4.7kΩ) ∥ (气敏元件 Rs + 串联电阻 R1208/R1201(4.7kΩ))。按 3.3 节电路与规格书数据（Rs 约 1kΩ ~ 100kΩ），源阻约 **2.6kΩ ~ 4.5kΩ**，属于高阻源。

> **算一笔账**：取最坏源阻 4.5kΩ、片内采样电容约 4pF，时间常数 τ = R×C ≈ 18ns；要把误差压到 12 位半格（约 0.012%）需要约 9τ ≈ 0.16µs 的稳定过程。3 周期只有 0.14µs（@21MHz），刚好不够；15 周期 0.71µs 已能满足，144 周期 6.86µs 则余量充足——对秒级监测是零成本的精度保险，所以本实验两通道都选 **144 周期**（480 留给更高阻抗场景）。

**③ 总转换时间**：

```
Tconv = 采样时间 + 12 个周期
```

本实验单通道：(144 + 12) / 21MHz ≈ **7.43µs**；双通道一轮扫描 ≈ 15µs。对秒级刷新就够用的气体监测来说，时间余量巨大，可以放心用连续转换。作为对照，若全用最短档（3+12=15 周期 @21MHz），单通道约 0.71µs——这就是"高速采集能到多快"的量级参考。

### 2.6 数据寄存器

规则组转换结果统一放在 **ADC_DR**（32 位寄存器，低 16 位有效，对齐方式由 CR2 的 ALIGN 位控制，HAL 默认右对齐）。关键点在于：**16 个规则通道共用这一个 DR**。多通道扫描时，每个通道转完都把结果写进同一个 DR，如果上一个结果没被读走，就会被下一个覆盖，数据直接丢失。解决办法二选一：

- **中断方式**：每转完一个通道立刻进中断读走。通道少时可行，通道一多中断频繁，CPU 大量时间耗在搬运上；
- **DMA 方式**（本实验）：转换结束硬件自动发出 DMA 请求，把 DR 里的结果直接写进内存数组的下一个位置，整个过程不占用 CPU。这是多通道采集的标准做法。

注入组另有 4 个专属寄存器 JDR1~JDR4，一通道一格，不存在覆盖问题，所以注入方式反而不需要 DMA 也行。

### 2.7 中断与 DMA 请求

ADC 支持四类中断：

| 中断 | 触发时机 | 典型用途 |
| --- | --- | --- |
| EOC（规则转换结束） | 一个通道转换完成 | 逐通道读取 |
| EOS（规则序列结束） | 一轮序列全部转换完成 | 多通道批量读取 |
| 模拟看门狗 | 输入电压越过预设上/下限（HTR/LTR） | 燃气超标即时报警（见第 8 节） |
| 溢出（OVR） | 旧数据未取走就被新结果覆盖 | 程序错误自检 |

转换结束还可以发出 **DMA 请求**，由 DMA 直接把结果从 DR 取走，全程不占用 CPU。**只有 ADC1 和 ADC3 能产生 DMA 请求**（ADC2 的结果要靠"交叉搬运"进 ADC1/ADC3 的通路间接实现），这正是本实验选 ADC1 的原因之一。CubeMX 勾选 *DMA Settings* 后，中断服务函数、DMA 配置全部自动生成，用户只写回调或读缓冲区。

### 2.8 电压转换

12 位分辨率 = 把 0~3.3V 量程切成 4096 级（码值 0~4095），每级权重 3.3V/4096 ≈ **0.806mV**——这就是 ADC 能分辨的最小电压变化，也是"12 位精度"的实际含义：比 0.8mV 更小的变化它无法分辨。下文换算式取"满量程码值 4095 对应 VREF"的工程惯例（与按级数 4096 计算的差异 <0.03%，可忽略）。

转换结果 X 对应的输入电压（与 3.3 节推导步骤 3 相同，满量程码值 4095 对应 VREF）：

```
V = 3.3 × X / 4095 (V)
```

> **例子（完整计算链）**：串口打印 `raw=1548` → 引脚电压 = 3.3 × 1548 / 4095 ≈ **1.246V** → 代入 3.3 节推导步骤 4 反推元件电阻 Rs = 5×4.7/1.246 − 9.4 ≈ **9.5kΩ** → 再对照规格书的 Rs—浓度曲线，即可得到气体浓度。

验证换算是否正确：用万用表量 PC3/PC4 引脚的实际电压，与 `V = 3.3X/4095` 对账，两者应在几个码值的误差内一致；差得远就先查 VREF 和下拉电阻是否虚焊。

---

## 3. 传感器认识与连接原理

本节回答"被测信号从哪来、怎么安全地接到 PC3/PC4"。两个模块同类不同用：MP-4 管"可燃气有没有漏"，MP503 管"空气闷不闷、脏不脏"。

### 3.1 MP-4 燃气传感器

MP-4 属于**金属氧化物半导体（MOS）气敏**器件（炜盛产品，与常见的 MQ-4 同属甲烷/天然气检测家族，量程 300~10000ppm）。其核心是一片二氧化锡（SnO₂）敏感层，由内部**加热丝**加热到工作状态（加热功耗可达数百 mW，这也是它要求 5V 供电、上电需预热的原因）。

工作原理一句话：**清洁空气中 SnO₂ 吸附氧、电阻（Rs）很大；可燃气还原吸附氧，Rs 随浓度下降**。

本笔记对应的传感器板（原理图标题 *CombustibleGas*，位号 U37）**没有比较器、没有排针模块电路**，气敏元件直接焊在板上，信号取自板载分压网络：


```
VCC_5V ──[Rs 气敏元件]── R1208(4.7kΩ) ──┬── PC4/GAS → 单片机 PC4
                                        │
                                    R1207(4.7kΩ)
                                        │
                                       GND
```

输出节点电压 = 下拉电阻 R1207 上的分压：**燃气浓度越高 → Rs 越小 → 回路电流越大 → R1207 上的电压越高**。R1208 是串联保护/限流电阻，因为 ADC 引脚几乎不取电流，它不改变稳态电压，只抬高源阻抗（见 2.5 节）。

**表 3-1 传感器板接线（对应原理图网络）**

| 网络/引脚 | 含义 | 接法 |
| --- | --- | --- |
| VCC_5V | 元件加热与分压供电 | 开发板 5V |
| GND | 地 | **与开发板共地** |
| PC4/GAS | 分压输出节点 | 直连 **PC4（ADC1_IN14）** |
| 加热丝（引脚 1-2） |  heater 供电回路 | 板上已接好（1→5V，2→GND） |

> 灵敏度曲线（Rs/R₀—浓度对数关系）和加热稳定时间（典型需预热老化、每次上电 1~2min 预热）以手中元件规格书为准；不同厂家同类元件 Rs 取值有差异，定量换算浓度时必须用实测曲线。

### 3.2 MP503 空气质量传感器

MP503 是炜盛（Winsen）**空气质量气体传感器**（TO-5 金属封装的平面半导体元件），敏感材料同样是加热型金属氧化物，但对**酒精、烟雾、异丁烷、甲醛、苯、一氧化碳、氨、氢气**等挥发性气体灵敏度高，定位是家庭/办公室有害气体检测，常见于空气净化机、新风换气系统、自动排风装置（部分成品模块以"TVOC 空气质量"名义标称）。

传感器板（原理图标题 *AirQuality*，位号 U30）的电路结构与燃气板**完全同构**，只是输出网络接到 PC3：

```
VCC_5V ──[Rs 气敏元件]── R1201(4.7kΩ) ──┬── PC3/AIR → 单片机 PC3
                                        │
                                    R1185(4.7kΩ)
                                        │
                                       GND
```

污染越重 → Rs 越小 → R1185 上的电压越高。输出机理与 MP-4 一致，同样没有 DO 引脚。

**表 3-2 两传感器对照**

| 项目 | MP-4（燃气板 → PC4） | MP503（空气板 → PC3） |
| --- | --- | --- |
| 检测对象 | 甲烷/天然气等可燃气体（300~10000ppm） | 酒精/烟雾/甲醛/异丁烷等挥发性有害气体 |
| 原理图标题 | CombustibleGas（U37） | AirQuality（U30） |
| 输出网络 | R1208 串 + R1207 下拉（均 4.7kΩ） | R1201 串 + R1185 下拉（均 4.7kΩ） |
| 浓度↔电压 | 浓度↑ 输出↑ | 污染↑ 输出↑ |
| 供电 | 5V（含加热丝回路） | 5V（含加热丝回路） |
| ADC 通道 | ADC1_IN14（Rank2） | ADC1_IN13（Rank1） |

### 3.3 连接原理与量程分析（对照实物原理图）

两张原理图如下（已存入本笔记文件夹）：

![MP-4 燃气传感器接口电路（CombustibleGas）](MP-4燃气传感器接口电路.png)

![MP503 空气质量传感器接口电路（AirQuality）](MP503空气质量传感器接口电路.png)

**① 电压转换公式推导**。以燃气板为例（空气板把 R1207/R1208 换成 R1185/R1201 即可），回路为：`VCC(5V) — 气敏 Rs — R串(R1208=4.7kΩ) —[输出节点 Vout]— R下(R1207=4.7kΩ) — GND`。

推导分四步（设电阻单位 kΩ、电压单位 V）：

1. **回路电流**：ADC 引脚输入阻抗近似无穷大，输出节点不分走电流，三个元件串联流过同一电流：

   ```
   I = VCC / (Rs + R串 + R下)
   ```

2. **输出电压**（ADC 实际读到的，就是 R下 上的压降）：

   ```
   Vout = I × R下 = VCC × R下 / (Rs + R串 + R下) = 5 × 4.7 / (Rs + 9.4)
   ```

   可见 Vout 是 Rs 的减函数：**气体浓度↑ → Rs↓ → Vout↑**。

3. **码值 → 电压**（分辨率定义：4096 级刻度铺满 0~VREF，raw 就是走过的刻度数）：

   ```
   Vout = VREF × raw / 4095 = 3.3 × raw / 4095
   ```

4. **反解 Rs**（第 2 步等式两边解出 Rs，供查浓度曲线）：

   ```
   Rs = VCC × R下 / Vout − (R串 + R下) = 5 × 4.7 / Vout − 9.4
   ```

第 3、4 两式就是第 6、7 两章代码中 `Raw_To_Volt()` 与 `Volt_To_Rs()` 的实现依据，函数注释里标注了对应步骤。

**② 为什么这个电路天然安全**。Rs ≥ 0，分母最小为 9.4，因此 **Vout 上限 = 5 × 4.7/9.4 = 2.5V**，无论气体浓度多高都不会超过 2.5V——始终落在 ADC 的 0~3.3V 量程和引脚耐压之内，**不需要外加衰减电路，软件也无需还原系数**。

**③ 反推算例（读数 → Rs）**。设某时刻 PC4 打印 `raw=1548`：

```
Vout = 3.3 × 1548 / 4095 ≈ 1.246V
Rs   = 5 × 4.7 / 1.246 − 9.4 ≈ 9.5kΩ
```

拿到 Rs 后对照规格书的 Rs/R₀—浓度曲线查 ppm（R₀ 需先在清洁空气中标定：测得清洁空气下的 Rs，再按规格书 Rs/R₀ 比值反算）。

**④ 各元件作用清单**：

| 位号 | 值 | 作用 |
| --- | --- | --- |
| R1208 / R1201 | 4.7kΩ | 与下拉电阻构成 2.5V 上限分压；兼作限流/保护，抬高源阻抗（见 2.5 节采样时间计算） |
| R1207 / R1185 | 4.7kΩ | 下拉取压电阻，决定输出上限 2.5V |
| C1186 | 10µF | 5V 电源大电容：吸收加热丝电流波动，压低电源纹波 |
| C1185 | 100nF | 5V 电源高频去耦：给加热回路提供低阻抗高频通路 |

> 注意 C1186/C1185 滤的是**电源轨**上的纹波，输出节点本身没有对地电容。若实测读数抖动明显，可在 PC3/PC4 就近对地加 100nF（源阻抗约 4.5kΩ 时截止频率约 0.36kHz，对秒级慢信号无影响）。

**⑤ 接线要点**：传感器板与开发板**必须共地**（两图的下拉电阻都接到各自 GND，不共地则 Vout 没有参考基准，读数乱跳）；5V 直接从开发板 5V 输出取，保证与 ADC 参考同源自洽。

---

## 4. ADC 初始化结构体详解

HAL 库为 ADC 建立了"句柄 → 总参数 → 通道参数"三层结构，CubeMX 生成代码就是按这三层填写的，理解成员含义即可自由配置。

### 4.1 ADC_HandleTypeDef 结构体

定义在 `stm32f4xx_hal_adc.h`，统管一个 ADC 的所有状态：

```c
typedef struct {
  ADC_TypeDef            *Instance;  /* 寄存器基地址（ADC1/2/3） */
  ADC_InitTypeDef         Init;      /* 总工作参数 */
  __IO uint32_t           NbrOfCurrentConversionRank;
  DMA_HandleTypeDef      *DMA_Handle;/* DMA 句柄指针（本实验要用） */
  HAL_LockTypeDef         Lock;      /* 互斥锁定 */
  __IO uint32_t           State;     /* 通信状态 */
  __IO uint32_t           ErrorCode; /* 错误码 */
} ADC_HandleTypeDef;
```

### 4.2 ADC_InitTypeDef 结构体

ADC 级（所有通道共用）的工作参数，CubeMX *ADC Settings → Parameter Settings* 对应填写：

**表 4-1 ADC_InitTypeDef 成员 ↔ CubeMX 配置（本实验取值）**

| 成员 | 含义 | 本实验取值 |
| --- | --- | --- |
| `ClockPrescaler` | ADCCLK 分频（2/4/6/8） | `ADC_CLOCKPRESCALER_PCLK_DIV4`（21MHz） |
| `Resolution` | 分辨率 | `ADC_RESOLUTION_12B` |
| `DataAlign` | 数据对齐 | `ADC_DATAALIGN_RIGHT` |
| `ScanConvMode` | 扫描模式：多通道必开 | `ADC_SCAN_ENABLE` |
| `ContinuousConvMode` | 连续转换：转完序列自动重来 | `ADC_CONTINUOUS_CONV_ON` |
| `EOCSelection` | 转换结束标志粒度 | `ADC_EOC_SINGLE_CONV` |
| `NbrOfConversion` | 规则序列长度 | `2` |
| `DiscontinuousConvMode` | 不连续采样 | 关闭 |
| `ExternalTrigConv` / `Edge` | 外部触发源/极性 | 软件触发、无边缘 |
| `DMAContinuousRequests` | 连续 DMA 请求 | 开启 |

### 4.3 ADC_ChannelConfTypeDef 结构体

通道级参数，CubeMX *Rank / Sampling Time* 表格即对应此结构：

```c
typedef struct {
  uint32_t Channel;       /* 通道号：ADC_CHANNEL_13 / 14 */
  uint32_t Rank;          /* 序列号：ADC_REGULAR_RANK_1 / 2 */
  uint32_t SamplingTime;  /* 采样时间：ADC_SAMPLETIME_144CYCLES_5 */
  uint32_t Offset;        /* 预留，置 0 */
} ADC_ChannelConfTypeDef;
```

> **通道顺序约定**：DMA 环形缓冲区里 `adc_value[0]` 对应 Rank1（PC3/MP503）、`adc_value[1]` 对应 Rank2（PC4/MP-4）。改 Rank 就是改数组位置，多通道"数据串位"多半是这里没对齐。

---

## 5. STM32CubeMX 配置工程

以下为全新工程从零配置 ADC1 的完整步骤。后文两个实验对应两套 CubeMX 配置，先按实验一配**模式 A（单通道、无 DMA）**，做完再改回**模式 B（双通道 + DMA）**做实验二（串口打印链路沿用《串口通信》笔记的 USART1 配置）。

### 5.1 新建工程与芯片选择

1. **New Project** → 搜索 `STM32F407VET6`，选 LQFP100 封装进入。

### 5.2 系统时钟

1. **RCC** → HSE = Crystal；
2. **Clock Configuration**：PLL 按 8MHz 晶振配到 **SYSCLK 168MHz**；AHB ÷1=168M，APB1 ÷4=42M，APB2 ÷2=**PCLK2 84MHz**；
3. ADC 频率显示应 ≤36MHz。

### 5.3 配置 ADC1

**模式 A（实验一：单通道，轮询读取，不用 DMA）**

1. **Analog → ADC1 → Mode**：只勾 **IN14**（PC4/GAS，芯片图上 PC4 自动出现），Mode 保持 **Independent Mode**；
2. **ADC Settings → Parameter Settings**：分辨率 12 bits、Prescaler ÷4、Scan Mode **Disable**、Continuous Conversion **Enable**（自动反复转换，读取时永远有新鲜数据）、Rules Number **1**、外部触发 *Disable*（软件触发）、DMA Continuous Requests **Disable**、EOC 选 *Each time ADC conversion period is ended*、Data Alignment 右对齐；
3. **Regular Conversion Settings**：Rank 1 → **Channel 14** → Sampling Time **144 Cycles**；
4. **DMA Settings**：不添加任何 DMA 传输；**NVIC Settings**：不勾选（本实验用轮询）。

**模式 B（实验二：双通道 + DMA）**

1. **Mode** 改勾 **IN13 & IN14**（PC3、PC4 都出现），Independent Mode；
2. **Parameter Settings**：Scan Mode **Enable**、Continuous **Enable**、Rules Number **2**、DMA Continuous Requests **Enable**，其余同模式 A；
3. **Regular Conversion Settings**：
   - Rank 1 → **Channel 13**（PC3，MP503）→ Sampling Time **144 Cycles**；
   - Rank 2 → **Channel 14**（PC4，MP-4）→ Sampling Time **144 Cycles**；
4. **DMA Settings → Add**：Stream **DMA2 Stream0**、Request **ADC1**、Mode **Circular**、Data Width 两端均 **Half Word**（若缓冲区用 `uint32_t`，Memory 端选 Word，与 HAL 约定一致，见 6.2 节说明）、Priority Medium；
5. NVIC 可不勾——DMA 模式下转换与搬运全由硬件闭环完成，主循环直接读缓冲即可。

### 5.4 顺带配置 USART1（打印输出）

Connectivity → USART1 → Asynchronous（PA9/PA10），115200-8-N-1，勾选全局中断——与前一篇笔记一致，不再展开。

### 5.5 生成代码

Project Manager 填工程名与路径（如 `ADC_gas_monitor`），工具链选 MDK-ARM 或 CubeIDE，**GENERATE CODE**。重点阅读三处：

- `adc.c`：`MX_ADC1_Init()` 与 `HAL_ADC_MspInit()`；
- `dma.c`：`MX_DMA_Init()`（**仅模式 B 存在**；注意函数调用顺序——DMA 控制器时钟必须在 `HAL_ADC_Init` 之前使能，CubeMX 已排好）；
- `stm32f4xx_it.c`：`DMA2_Stream0_IRQHandler()` → `HAL_ADC_IRQHandler` 的挂接（仅模式 B）。

模式 B 下 CubeMX 生成的 MspInit 关键片段（列表 1: 代码清单 5-1；模式 A 没有 `hdma_adc1` 段落，其余相同）：

```c
void HAL_ADC_MspInit(ADC_HandleTypeDef* adcHandle)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if (adcHandle->Instance == ADC1)
  {
    __HAL_RCC_ADC1_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();

    /* PC3/PC4 配置为模拟输入——ADC 引脚必须 Analog 模式，
       复用数字功能会引入上下拉干扰采集 */
    GPIO_InitStruct.Pin  = GPIO_PIN_3 | GPIO_PIN_4;
    GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

    /* ADC1 → DMA2 Stream0 Channel1（CubeMX 自动生成） */
    hdma_adc1.Instance                 = DMA2_Stream0;
    hdma_adc1.Init.Channel             = DMA_CHANNEL_1;
    hdma_adc1.Init.Direction           = DMA_PERIPH_TO_MEMORY;
    hdma_adc1.Init.PeriphInc           = DMA_PINC_DISABLE;
    hdma_adc1.Init.MemInc              = DMA_MINC_ENABLE;
    hdma_adc1.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    hdma_adc1.Init.MemDataAlignment    = DMA_MDATAALIGN_HALFWORD;
    hdma_adc1.Init.Mode                = DMA_CIRCULAR;
    hdma_adc1.Init.Priority            = DMA_PRIORITY_MEDIUM;
    HAL_DMA_Init(&hdma_adc1);

    __HAL_LINKDMA(adcHandle, DMA_Handle, hdma_adc1);
  }
}
```

---

## 6. 实验一：单通道采集 MP-4 燃气值（PC4，轮询，不用 DMA）

**实验目标**：只用 ADC1 采集 CH14（PC4，MP-4 燃气），**不配置 DMA**——主循环用 `HAL_ADC_PollForConversion()` 轮询等待转换结束、`HAL_ADC_GetValue()` 读数，每 1 秒打印原始码值、引脚电压与反推的气敏电阻 Rs（换算公式的完整推导见 3.3 节①，代码注释标注了对应步骤）。本实验帮助看清"一次转换从触发到取数"的完整链路，也是实验二出问题时的对照基准。

### 6.1 硬件设计

1. 只接**燃气板**：输出网络 **PC4/GAS → PC4**（板载 4.7kΩ 串 + 4.7kΩ 下拉，输出 ≤2.5V，直连无需衰减）；
2. 燃气板 VCC 接开发板 **5V**，GND 与开发板共地；
3. 开发板 USART1（PA9/PA10）经 USB 转串口连电脑；
4. 空气板本实验可不接（PC3 悬空不影响采集）。

> 接线复查两件事：共地可靠；5V 电流预算够（加热回路可达数十 mA）。

### 6.2 软件设计

CubeMX 按 5.3 节**模式 A** 配置（IN14 单通道、Scan 关、Continuous 开、无 DMA、无 NVIC）。核心代码写在 `main.c` 的 USER CODE 区。

#### 6.2.1 编程要点

1. 使能 GPIOC 与 ADC1 时钟，PC4 配置为 **Analog 模式**（MspInit 完成）；
2. 配置 ADC：12 位、÷4、单通道、连续转换、软件触发（CubeMX 完成）；
3. `HAL_ADC_Start()` 启动转换——连续模式下转换自动循环；
4. 主循环 `HAL_ADC_PollForConversion()` 等待本次转换结束，`HAL_ADC_GetValue()` 读数；
5. 按 3.3 节推导式把码值换算成电压与 Rs 打印。

#### 6.2.2 代码分析

列表 2: 代码清单 6-1 换算函数（与 3.3 节①推导步骤一一对应，两个实验共用）

```c
/* USER CODE BEGIN 0 */
#define VREF          3.3f    /* ADC 参考电压(V) */
#define FULL_SCALE    4095.0f /* 12 位满量程码值 */
#define VS_EN         5.0f    /* 传感器板供电 VCC(V) */
#define R_SER         4.7f    /* 串联电阻 R1208/R1201(kΩ) */
#define R_DOWN        4.7f    /* 下拉电阻 R1207/R1185(kΩ) */

/* 推导步骤3：4096 级刻度铺满 0~VREF，raw 即走过的刻度数
   Vout = VREF × raw / 4095 */
static float Raw_To_Volt(float raw)
{
  return raw * VREF / FULL_SCALE;
}

/* 推导步骤2：Vout = VCC × R下 / (Rs + R串 + R下)
   推导步骤4（反解）：Rs = VCC × R下 / Vout − (R串 + R下)
   Vout 接近 0（清洁空气、Rs 极大）时钳位 999kΩ 防除零 */
static float Volt_To_Rs(float vout)
{
  float rs;
  if (vout < 0.01f) return 999.0f;
  rs = VS_EN * R_DOWN / vout - (R_SER + R_DOWN);
  return (rs > 999.0f) ? 999.0f : rs;
}
/* USER CODE END 0 */
```

列表 3: 代码清单 6-2 主函数（轮询读取，无 DMA）

```c
int main(void)
{
  HAL_Init();
  SystemClock_Config();        /* 168MHz, PCLK2=84MHz */
  MX_GPIO_Init();
  MX_ADC1_Init();              /* 模式 A：CH14 单通道，无 DMA */
  MX_USART1_UART_Init();       /* 115200 8-N-1 */

  HAL_ADC_Start(&hadc1);       /* 软件触发启动，连续模式自动循环 */

  while (1)
  {
    /* 轮询等待本次转换结束（100ms 超时） */
    if (HAL_ADC_PollForConversion(&hadc1, 100) == HAL_OK)
    {
      float raw  = (float)HAL_ADC_GetValue(&hadc1);
      float vout = Raw_To_Volt(raw);   /* 码值 → 电压 */
      float rs   = Volt_To_Rs(vout);   /* 电压 → Rs(kΩ) */

      printf("MP-4(GAS) raw=%6.0f  V=%.3fV  Rs=%.1fkΩ\r\n",
             raw, vout, rs);
    }
    HAL_Delay(1000);
  }
}
```

**代码要点分析**：

1. **轮询的代价**：`HAL_ADC_PollForConversion()` 内部就是反复查 ADC_SR 的 EOC 标志，等待期间 CPU 全程陪跑。本实验一轮转换仅约 7.4µs（2.5 节），1 秒打印周期里 CPU 绝大部分时间在 `HAL_Delay`，陪跑无所谓；若通道多、采样率高，这种方式就不可接受——这正是实验二引入 DMA 的动机。
2. **连续模式的取数时机**：Continuous=Enable 时转换自动循环，读 DR 拿到的总是"最近一次完成"的值；若要严格"触发一次只转一次"，把 Continuous 关闭，每次转换前手动 `HAL_ADC_Start()`。
3. **单通道没有覆盖/串位问题**：Scan 关闭、只有一个规则通道，DR 里永远只有 CH14 的数据，也就不涉及 Rank 与数组下标的对应关系。

### 6.3 下载验证

编译下载，串口助手（115200-8-N-1）每秒打印一行。静置时 Rs 应处于高阻（清洁空气几十 kΩ 以上）且稳定；对着燃气板轻呼一口气或靠~近打火机出气口（**轻试即离**），raw 上升、Rs 下降，撤离后缓慢回升。

---

## 7. 实验二：双通道同时采集（PC3+PC4）+ DMA 数据搬运

**实验目标**：ADC1 扫描模式同时采集 CH13（MP503 空气质量）与 CH14（MP-4 燃气），**DMA 环形缓冲自动搬运**，主循环每 1 秒把两路码值、电压、Rs（换算函数直接复用代码清单 6-1）打印到串口调试助手。

### 7.1 硬件设计

1. 两传感器板按第 3 章原理图直连：**PC4/GAS → PC4**、**PC3/AIR → PC3**，均为板载 4.7kΩ 串 + 4.7kΩ 下拉结构，输出 ≤2.5V，无需外加衰减；
2. 两板 VCC 接开发板 **5V**，GND 与开发板共地；
3. 开发板 USART1（PA9/PA10）经 USB 转串口连电脑。

> 接线复查三件事：共地可靠、5V 电流预算够（两枚气敏元件加热回路合计可达百余 mA）、走线避开加热驱动回路与电机等干扰源。

### 7.2 软件设计

CubeMX 按 5.3 节**模式 B** 配置（IN13+IN14、Scan 开、序列长度 2、DMA2 Stream0 Circular）。核心代码写在 `main.c` 的 USER CODE 区。

#### 7.2.1 编程要点

1. 使能 GPIO（PC3/PC4）、ADC1、DMA2 时钟，引脚 **Analog 模式**（MspInit 完成）；
2. 配置 ADC：12 位、÷4、扫描+连续、软件触发、序列长度 2（CubeMX 完成）；
3. 配置各通道 Rank（CH13→Rank1，CH14→Rank2）与 144 周期采样时间（CubeMX 完成）；
4. 配置 ADC1 → DMA2 Stream0 环形传输：外设地址 ADC1->DR、内存地址指向 `adc_value` 数组、`__HAL_LINKDMA` 挂接（CubeMX 完成）；
5. 上电 `HAL_ADC_Start_DMA(&hadc1, adc_value, 2)` 启动采集；
6. 主循环取数换算打印；**连续转换 + 环形 DMA 下无需重复启动**。

#### 7.2.2 代码分析

列表 4: 代码清单 7-1 采集缓冲定义

```c
/* USER CODE BEGIN PV */
#define ADC_CH_NUM 2
/* DMA 目标环形缓冲：下标跟 Rank 走 —— [0]=Rank1=CH13(PC3)，[1]=Rank2=CH14(PC4) */
__IO uint32_t adc_value[ADC_CH_NUM];
/* USER CODE END PV */
```

> 缓冲区类型必须与 CubeMX 的 DMA Data Width 一致：`HAL_ADC_Start_DMA` 约定传 `uint32_t*`，故缓冲区用 `uint32_t`、Memory 端选 Word；若两端都配 Half Word，则数组改用 `uint16_t` 并在调用处强转。

列表 5: 代码清单 7-2 主函数（DMA 读取；`Raw_To_Volt()`/`Volt_To_Rs()` 与代码清单 6-1 相同，直接复用）

```c
int main(void)
{
  HAL_Init();
  SystemClock_Config();        /* 168MHz, PCLK2=84MHz */
  MX_GPIO_Init();
  MX_DMA_Init();               /* DMA 时钟先于 ADC 初始化 */
  MX_ADC1_Init();              /* 模式 B：扫描+连续+2 通道 */
  MX_USART1_UART_Init();       /* 115200 8-N-1 */

  /* 启动 DMA 循环采集：一次启动，硬件自动不停 */
  HAL_ADC_Start_DMA(&hadc1, (uint32_t *)adc_value, ADC_CH_NUM);

  while (1)
  {
    /* 换算步骤与 3.3 节①推导一一对应：步骤3 码值→电压，步骤4 电压→Rs */
    float v503  = Raw_To_Volt((float)adc_value[0]);  /* PC3 空气质量 */
    float rs503 = Volt_To_Rs(v503);
    float v4    = Raw_To_Volt((float)adc_value[1]);  /* PC4 燃气 */
    float rs4   = Volt_To_Rs(v4);

    printf("MP503(空气质量) raw=%4d  V=%.3fV  Rs=%.1fkΩ\r\n",
           adc_value[0], v503, rs503);
    printf("MP-4 (燃气)     raw=%4d  V=%.3fV  Rs=%.1fkΩ\r\n",
           adc_value[1], v4,   rs4);
    printf("----------------------------\r\n");

    HAL_Delay(1000);
  }
}
```

**代码要点分析**：

1. **环形 DMA 免搬运**：连续转换 + Scan + DMA Circular 组合下，硬件每转完一轮（CH13→CH14）就把两个结果写入 `adc_value[0..1]` 并自动回卷，主循环读到的永远是最新一轮数据，CPU 零参与——对比实验一，这里没有任何 `PollForConversion`，也没有 EOC 判断。
2. **取数快照**：严格来说读数组瞬间可能被 DMA 更新，本场景数据慢变、单字访问，无碍；高要求场景用双缓冲或 EOC 中断置标志。
3. **Rs→浓度**：`Volt_To_Rs` 只把电压换算成气敏元件电阻，这已是硬件能给到的最"物理"的量。要报 ppm，需先在清洁空气中标定 R₀（取 Rs/R₀ 比值），再对照规格书的 Rs/R₀—浓度对数曲线查表或拟合幂律 `Rs/R0 = A × ppm^B`——不同个体曲线有差异，量产需逐台标定。
4. **预热**：MOS 气敏上电需预热数分钟读数才稳，正式判断前丢弃前 2~5 分钟数据。
5. **两个实验的取舍**：单通道轮询胜在链路直观、易调试、不占 DMA 资源；双通道 DMA 胜在不占 CPU、可扩展到 16 通道。工程上先跑通轮询验证硬件与换算公式，再切 DMA，是稳妥的开发顺序。

### 7.3 下载验证

1. 编译下载到开发板，串口助手（115200-8-N-1）每秒刷新两组数据；
2. 静置时两路 Rs 应处于高阻且数值稳定（±2 码内抖动为正常噪声）；
3. 对着燃气板呼出气体或靠近打火机出气口（**轻试即离，勿长时间灌气**），MP-4 通道 raw 上升、Rs 明显下降，撤离后缓慢回升；
4. 对着空气板哈气或靠近纸巾/酒精棉（不接触），空气质量通道同样 raw↑、Rs↓；
5. 若读数恒为 4095/0：检查共地与下拉电阻是否虚焊；若读数偏低且随采样时间变化：加大采样时间档；若两路数据对调：检查 Rank 与数组下标。

---

## 8. 扩展：定时采集与看门狗报警（思路）

1. **TIM 触发替代连续转换**：把 Continuous 关闭、外部触发选 TIM2 TRGO（Period Msp），即可精确按 100ms/1s 周期采样，适合与电机等噪声源同步错峰；
2. **模拟看门狗**：`HAL_ADC_ConfigAnalogOscillator` → 实际 API 为通道级看门狗配置（LTR/HTR 阈值），MP-4 电压越上限即触发报警中断，比主循环轮询响应快且不占 CPU；
3. **注入通道优先级**：若将来增加"紧急超量程抢测"需求，把报警通道配成注入组即可插队规则序列。

---

## 9. 本章小结

1. ADC 采集链：输入范围（0~3.3V 硬约束）→ 通道映射（PC3=CH13、PC4=CH14，查表选脚）→ Rank 定序列 → 软件触发 → 转换时间 = 采样时间 + 12 周期（高阻抗信号源配 144 周期采样）→ DR 单寄存器必须 DMA 搬 → 码值×VREF/4095 还原电压、再反推 Rs。
2. HAL 三层结构：`ADC_HandleTypeDef`（管全局）→ `ADC_InitTypeDef`（ADC 级参数，扫描/连续/触发）→ `ADC_ChannelConfTypeDef`（通道级 Rank/采样时间），CubeMX 面板逐项对应。
3. 本实验传感器板为**板载 4.7kΩ 串联 + 4.7kΩ 下拉**的分压结构，输出天然限制在 ≤2.5V，直接进 ADC 无需外加衰减；5V 供电、强制共地，电源轨靠 10µF+100nF 去耦压制加热丝纹波。
4. 多通道标准姿势：Scan + Continuous + DMA Circular 一次启动循环采集；报警类场景升级定时器触发与模拟看门狗。
5. MP-4（燃气）与 MP503（空气质量）原理同类：加热 SnO₂ 电阻 Rs 随气体浓度下降，板载分压网络把 Rs 变化转成电压；软件按 `Rs = VS×R下/Vout − (R串+R下)` 反推元件电阻，定量浓度还需 R₀ 标定 + 规格书 Rs/R₀—浓度曲线。

## 10. 常见问题速查

| 现象 | 最可能原因 | 处理 |
| --- | --- | --- |
| 读数始终 4095 | 引脚被外部强灌 >3.3V，或下拉电阻虚焊（节点悬空漂高） | 查 R1207/R1185 焊接；确认传感器板供电与接线 |
| 读数始终 0 | 输出网络未接通/GND 未共地/引脚模式错 | 查 PC3/AIR、PC4/GAS 飞线；确认 CubeMX 里引脚为 Analog Mode |
| 两路数据对调 | Rank 与数组下标不一致 | CH13=Rank1→`[0]`，CH14=Rank2→`[1]` |
| 数值偏低且抖动 | 采样时间太短（源阻抗约 2.6~4.5kΩ） | 采样时间升到 144/480 周期 |
| 上电读数一路漂 | 传感器预热期 | 丢弃前 2~5 分钟数据再判定 |
| 重新生成代码丢配置 | 手写代码在 CubeMX 管理区 | 代码只写进 `USER CODE BEGIN/END` 块 |
| DMA 不更新数组 | MspInit 里忘记 `__HAL_LINKDMA` 或 DMA 时钟未开 | 用 CubeMX 重新生成，勿手删 MspInit 片段 |
