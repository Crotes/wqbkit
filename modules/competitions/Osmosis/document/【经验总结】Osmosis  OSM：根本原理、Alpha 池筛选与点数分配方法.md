---
title: "【经验总结】Osmosis / OSM：根本原理、Alpha 池筛选与点数分配方法"
source: "https://support.worldquantbrain.com/hc/en-us/community/posts/40346082255255--%E7%BB%8F%E9%AA%8C%E6%80%BB%E7%BB%93-Osmosis-OSM-%E6%A0%B9%E6%9C%AC%E5%8E%9F%E7%90%86-Alpha-%E6%B1%A0%E7%AD%9B%E9%80%89%E4%B8%8E%E7%82%B9%E6%95%B0%E5%88%86%E9%85%8D%E6%96%B9%E6%B3%95"
author:
published: 2026-05-09
created: 2026-05-11
description: "0. 结论先说 本文只讨论 Osmosis / OSM。 Osmosis 的表面动作是给符合规则的已提交 Alpha 分配 OsmosisPoints，但它的本质不是“点数游戏”，而是一个带平台规则约束的 Alpha 组合配置问题。 从根本原理看，提升 OSM..."
tags:
  - "clippings"
---
## 0\. 结论先说

本文只讨论 **Osmosis / OSM** 。

`Osmosis` 的表面动作是给符合规则的已提交 Alpha 分配 `OsmosisPoints` ，但它的本质不是“点数游戏”，而是一个带平台规则约束的 **Alpha 组合配置问题** 。

从根本原理看，提升 OSM 不是靠猜哪种分点脚本更神，而是靠三件事：

- **Alpha 池质量** ：被分配点数的 Alpha 是否更可能在样本外有正贡献。
- **组合结构** ：这些 Alpha 是否低相关、低集中、风险暴露互补。
- **权重分配** ： `OsmosisPoints` 是否把更多风险预算给了可靠信号，同时避免单点过度暴露。

一句话：

> 先提高 Alpha 池的真实边际贡献，再谈点数分配。点数分配只能改变暴露，不能创造 Alpha 质量。

---

## 1\. Osmosis 到底是什么

## 1.1 表面定义

在 Osmosis 相关规则中，用户需要从已提交 Alpha 中选择符合资格的 Alpha，并为它们分配 `OsmosisPoints` 。

常见规则包括：

- 每个地区/赛区需要分配固定总点数，例如 `100000` 。
- Alpha 必须满足当期规则要求，例如状态、类型、地区、Delay、是否可更新点数等。
- 通常要求每个地区至少有一定数量的合格 Alpha。
- 平台或比赛会基于这些带权 Alpha 池计算相应的组合表现、排名或 OSM 指标。

具体约束要以当期官方规则为准。不要把某次比赛的 `100000` 点、 `至少 10 条 Alpha` 等规则理解成所有时期永久不变的数学定律。

## 1.2 根本定义

如果把 `OsmosisPoints` 看成组合权重，那么 Osmosis 本质上是在做：

```
在一组符合规则的 Alpha 中，
选择哪些 Alpha 进入组合，
以及每个 Alpha 分配多少权重。
```

组合的核心关系可以抽象为：

```
组合收益 ≈ Σ w_i * r_i
组合风险 ≈ w' Σ w
组合表现 ≈ 费后收益 / 组合波动
```

其中：

- `w_i` ：第 `i` 个 Alpha 的点数权重。
- `r_i` ：第 `i` 个 Alpha 的样本外收益贡献。
- `Σ` ：Alpha 之间的协方差/相关性结构。
- 费用影响主要通过 `margin` 、 `turnover` 、region fee model、流动性和 investability 体现。

所以，OSM 的核心不是单个 Alpha 的 IS 指标，而是：

> 带权 Alpha 池在样本外、费后、考虑相关性后的整体风险调整表现。

---

## 2\. 最容易犯的错误

## 2.1 把 Osmosis 理解成点数技巧

错误理解：

> 只要找到一个好的分点公式，OSM 就能提高。

根本问题：

- 如果 Alpha 池本身低质量，分点公式只能决定亏损从哪里来。
- 如果 Alpha 彼此高度相关，分散点数只是表面分散。
- 如果 Alpha 费后表现差，IS Sharpe 再好也可能拖累组合。

正确理解：

> 点数分配是最后一步。第一步是筛出真正值得承载风险预算的 Alpha。

## 2.2 全选一锅煮

论坛中很多经验都指向同一个结论：

> Alpha 池里“独特与优异”比数量更重要。

全选的风险：

- 低质量 Alpha 会稀释或抵消高质量 Alpha。
- 相似 Alpha 会放大同一类风险暴露。
- 一个负 OS Alpha 可能需要多个正 OS Alpha 才能弥补。
- 高 turnover、低 margin 的 Alpha 可能在费后拖累组合。

