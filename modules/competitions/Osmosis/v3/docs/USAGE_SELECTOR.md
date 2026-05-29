# OsmosisAlphaSelectorV3 使用指南

## 1. 基础用法

### 1.1 初始化

```python
from modules.competitions.Osmosis.v3.osmosis_selector_v3 import OsmosisAlphaSelectorV3
from datetime import datetime

selector = OsmosisAlphaSelectorV3()
```

初始化时会自动：
- 登录 WQB API
- 加载黑名单（`data/selector_cache/blacklist.json`）
- 加载 MaxTrade 映射表（`data/maxtrade_status.json`）
- 创建缓存目录

### 1.2 执行完整筛选（推荐）

```python
df = selector.select(
    region="EUR",                    # 必填: USA/GLB/EUR/ASI/IND 等
    start_date=datetime(2025, 4, 19), # 可选: 只保留该日期后创建的 Alpha
    delay=1,                         # 可选: 1 或 0，默认 None（返回所有 delay）
    use_cache=True,                  # 可选: 是否使用本地缓存（默认 True）
    fetch_yearly_stats=True,         # 可选: 是否获取年度统计（首次建议 True）
)

print(f"选中 {len(df)} 个 Alpha")
print(df[['id', 'type', 'sharpe', 'fitness', 'quality_score', 'decay_label', 'dataset_tags']].head())
```

**输出列包含：**
- `id`, `type`, `expression` — 基础信息
- `sharpe`, `fitness`, `returns`, `margin`, `turnover`, `drawdown` — IS 指标
- `quality_score` — **核心评分** [0, 1]，分配权重的主要依据
- `yearly_stability`, `os_is_score`, `uniqueness_score` — 子评分
- `decay_label`, `decay_multiplier` — investability 衰减分类
- `dataset_tags`, `neutralization` — 多样性维度
- `yearly_stats` — 年度统计原始数据（列表）

---

## 2. 常用场景

### 2.1 快速预览（不获取 yearly-stats，避免 API 调用）

```python
df = selector.select(region="USA", fetch_yearly_stats=False)
# 使用本地缓存的候选数据，跳过 yearly-stats API 调用
# 此时 yearly_stability = 0.5（默认值），其他评分正常计算
```

### 2.2 首次完整跑批（获取全部数据）

```python
for region in ["USA", "EUR", "ASI", "IND"]:
    df = selector.select(region=region, fetch_yearly_stats=True)
    # 第一次会调用 yearly-stats API（并发，约 20-30 个 Alpha/region）
    # 结果缓存 24 小时，后续重复调用直接读缓存
```

### 2.3 检查单个 Alpha 的详细评分

```python
df = selector.select(region="EUR", fetch_yearly_stats=True)
alpha = df[df['id'] == '某个AlphaID'].iloc[0]

print(f"quality_score: {alpha['quality_score']:.3f}")
print(f"  - IS质量: {alpha['sharpe']:.2f} sharpe, {alpha['fitness']:.2f} fitness")
print(f"  - 年度稳定性: {alpha['yearly_stability']:.3f}")
print(f"  - OS/IS先验: {alpha['os_is_score']:.3f}")
print(f"  - 独特性: {alpha['uniqueness_score']:.3f}")
print(f"  - 衰减状态: {alpha['decay_label']} (系数 {alpha['decay_multiplier']})")
print(f"  - dataset_tags: {alpha['dataset_tags']}, neutralization: {alpha['neutralization']}")
```

---

## 3. 黑名单管理

```python
# 添加 Alpha 到黑名单（永久排除）
selector.add_to_blacklist(["alpha_id_1", "alpha_id_2"], reason="表现持续恶化")

# 查看黑名单
print(selector.list_blacklist())

# 从黑名单移除
selector.remove_from_blacklist(["alpha_id_1"])

# 清空黑名单
selector.clear_blacklist()
```

> 黑名单保存在 `data/selector_cache/blacklist.json`，持久化存储。

---

## 4. MaxTrade 映射表

### 4.1 查看需要重新 simulation 的 Alpha

