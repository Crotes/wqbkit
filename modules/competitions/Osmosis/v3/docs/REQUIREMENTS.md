# Osmosis v3.0 需求文档

> **目标**：在 v2.0 基础上，补齐文档要求的全部关键环节，将 Osmosis 从"前向筛选+Softmax 分配"升级为"全链路质量评估 + 组合风险感知 + 约束化分配 + 迭代复盘"的系统。

---

## 1. 背景：V2.0 现状与差距

V2.0 已完成：
- 三层粗筛（Hard Filters → Prod Correlation → Diversification）
- 多策略分配器（equal / score_prop / inverse_vol / mdc / greedy_sharpe / risk_parity）
- 黑名单、缓存、并发 API 更新
- 按 Region 批量跑批

**与官方文档/社区最佳实践的系统性差距**（详见 `../v2_0/` 分析）：

| 维度 | 文档要求 | V2.0 现状 | 差距等级 |
|------|---------|----------|---------|
| 年度稳定性 | `quality_score` 中占 25% | ✅ 已实现 yearly-stats + stability score | ✅ 完成 |
| OS/IS 先验 | `quality_score` 中占 15% | ✅ 已实现 OS/IS proxy | ✅ 完成 |
| PnL Correlation | 核心去重指标，>0.7 二选一 | ✅ 已实现 PnL corr + drawdown overlap | ✅ 完成 |
| 分配上限约束 | 单 Alpha / Cluster / 数据集上限 | ❌ 待 allocator_v3 实现 | 🔴 高 |
| Drawdown Overlap | 降低同步回撤组权重 | ✅ 已实现 (threshold=0.8) | ✅ 完成 |
| Cluster Balancing | 分配阶段 diversity 约束 | ❌ 待 allocator_v3 实现 | 🟡 中 |
| Neutralization 分散 | 操作+中性化双重分散 | ✅ 已实现 | ✅ 完成 |
| Self-Correlation | 账号内部重复识别 | ✅ 已实现 selfCorrelation 提取 | ✅ 完成 |
| Investability | MaxTradeOn + investability filter | ✅ 已实现 (软过滤，评分降权) | ✅ 完成 |
| Delay 维度 | scope = region × delay | ❌ 待 runner_v3 实现 | 🟡 中 |
| PnL Smoothness | 收益路径分析 | ❌ 未实现 | 🟢 低 |
| Turnover Buckets | <10%, 10-20%, >20% 分桶 | ❌ 未实现 | 🟢 低 |
| 复盘迭代 | 历史验证参数 | ❌ 待 replay_v3 实现 | 🟢 低 |

---

## 2. V3.0 总体目标

将 Osmosis 重新定义为 **Alpha 组合配置问题**，而非单纯的"点数分配"。V3.0 需要实现：

1. **更丰富的 Alpha 质量评估**：引入年度稳定性、OS/IS 先验、self-correlation、investability 衰减
2. **组合风险感知**：以 PnL correlation 替代 prodCorrelation，引入 drawdown overlap
3. **约束化分配**：单 Alpha 上限、cluster 上限、数据集上限、最低有效 Alpha 数
4. **Scope 完整覆盖**：正确处理 `region × delay` 组合
5. **复盘与迭代**：记录分配历史，关联后续 OSM 表现，滚动优化参数

---

## 3. 模块拆分与详细需求

### 3.1 `osmosis_selector_v3.py` — 粗筛器增强

#### 3.1.1 数据获取增强

**filter_alphas 返回的字段（`_parse_alpha_item()` 扩展提取）：**