数量可以降低部分随机波动，但不能弥补负期望和伪多样性。

## 2.3 只看 IS Sharpe / Fitness

`IS Sharpe` 和 `Fitness` 有价值，但它们不是 Osmosis 的最终目标。

高 IS 可能来自：

- 参数调优过度。
- 特定年份或特定 regime 的偶然收益。
- 高 turnover 下未充分体现费后损耗。
- 与已有 Alpha 高度重叠。
- 复杂表达式带来的自由度过高。

更稳健的做法是把 IS 指标作为候选输入之一，同时结合：

- yearly stats
- PnL 路径
- margin
- turnover
- drawdown
- correlation
- signal purity
- economic rationale
- OS/IS prior

---

## 3\. Osmosis 的根本决定因素

## 3.1 单 Alpha 的样本外正贡献概率

一个 Alpha 是否值得分配点数，根本上取决于它未来样本外是否更可能带来正的费后边际贡献。

可观察的代理变量包括：

- **IS Sharpe / Fitness** ：基础质量指标，但不能单独使用。
- **Yearly Sharpe 均值和稳定性** ：判断是否长期有效。
- **Positive year ratio** ：盈利年份占比。
- **Recent trend** ：最近几年是否持续恶化。
- **Drawdown** ：是否有不可接受的尾部风险。
- **Margin** ：收益空间是否足以覆盖成本。
- **Turnover** ：交易频率是否造成费用侵蚀。
- **PnL smoothness** ：收益是否过度依赖少数跳变。
- **经济逻辑** ：信号是否有可以解释的来源。

## 3.2 Alpha 之间的协方差结构

OSM 是组合问题，不是单 Alpha 问题。

两个 Alpha 单独看都不错，但如果 PnL 高度相关，它们对组合的边际贡献会下降。

需要区分几种相关性：

- **PnL correlation** ：最接近组合风险，直接反映收益路径是否同涨同跌。
- **Drawdown overlap** ：反映尾部风险是否同时爆发。
- **Self-correlation** ：账号内部 Alpha 是否重复。
- **Prod-correlation** ：与平台生产信号是否相似，影响独特性和提交价值。
- **Expression / field similarity** ：用于提前识别伪多样性，但不等于真实 PnL 独立。

对 Osmosis 权重分配而言， `PnL correlation` 和 `drawdown overlap` 比表面字段差异更重要。

## 3.3 费后约束

Osmosis 不能只看毛收益或 IS Sharpe。组合最终要经受费用和交易约束。

关键变量：

- **Margin** ：利润空间。
- **Turnover** ：交易频率。
- **Region** ：不同地区交易成本和市场结构不同。
- **Liquidity / Investability** ：信号能否实际承载规模。
- **Decay** ：平滑收益与降低 turnover 的权衡。

更准确地说：

> Margin 和 Turnover 是费后表现能否成立的核心约束，而不是唯一决定因素。

## 3.4 权重集中度

点数越集中，组合越接近押注少数 Alpha。

集中有优点：

- 如果头部 Alpha 真实质量很高，短期可能冲高。
- 能更充分利用高置信度信号。

集中也有风险：

- 评分误差会被放大。
- 单个 Alpha 失效会显著拖累 OSM。
- 同一 cluster 被过度押注时，regime shift 风险变大。

因此，权重分配应同时控制：

- 单 Alpha 上限。
- 单 cluster 上限。
- 单数据集/单范式上限。
- 最低有效 Alpha 数。

---

## 4\. OS/IS 在 Osmosis 中的正确位置

`OS/IS Ratio = OS Sharpe / IS Sharpe` 。

它在 Osmosis 中有用，但它不是 Osmosis 本身。

正确定位：

> OS/IS 是判断字段、数据集、模板或 Alpha 历史抗衰减能力的先验，用于帮助筛选 Alpha 池和设置权重置信度。

需要注意：

- 字段级/数据集级 OS/IS 是历史提交 Alpha 的聚合统计，不是单个 Alpha 的未来保证。
- 高 OS/IS 表示历史衰减较低，但不代表绝对 Sharpe 一定高。
- 如果 IS Sharpe 很低，OS/IS ratio 本身可能不稳定。
- OS/IS 可能有样本选择偏差和幸存者偏差。
- 高 OS/IS 只能提高置信度，不能替代 yearly stats、PnL、成本和相关性检查。

因此，本文把 OS/IS 作为 `quality_score` 的一部分，而不是最终目标。

---

## 5\. Alpha 池筛选流程

## Step 1：建立候选 Alpha 表

按 region 拉出所有可能参与 Osmosis 的 Alpha，至少记录：