```python
df = selector.select(region="EUR", fetch_yearly_stats=False)
needs_resim = df[
    (df['max_trade'] == 'OFF') & 
    ~df['id'].apply(lambda aid: selector.get_maxtrade_status(aid).get('has_maxTradeOn_sim', False))
]
print(f"需要 MaxTradeOn simulation 的 Alpha: {needs_resim['id'].tolist()}")
```

### 4.2 更新映射表（手动完成 simulation 后）

```python
# 用户手动在平台上完成 MaxTradeOn simulation 后，记录结果
selector.update_maxtrade_status(
    alpha_id="某个AlphaID",
    has_maxTradeOn_sim=True,
    maxTradeOn_sharpe=1.85,
    maxTradeOn_fitness=1.62,
    notes="MaxTradeOn 后表现良好",
)
```

> 映射表保存在 `data/maxtrade_status.json`。

---

## 5. 缓存管理

```python
# 清空候选缓存（强制下次从 API 重新获取）
selector.clear_cache("candidates")

# 清空 yearly-stats 缓存
# （手动删除 data/yearly_stats_cache/ 下的 json 文件）

# 查看缓存目录
import os
print(os.listdir(selector.cache_dir))
print(os.listdir(selector.yearly_stats_dir))
```

---

## 6. 获取 Returns 矩阵（供 Allocator 使用）

```python
df = selector.select(region="EUR")

# 获取筛选后 Alpha 的日收益矩阵
returns = selector.get_selected_returns(df)
print(returns.shape)  # (date_count, alpha_count)

# 用于 PnL correlation 分析或 allocator 的 greedy_sharpe/risk_parity 方法
```

---

## 7. 进一步精简（可选）

```python
df = selector.select(region="EUR")

# 基于 PnL correlation 的最大独立集合（贪心算法）
df_subset = selector.get_low_correlation_subset(df, threshold=0.7, max_size=25)
print(f"低相关子集: {len(df_subset)} 个")
```

---

## 8. 完整示例：批量筛选并导出结果

```python
from datetime import datetime
import pandas as pd

REGIONS = ["USA", "EUR", "ASI", "IND"]
selector = OsmosisAlphaSelectorV3()

results = {}
for region in REGIONS:
    print(f"\n{'='*40} {region} {'='*40}")
    df = selector.select(region=region, start_date=datetime(2025, 4, 19), fetch_yearly_stats=True)
    
    if len(df) < 10:
        print(f"⚠️ 仅 {len(df)} 个 Alpha，不足门槛")
        continue
    
    print(f"✅ 选中 {len(df)} 个 Alpha")
    print(f"   REGULAR: {(df['type'] != 'SUPER').sum()}, SUPER: {(df['type'] == 'SUPER').sum()}")
    print(f"   quality_score: {df['quality_score'].min():.3f} ~ {df['quality_score'].max():.3f}")
    print(f"   decay: {dict(df['decay_label'].value_counts())}")
    print(f"   dataset_tags: {df['dataset_tags'].explode().unique().tolist()}")
    
    results[region] = df

# 查看 USA 的 Top 10
if "USA" in results:
    print("\nUSA Top 10:")
    print(results["USA"].nlargest(10, 'quality_score')[['id', 'type', 'sharpe', 'fitness', 'quality_score', 'dataset_tags']])
```

---

## 9. 注意事项

| 注意点 | 说明 |
|--------|------|
| **API 速率限制** | 2000 次/小时，yearly-stats 批量获取在限制内 |
| **首次跑批较慢** | 需要获取 yearly-stats（约 20-30 个 API 调用/region） |
| **后续跑批很快** | 候选缓存 60 分钟，yearly-stats 缓存 24 小时 |
| **ASI/IND 门槛紧张** | 可能只有 10-11 个 Alpha，建议放宽筛选条件或接受 |
| **quality_score 为 0.5** | 表示该 Alpha 无 yearly_stats（未获取或获取失败） |
| **decay_label = unknown** | 表示 investability 数据缺失，不影响分配 |