```python
required_new_fields = {
    # OS 指标（os 对象始终存在但可能为空，需判断 os.sharpe is not None）
    "os_sharpe": item.get("os", {}).get("sharpe"),
    "os_fitness": item.get("os", {}).get("fitness"),
    "os_returns": item.get("os", {}).get("returns"),
    "os_is_ratio": item.get("os", {}).get("osISSharpeRatio"),  # 现成的 OS/IS ratio
    
    # 相关性（is 下已有）
    "selfCorrelation": is_data.get("selfCorrelation"),  # 账号内部相关性
    "prodCorrelation": is_data.get("prodCorrelation"),
    
    # 可投资性（is.investabilityConstrained 下始终存在）
    "inv_sharpe": is_data.get("investabilityConstrained", {}).get("sharpe"),
    "inv_fitness": is_data.get("investabilityConstrained", {}).get("fitness"),
    "inv_returns": is_data.get("investabilityConstrained", {}).get("returns"),
    "inv_drawdown": is_data.get("investabilityConstrained", {}).get("drawdown"),
    "inv_turnover": is_data.get("investabilityConstrained", {}).get("turnover"),
    "inv_margin": is_data.get("investabilityConstrained", {}).get("margin"),
    
    # MaxTradeOn（settings.maxTrade，字符串 "OFF"/"ON"）
    "max_trade": settings.get("maxTrade", "OFF"),
    
    # 中性化（settings 下已有）
    "neutralization": settings.get("neutralization", "unknown"),
    
    # 数据集类别（settings 中无 dataset 字段，从 tags 列表推断，支持多标签）
    "dataset_tags": item.get("tags", ["unknown"]) if item.get("tags") else ["unknown"],
}
```

**yearly-stats 额外 API（不在 filter_alphas 结果中）：**

```
GET /alphas/{alpha_id}/recordsets/yearly-stats
```

- 返回 `schema.properties` + `records`（二维数组，按 schema 顺序解析）
- 包含字段：year, pnl, bookSize, longCount, shortCount, turnover, sharpe, returns, drawdown, margin, fitness, stage
- `stage` 列区分 "IS" / "OS" 年份
- **获取策略**：只在 Layer 1 [HardFilter] 后对保留的候选获取，避免对全量 Alpha 调用；并发请求 + 24h 缓存

**完整数据获取流程：**

```
Step 1: filter_alphas API — 获取基础指标 + investabilityConstrained + os(可能空)
            ↓
Step 2: Layer 1 [HardFilter] — 硬性质量门槛过滤，保留 N 个候选
            ↓
Step 3: yearly-stats API — 对 N 个候选逐个获取年度统计（并发 + 缓存）
            ↓
Step 4: Layer 2 [Investability] — 可投资性衰减检查（日志提示，不淘汰）
            ↓
Step 5: Layer 3 [Correlation] — PnL correlation + drawdown overlap 去重
            ↓
Step 6: Layer 4 [Diversification] — dataset_tags + neutralization 分散化
            ↓
Step 5: get_alpha_results() — 获取 returns 矩阵（供 allocator 使用）
```

#### 3.1.2 新增筛选层

**Layer 2 [Investability]: 可投资性软检查**
- 计算 investability 衰减率：`decay = (is_sharpe - inv_sharpe) / is_sharpe`
- 衰减分级（配置可调）：
  - `severe_decay` (≥60%): 在 `quality_score` 中大幅降权（系数 0.2）
  - `moderate_decay` (40-60%): 中度降权（系数 0.6）
  - `mild_decay` (20-40%): 轻度降权（系数 0.85）
  - `stable` (<20%): 正常（系数 1.0）
- **不自动排除**衰减严重的 Alpha（避免误杀 unique 信号），仅在评分中降权，日志提示人工复核
- 对 `max_trade == "OFF"` 的历史 Alpha，标记 `needs_resim` 并记录到持久化映射表
- **MaxTrade 映射表**（`data/maxtrade_status.json`）：
  ```json
  {
    "alpha_id": {
      "original_maxTrade": "OFF",
      "has_maxTradeOn_sim": false,
      "maxTradeOn_sharpe": null,
      "maxTradeOn_fitness": null,
      "notes": "需要重新 simulation"
    }
  }
  ```
  - 用户手动完成 MaxTradeOn simulation 后更新此映射
  - 在 V3 筛选中，`has_maxTradeOn_sim=false` 的 Alpha 不自动排除，仅在日志中提示
  - 长期目标：当映射表中积累足够数据后，评估 MaxTradeOn 对各类 Alpha 的平均影响