- `alpha_id`
- `region`
- `type`
- `status`
- `delay`
- `is.sharpe`
- `is.fitness`
- `is.margin`
- `is.turnover`
- `is.drawdown`
- `is.returns`
- `prodCorrelation`
- `selfCorrelation`
- `yearly_stats`
- `pnl`
- `osmosisPoints`
- 是否符合当期 Osmosis 资格规则
- 是否可更新 `OsmosisPoints`
- 数据集、字段、operator、template、neutralization 等元信息

如果已有 OS 或 semi-OS 数据，也应加入：

- `os.sharpe`
- `os.fitness`
- `OS/IS ratio`
- 近期 OS trend

## Step 2：资格过滤

先剔除不具备参与资格的 Alpha：

- 非 Active。
- 不能设置 `OsmosisPoints` 。
- 不符合当期活动规则。
- 地区、Delay、类型不满足要求。
- 指标缺失严重。
- 明显异常或不可解释的 Alpha。

这一步是规则过滤，不是质量判断。

## Step 3：基础质量过滤

再剔除明显不适合承载点数的 Alpha。

重点看：

- Sharpe 是否过低。
- Fitness 是否过低。
- Margin 是否太低。
- Turnover 是否极端。
- Drawdown 是否异常。
- Returns 是否不足以覆盖风险。
- PnL 是否只靠少数跳变。
- 最近几年是否持续恶化。

注意：固定阈值只能作为保守初筛，不应机械执行。

例如：

- `Sharpe > 1.58`
- `Fitness > 1.0`
- `Margin > 10bp`

这些可以作为较保守的经验门槛，但最终是否纳入 Osmosis 池，应看该 Alpha 对组合的边际贡献。

## Step 4：年度稳定性评估

不要只看整体 IS。

建议评估：

- 最近 `3-4` 年 Sharpe 均值。
- Sharpe 标准差。
- 正收益年份占比。
- 最近一年是否明显退化。
- 最近两年是否抬头。
- 是否只靠单一年份爆发。

一个启发式评分：

```
year_score =
  0.35 * recent_sharpe_mean_rank
+ 0.25 * positive_year_ratio
+ 0.20 * low_sharpe_std_rank
+ 0.20 * recent_trend_rank
```

这个公式不是绝对真理，只是把“长期稳定性”显式纳入筛选。

## Step 5：相关性剪枝

按 region 或规则要求的赛区分组，对候选池去重。

建议：

- PnL correlation `> 0.7` ：原则上二选一，除非二者在尾部风险或成本结构上明显互补。
- PnL correlation `0.4-0.7` ：可同时保留，但降低权重。
- 同数据集 + 同字段 + 同模板 + 同 operator：只保留最稳的几个。
- 同期 drawdown 高度重叠：降低同组总权重。
- 表达式不同但 PnL 高相关：按高相关处理。

保留多样性时，应优先保证主信号不同，而不是只追求表面字段或算子不同。

---

## 6\. 综合质量评分

推荐构造一个综合质量分，而不是只按 Sharpe 排序。

一个可用的启发式结构：

```
quality_score =
  0.25 * IS_quality
+ 0.25 * yearly_stability
+ 0.20 * cost_quality
+ 0.15 * OS_or_OSIS_prior
+ 0.15 * uniqueness_score
```

其中：

- **IS\_quality** ：Sharpe、Fitness、Returns、Drawdown 的综合质量。
- **yearly\_stability** ：年度均值、年度波动、正收益年份占比、近期趋势。
- **cost\_quality** ：Margin 高、Turnover 合理、费后可持续。
- **OS\_or\_OSIS\_prior** ：有真实 OS 用真实 OS；没有则用字段/数据集/模板 OS/IS prior。
- **uniqueness\_score** ：低相关、低集中、信号逻辑独特。

这个分数的作用不是预测未来的精确收益，而是帮助排序和分配权重置信度。

---

## 7\. Alpha 数量：不要迷信固定个数

论坛经验中，常见做法是每个 region 选择 `15-20` 个高质量 Alpha。

这个经验有参考价值：

- `10` 个左右：可能冲高，但波动更大。
- `15-25` 个：通常更均衡。
- `30+` 个：更稳定，但如果质量参差，会稀释头部信号。
- 全选：容易引入低质量和高相关 Alpha。

但根本不是数量，而是：

> 有效独立 Alpha 数量。

例如：

- 20 个高度相关 Alpha，可能只等价于很少的有效信号。
- 8 个低相关、高质量 Alpha，可能比 30 个同质 Alpha 更好。
- 某个地区整体质量差时，强行凑数量可能不如少配或暂缓参与。

因此，数量应由质量分布、相关矩阵和规则约束共同决定。

---

## 8\. OsmosisPoints 分配方法

## 8.1 稳定型：质量分加权

适合质量分可信、目标偏稳定的情况：