**Layer 3 [Correlation]: PnL Correlation 替代 Prod Correlation**
- 保留 `prodCorrelation` 作为参考字段和 fallback
- 主逻辑：通过 `calculate_alpha_corr()` 获取候选 Alpha 的 returns 矩阵
- 计算 pairwise PnL correlation
- 阈值 > 0.7 时，保留 quality_score 更高的，另一个排除
- 阈值 0.4-0.7 时，允许保留但标记 `high_corr_flag`（供 allocator 降权）

**Layer 3 [Correlation] Drawdown Overlap 检测**
- 基于 returns 矩阵计算同步回撤期
- 定义 drawdown overlap = 两 Alpha 同时处于回撤期的天数 / max(各自回撤天数)
- 仅对 PnL correlation > 0.4 的 pair 检测 overlap
- overlap > 0.8（配置可调）的 pair，淘汰 quality_score 较低的
- SuperAlpha ↔ REGULAR 跳过淘汰（避免误杀 SuperAlpha）

**Layer 4 [Diversification]: Neutralization + Dataset Tags 维度**
- 增加 diversification 维度：
  - `top_k_neutralization`: max(5, min(15, n // 15))（配置可调）
  - `top_k_dataset_tag`: max(5, min(20, n // 12))（配置可调）
- dataset_tags 多标签分散：每个 tag 类别保留 top_k，Alpha 只要在一个 tag 中达标即可保留
- SuperAlpha 直接保留，不经过 diversification 过滤
- 过滤后总数 < min_alpha_count（默认 10）时回退到过滤前

#### 3.1.3 年度稳定性评分

新增方法 `compute_yearly_stability_score(df)`：

```python
def compute_yearly_stability_score(yearly_stats):
    """
    输入: yearly_stats 列表，每项 dict(year, sharpe, returns, drawdown, fitness, stage)
    输出: [0, 1] 之间的稳定性分数
    """
    if not yearly_stats or len(yearly_stats) < 2:
        return 0.5  # 默认值
    
    # 优先使用 IS 阶段的数据计算稳定性（OS 数据太新可能样本不足）
    is_records = [s for s in yearly_stats if s.get("stage") == "IS"]
    records = is_records if len(is_records) >= 3 else yearly_stats
    
    sharpe_list = [s["sharpe"] for s in records if s.get("sharpe") is not None]
    if len(sharpe_list) < 2:
        return 0.5
    
    recent_sharpe_mean = np.mean(sharpe_list[-3:])  # 最近3年
    positive_year_ratio = sum(1 for s in sharpe_list if s > 0) / len(sharpe_list)
    sharpe_std = np.std(sharpe_list)
    
    # 启发式评分
    score = (
        0.35 * _normalize(recent_sharpe_mean, sharpe_list) +
        0.25 * positive_year_ratio +
        0.20 * _normalize(-sharpe_std, [-s for s in sharpe_list]) +  # std 越低越好
        0.20 * _normalize(_trend_score(sharpe_list), [0, 1])
    )
    return clip(score, 0, 1)
```

#### 3.1.4 OS/IS 先验评分

新增方法 `compute_os_is_score(df)`：

```python
def compute_os_is_score(row):
    """
    优先使用真实 OS 数据，否则尝试从字段/数据集级 prior 推断
    """
    os_is_ratio = row.get("os_is_ratio")
    is_sharpe = row.get("sharpe", 0)
    
    # 优先使用现成的 osISSharpeRatio
    if pd.notna(os_is_ratio):
        # ratio 在 0.5-1.0 之间较好，<0.3 较差
        return _sigmoid((os_is_ratio - 0.5) * 4)  # 映射到 [0,1]
    
    # 无 osISSharpeRatio 时，用 inv_sharpe / is_sharpe 作为代理
    inv_sharpe = row.get("inv_sharpe")
    if pd.notna(inv_sharpe) and is_sharpe > 0:
        proxy_ratio = inv_sharpe / is_sharpe
        return _sigmoid((proxy_ratio - 0.5) * 4) * 0.7  # 可信度打 7 折
    
    return 0.5  # 默认值
```

---

### 3.2 `osmosis_allocator_v3.py` — 约束化分配器

#### 3.2.1 综合质量评分重构

`_compute_composite_score()` 重构为文档推荐的五维结构：

```python
quality_score = (
    0.25 * is_quality +      # fitness, sharpe, returns, drawdown, turnover 综合
    0.25 * yearly_stability + # 年度稳定性（新增）
    0.20 * cost_quality +     # margin, turnover, investability（增强）
    0.15 * os_is_prior +      # OS/IS 或 investability proxy（新增）
    0.15 * uniqueness_score   # self_corr, prod_corr, PnL corr（新增）
)
```

其中 `uniqueness_score`：
- 基于 self_correlation（越低越好）
- PnL correlation 均值（越低越好）
- prodCorrelation（越低越好）
- 组合方式：rank-normalized 后加权平均

#### 3.2.2 分配约束系统

**约束配置（可配置）：**

```python
DEFAULT_CONSTRAINTS = {
    "min_score_per_alpha": 1,          # 单 Alpha 最低 1 点（保留）
    "max_score_per_alpha": 15000,       # 单 Alpha 最高 15,000 点
    "max_score_per_cluster": 30000,     # 单 cluster（primary_field + primary_op）最高 30,000
    "max_score_per_dataset_tags": 35000,     # 单数据集类别最高 35,000（基于 tags）
    "max_score_per_neutralization": 40000,  # 单中性化方式最高 40,000
    "min_alpha_count": 10,              # 最低有效 Alpha 数（保留）
    "max_alpha_count": 35,              # 最高有效 Alpha 数（新增）
}
```

**约束后处理流程：**

```
1. 原始分配（softmax / 混合方法）
2. 应用单 Alpha 上限：score = min(score, max_score_per_alpha)
3. 应用 cluster 上限：对超额 cluster，按比例压缩该 cluster 内所有 Alpha
4. 应用 dataset 上限：同上
5. 应用 neutralization 上限：同上
6. 重新校准总分 = 100,000
7. 应用单 Alpha 下限：score = max(score, min_score_per_alpha)
8. 最终校准总分
```

#### 3.2.3 新增分配方法：混合型（推荐默认）

实现文档 8.3 推荐的混合型：

```python
def _allocate_mixed(
    self, df, total_score,
    quality_weight=0.50,
    rank_decay_weight=0.25,
    cluster_balance_weight=0.25,
    temperature=0.15,
):
    """
    final_weight = 0.50 * normalized_quality
                 + 0.25 * rank_decay_weight
                 + 0.25 * cluster_balancing_weight
    """
    # 1. normalized_quality: softmax(quality_score / temperature)
    q_weights = _softmax(df["quality_score"], temperature)
    
    # 2. rank_decay_weight: 排名越靠前权重衰减越慢
    # e.g., rank_decay = 1 / sqrt(rank)
    df_sorted = df.sort_values("quality_score", ascending=False).reset_index(drop=True)
    ranks = df_sorted.index + 1
    rank_weights = (1.0 / np.sqrt(ranks))
    rank_weights = rank_weights / rank_weights.sum()
    
    # 3. cluster_balancing_weight: 鼓励 cluster 间均衡
    # 先统计各 cluster 的 quality_score 总和
    cluster_scores = df.groupby("primary_field")["quality_score"].transform("sum")
    # cluster 总分越高的，额外增加该 cluster 内 Alpha 的权重越少（inverse）
    cluster_balance = 1.0 / (1.0 + cluster_scores / cluster_scores.mean())
    cluster_balance = cluster_balance / cluster_balance.sum()
    
    # 组合
    final_weights = (
        quality_weight * q_weights +
        rank_decay_weight * rank_weights +
        cluster_balance_weight * cluster_balance
    )
    final_weights = final_weights / final_weights.sum()
    df["assigned_score"] = final_weights * total_score
    return df
```

**默认方法从 `score_prop` 改为 `mixed`。**

#### 3.2.4 PnL 相关方法增强

`greedy_sharpe` 和 `risk_parity`：
- 当前已支持 `returns_matrix`，但 runner 未传入
- V3 runner 需要在分配前调用 `selector.get_selected_returns()` 并传入

---

### 3.3 `osmosis_runner_v3.py` — Scope 感知的批量跑批

#### 3.3.1 Scope 定义

**从平台自动获取可用 scopes**（基于 `osmosis.json` 格式）：

```python
# 方式 1: 从平台拉取（推荐）
# GET /consultants/{id}/osmosis 或类似接口获取当前可用的 scopes
# 返回: [{"region": "USA", "delay": 1, "pointsAllocated": 100000, "alphas": 37}, ...]

# 方式 2: 配置覆盖（fallback）
DEFAULT_REGIONS = ["USA", "GLB", "EUR", "ASI", "IND"]  # 从平台数据动态发现
DEFAULT_DELAYS = [1]  # 当前只做 delay=1；架构预留 delay=0 扩展
```

**已确认的平台状态**（来自 osmosis.json）：
- 可用 regions（11 个）：AMR, ASI, CHN, EUR, GLB, HKG, JPN, KOR, MEA, USA, IND
- 已分配 scopes：USA/D1(37α), EUR/D1(19α), ASI/D1(10α), IND/D1(11α)
- ASI 仅 10 个 Alpha（正好门槛），筛选需保守
- delay=0 全部未分配

#### 3.3.2 跑批逻辑改造

```python
def run_scope(region, delay, update=False):
    """单个 scope 的完整流程"""
    df = selector.select(region=region, delay=delay, start_date=START_DATE)
    if len(df) < MIN_ALPHA_COUNT:
        return None
    
    # 获取 returns 矩阵（供 PnL-based 方法使用）
    returns = selector.get_selected_returns(df)
    
    # 分配
    df_alloc = allocator.allocate(
        df,
        method="mixed",  # V3 默认
        total_score=TOTAL_SCORE,
        temperature=0.15,
        returns_matrix=returns,  # 传入供 greedy_sharpe / risk_parity 使用
    )
    
    if update:
        clearer.clear(region=region, delay=delay)  # delay 过滤
        allocator.update_osmosis_points(df_alloc)
    
    return df_alloc
```

#### 3.3.3 多 Scope 聚合输出

- 输出每个 scope 的分配结果
- 汇总：跨 scope 的 Alpha 重叠情况（一个 Alpha 可能被分配到多个 scope）
- 提示：跨 scope 使用相同 Alpha 时，注意其在不同 region 的相关性

---

### 3.4 `osmosis_replay_v3.py` — 复盘与迭代模块（新增）

#### 3.4.1 数据记录

每次分配后记录：

```python
allocation_record = {
    "timestamp": datetime.now().isoformat(),
    "region": region,
    "delay": delay,
    "alpha_ids": df["id"].tolist(),
    "assigned_scores": dict(zip(df["id"], df["assigned_score"].tolist())),
    "quality_scores": dict(zip(df["id"], df["quality_score"].tolist())),
    "composite_metadata": {
        "method": "mixed",
        "temperature": 0.15,
        "constraints": {...},
    }
}
# 保存到 data/allocation_history/scope_{region}_{delay}.jsonl
```

#### 3.4.2 OSM 表现回拉

新增方法 `fetch_osm_performance()`：
- 从 WQB API 或平台页面获取历史 OSM 表现
- 记录：weekly OSM Sharpe、daily rank、combined performance
- 与 allocation_record 关联

#### 3.4.3 参数迭代建议

```python
def analyze_allocation_history(scope, weeks=4):
    """
    分析最近 N 周的分配历史与 OSM 表现，输出参数调整建议
    
    输出示例：
    - "temperature 0.15 时 Top5% 集中度 39%，但上周 OSM sharpe 下降 0.3，
         建议尝试 temperature 0.20 增加分散"
    - "dataset 'fundamental6' 在 3 个 scope 中共分配 45%，但实际 OS 贡献为负，
         建议收紧 dataset 上限至 25%"
    """
```

---

## 4. 文件结构

```
modules/competitions/Osmosis/v3/
├── REQUIREMENTS.md          # 本文档
├── osmosis_selector_v3.py   # 增强粗筛器
├── osmosis_allocator_v3.py  # 约束化分配器
├── osmosis_clear_v3.py      # 清除模块（继承 V2，增加 delay 过滤）
├── osmosis_runner_v3.py     # Scope 感知跑批
├── osmosis_replay_v3.py     # 复盘与迭代（新增）
└── data/
    ├── selector_cache/      # 候选缓存（filter_alphas 结果）
    ├── yearly_stats_cache/  # 年度统计缓存（24h TTL，历史数据不变）
    ├── allocation_history/  # 分配历史记录（jsonl）
    └── osm_performance/     # 回拉的 OSM 表现数据
```

---

## 5. 优先级与实施顺序

### Phase 1: 约束化分配（❌ 待实现）
1. ❌ 实现 `constraints` 配置和约束后处理
2. ❌ 单 Alpha 上限、cluster 上限、dataset 上限
3. ❌ 将默认方法从 `score_prop` 改为 `mixed`
4. ❌ 改造 `run_allocation` 支持 `region × delay` scope

**状态**：allocator_v3.py、runner_v3.py 尚未实现，当前仍使用 V2 分配器。
**预期效果**：防止 softmax 过度集中，降低单点失效风险。

### Phase 2: 质量评分增强（✅ 已完成）
5. ✅ 扩展 `_parse_alpha_item()` 获取 `os_sharpe`、`os_is_ratio`、`selfCorrelation`、`inv_*`；新增 `fetch_yearly_stats()` 批量获取年度统计
6. ✅ 实现 `yearly_stability_score`、`os_is_score`、`uniqueness_score`
7. ✅ 重构 `composite_score` 为五维 `quality_score`

**预期效果**：筛选和分配的输入质量显著提升。

### Phase 3: PnL 风险感知（✅ 已完成）
8. ✅ 将 Layer 3 [Correlation] 从 `prodCorrelation` 改为 PnL correlation
9. ✅ 实现 drawdown overlap 检测（threshold=0.8）
10. ✅ 在 diversification filter 中增加 neutralization + dataset_tags 维度

**预期效果**：组合层面的相关性风险被真正识别和控制。

### Phase 4: 复盘迭代（长期，持续）
11. 实现 `allocation_history` 记录
12. 实现 OSM 表现回拉
13. 实现参数建议输出

**预期效果**：从"一次性分配"进化为"数据驱动的迭代优化"。

---

## 6. 关键设计决策

### 6.1 PnL Correlation 的计算成本
- `get_alpha_results()` 获取 returns 矩阵，候选池通常 50-200 个 Alpha
- Pairwise correlation 计算量 O(n²)，在本地可接受
- **决策**：在 `selector.select()` 的 Layer 3 [Correlation] 中实时计算，不缓存（因为候选池每次可能变化）

### 6.2 OS/IS 数据缺失的处理
- `os` 对象始终存在但可能为空（os.sharpe is None）
- **决策**：优先使用现成的 `os.osISSharpeRatio`；无则通过 `inv_sharpe / is_sharpe` 做代理；两者都无则给默认值 0.5
- 不在筛选阶段硬性要求 OS 数据（否则会过度 kill）

### 6.5 API 速率限制与并发策略
- **平台限制**：2000 次/小时，次数充足
- **yearly-stats 调用量**：粗筛后通常 20-30 个 Alpha/region × 5 regions ≈ 150 次调用
- **并发策略**：使用 ThreadPool（如 8-16 线程）并发获取 yearly-stats，在 2000/小时限制下完全可行
- **缓存策略**：yearly-stats 历史数据不变，设 24h TTL；首次跑批后后续直接读缓存

### 6.3 Investability 60% 衰减规则
- 文档建议"declines by ~60% or more"时排除，除非 unique 或不同数据集
- **决策**：作为 Layer 2 [Investability] 的软检查——标记 `decay_label` 但不自动排除，在 quality_score 中通过 `decay_multiplier` 降权
- 理由：自动判断"是否 unique"需要更多上下文，人工复核更安全

### 6.4 Scope 的 Delay 值
- 用户当前未做 delay=0 的 Alpha，但架构预留扩展性
- **决策**：`DELAYS` 默认 `[1]`；runner 支持传入自定义列表（如 `[1, 0]`）
- Region 列表优先从平台 `osmosis.json` 动态获取，fallback 到配置列表
- ASI 仅 10 个 Alpha（正好门槛），该区域需放宽筛选条件或标记警告

---

## 7. 接口约定

### 7.1 Selector 输出 DataFrame 列要求

| 列名 | 来源 | 用途 |
|------|------|------|
| `id` | API | 唯一标识 |
| `sharpe` / `fitness` / `returns` / `drawdown` / `margin` / `turnover` | API IS | 基础质量 |
| `yearly_stats` | API IS | 年度稳定性 |
| `os_sharpe` / `os_fitness` | API OS | OS/IS 先验 |
| `selfCorrelation` | API IS | 独特性 |
| `inv_sharpe` | API IS investabilityConstrained | 可投资性代理 |
| `prodCorrelation` | API IS | 参考 |
| `expression` | API | operator / field 提取 |
| `neutralization` | API settings | 分散维度 |
| `dataset_tags` | API tags | 分散维度（支持多标签） |
| `type` | API | SUPER 特殊处理 |
| `quality_score` | 计算 | 分配输入 |
| `yearly_stability` | 计算 | quality_score 成分 |
| `os_is_score` | 计算 | quality_score 成分 |
| `uniqueness_score` | 计算 | quality_score 成分 |
| `high_corr_flag` | 计算 | PnL corr 0.4-0.7 标记 |
| `decay_label` | 计算 | investability 衰减分类标签 |

### 7.2 Allocator 输入要求

```python
df_required_columns = [
    "id", "quality_score",
    # "primary_field", "primary_op",  # TODO: 用于 cluster 约束（尚未实现提取）
    "dataset_tags", "neutralization",  # 用于 dataset/neutralization 约束
]
```

---

## 8. 验收标准

### 8.1 功能验收
- [ ] `mixed` 分配方法实现并可通过 `method="mixed"` 调用
- [ ] 单 Alpha 上限约束生效（如设 15,000，无 Alpha 超过）
- [ ] Cluster 上限约束生效（如同一 field+op 组合总分不超过 30,000）
- [ ] Dataset 上限约束生效
- [ ] `yearly_stability_score` 计算正确（输入 yearly_stats 列表，输出 [0,1]）
- [ ] `os_is_score` 在有 OS 数据时使用 OS/IS ratio，无则使用 investability proxy
- [ ] Runner 支持 `region × delay` 组合跑批
- [ ] 分配历史记录到 `data/allocation_history/`

### 8.2 质量验收
- [ ] 与 V2 对比：在相同候选池上，`mixed` 方法的 Gini 系数应介于 `score_prop(t=0.05)` 和 `equal` 之间
- [ ] Top 5% Alpha 的点数占比应在 30%-45% 之间（V2 t=0.15 时约 39%）
- [ ] 单 cluster 点数占比不超过 35%
- [ ] 单 dataset 点数占比不超过 40%

### 8.3 稳定性验收
- [ ] 每次跑批后 `assigned_score` 总和严格等于 100,000
- [ ] 所有 Alpha `assigned_score >= 1`
- [ ] API 更新成功率 >= 95%
- [ ] 异常情况（API 失败、数据缺失）下 graceful fallback，不崩溃

---

*文档版本: v3.0-draft*
*最后更新: 2026-05-09*