```
points_i = 100000 * quality_score_i / Σ quality_score
```

建议加约束：

- 单 Alpha 最低有效点数。
- 单 Alpha 最高点数。
- 单 cluster 最高点数。
- 单数据集/单范式最高点数。

优点：

- 简单透明。
- 不容易过度集中。
- 适合 Alpha 池质量较均衡的情况。

风险：

- 如果 quality\_score 区分度不足，优秀 Alpha 权重可能不够。
- 如果低质量 Alpha 没被过滤干净，仍会获得点数。

## 8.2 进攻型：Softmax 加权

适合对头部 Alpha 置信度较高、愿意承担波动的情况：

```
points_i = softmax(z_score(quality_score_i) / temperature)
```

注意：

- Softmax 前必须先对 `quality_score` 标准化或 rank-normalization。
- `temperature` 越小，权重越集中。
- `temperature` 越大，权重越均衡。
- Softmax 会放大评分误差，不适合噪声很大的质量分。

建议仍然设置：

- 单 Alpha 上限。
- 单 cluster 上限。
- 最低有效 Alpha 数。

## 8.3 混合型：质量 + 排名 + 多样性

更稳健的启发式方案：

```
final_weight =
  0.50 * normalized_quality
+ 0.25 * rank_decay_weight
+ 0.25 * cluster_balancing_weight
```

含义：

- `normalized_quality` ：让高质量 Alpha 获得更多权重。
- `rank_decay_weight` ：保证排名靠前者有明确优势。
- `cluster_balancing_weight` ：避免同一类 Alpha 过度集中。

注意：

> `0.50 / 0.25 / 0.25` 只是初始启发式，不是固定真理。最终参数应通过历史 OSM、OS 或 semi-OS 表现滚动验证。

---

## 9\. 复盘与迭代

Osmosis 不应该每天因短期波动频繁乱改，但也不能长期不复盘。

建议每周或每次 OSM 更新后检查：

- 哪个 region 拖累整体表现。
- 哪些 Alpha 可能贡献为负。
- 哪些 cluster 同时亏损。
- 是否某个数据集或模板过度集中。
- 高 turnover / 低 margin Alpha 是否拖累费后表现。
- 新 OS 更新后，哪些 Alpha 的 OS/IS 或 OS 表现显著恶化。
- 点数集中度是否过高。
- 是否有新增高质量 Alpha 可以替换旧 Alpha。

复盘时不要只看单期排名，要看：

- 排名变化是否持续。
- PnL 是否稳定。
- 风险是否集中。
- 换 Alpha 后是否提高组合的边际贡献。

---

## 10\. 推荐实战流程

如果目标是系统性提升 Osmosis，建议按以下顺序执行：

1. **导出每个 region 的候选 Alpha 表。**
2. **剔除不符合 Osmosis 规则的 Alpha。**
3. **剔除明显低质量 Alpha。**
4. **计算年度稳定性指标。**
5. **计算 margin / turnover / drawdown 等费后约束指标。**
6. **计算 PnL correlation 和 drawdown overlap。**
7. **按质量和相关性进行剪枝，形成候选池。**
8. **构造综合 `quality_score` 。**
9. **按稳定型、进攻型或混合型方法分配 `OsmosisPoints` 。**
10. **设置单 Alpha、单 cluster、单数据集上限。**
11. **提交点数分配后按周复盘。**
12. **基于真实更新结果迭代质量分和权重参数。**

---

## 11\. 关键认知

- **Osmosis 的本质是 Alpha 组合配置，不是简单点数技巧。**
- **点数是权重，权重只改变暴露，不能创造信号质量。**
- **Alpha 池质量是第一层，相关性结构是第二层，点数分配是第三层。**
- **多样性不是字段或表达式看起来不同，而是 PnL 和风险来源真的不同。**
- **OS/IS 是有用的泛化先验，但不是单个 Alpha 未来表现的保证。**
- **Margin / Turnover 是费后表现能否成立的核心约束。**
- **小而美、纯粹、有经济解释的 Alpha，往往比复杂高 IS Alpha 更有样本外生存概率，但仍需数据验证。**
- **固定阈值和固定数量都只是启发式，最终要看组合边际贡献。**

---

## 12\. 最终总结

Osmosis 应该被理解为：

> 在平台规则允许的 Alpha 集合中，选择一批更可能在样本外有正贡献、低相关、费后可持续、年度表现稳定、信号逻辑纯粹的 Alpha，并用有上限、有多样性约束的权重方法分配 `OsmosisPoints` 。

最重要的不是“怎么把 100000 点分完”，而是：

> 哪些 Alpha 值得拿点数，以及它们放在一起后是否真的提高组合表现。

最终原则：

> 先做 Alpha 池质量控制，再做相关性和集中度控制，最后才做点数分配。