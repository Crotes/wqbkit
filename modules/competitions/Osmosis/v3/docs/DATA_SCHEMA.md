# V3 数据格式分析

> 基于 `alpha_detail_os.json`、`alpha_detail_no_os.json`、`year_status.json` 三个样例的结构解析。

---

## 1. filter_alphas 返回的 Alpha 详情结构

### 1.1 顶层字段

| 字段 | 类型 | 说明 | V3 用途 |
|------|------|------|---------|
| `id` | string | Alpha ID | 唯一标识 |
| `type` | string | "REGULAR" / "SUPER" / etc | Alpha 类型分类 |
| `settings` | object | Alpha 配置参数 | 提取 delay/neutralization/maxTrade |
| `regular.code` | string | 表达式 | 提取 operator/field |
| `regular.operatorCount` | int | 算子数量 | 参考 |
| `dateCreated` | string (ISO) | 创建时间 | 时间过滤 |
| `dateSubmitted` | string (ISO) | 提交时间 | 参考 |
| `tags` | string[] | 标签，如 ["Fundamental"], ["Imbalance"] | **推断数据集类别** |
| `classifications` | object[] | 分类标签 | 识别 FastD1 / Power Pool 等 |
| `stage` | string | "OS" / "IS" / etc | 当前阶段 |
| `status` | string | "ACTIVE" / etc | 状态过滤 |
| `is` | object | In-Sample 指标 | 核心质量数据 |
| `os` | object | Out-of-Sample 指标（可能为空/null） | OS/IS 先验 |
| `osmosisPoints` | int/null | 当前分配的点数 | 参考 |

### 1.2 settings 对象

```json
{
    "instrumentType": "EQUITY",
    "region": "IND",
    "universe": "TOP500",
    "delay": 1,
    "decay": 4,
    "neutralization": "SLOW",      // ← V3 新增提取：中性化方式
    "truncation": 0.02,
    "pasteurization": "ON",
    "unitHandling": "VERIFY",
    "nanHandling": "OFF",
    "maxTrade": "OFF",             // ← "OFF" 或 "ON"，字符串！不是 bool
    "maxPosition": "OFF",
    "language": "FASTEXPR",
    "visualization": false,
    "startDate": "2013-01-20",
    "endDate": "2023-01-20"
}
```

**关键发现**：
- ❌ **没有 `dataset` 字段**：settings 中不存在 dataset 字段
- ❌ **没有 `category` 字段**：settings 中不存在 category 字段
- ✅ **`neutralization`**：存在，值为 "SLOW" / "FAST" / "NONE" / "INDUSTRY" / "SUBINDUSTRY" 等
- ✅ **`maxTrade`**：值为字符串 "OFF" 或 "ON"（不是布尔值）
- ✅ **`delay`**：整数，scope 的关键维度

**dataset 推断策略**：
- 主来源：`tags` 数组，如 `["Fundamental"]`、`["Imbalance"]`
- 次来源：从 expression 中的 field 名称推断（如 `fnd44_` → fundamental）
- fallback：从 `pyramids` 或 `classifications` 推断

### 1.3 `is` 对象（In-Sample 指标）

```json
{
    "pnl": 4203642,
    "bookSize": 20000000,
    "longCount": 194,
    "shortCount": 308,
    "turnover": 0.2983,
    "returns": 0.0798,
    "drawdown": 0.0622,
    "margin": 0.000535,
    "sharpe": 1.6,
    "fitness": 0.83,
    "startDate": "2013-01-20",
    "investabilityConstrained": {   // ← V3 新增提取
        "turnover": 0.1321,
        "returns": 0.047,
        "drawdown": 0.0809,
        "margin": 0.000711,
        "fitness": 0.54,
        "sharpe": 0.9
    },
    "selfCorrelation": 0,           // ← V2 已提取，V3 使用
    "prodCorrelation": 0.2361       // ← V2 已提取
}
```

**关键发现**：
- ✅ `investabilityConstrained` **始终存在**（即使 OS 数据缺失的 Alpha 也有）
- ✅ `selfCorrelation` 在 `is` 下，值域 [0, 1]
- ✅ `prodCorrelation` 在 `is` 下，值域 [0, 1]
- ❌ **没有 `yearlyStats`**：需要通过额外 API 获取

### 1.4 `os` 对象（Out-of-Sample 指标）

**情况 A：有完整 OS 数据**（如 `alpha_detail_os.json`）

```json
{
    "startDate": "2023-01-21",
    "turnover": 0.286,
    "returns": 0.0084,
    "drawdown": 0.0248,
    "margin": 0.000059,
    "fitness": 0.03,
    "preCloseSharpe": null,
    "sharpe": 0.2,
    "sharpe60": -1.23,
    "sharpe125": 0.35,
    "sharpe250": null,
    "sharpe500": null,
    "osISSharpeRatio": 0.12,        // ← OS/IS Sharpe Ratio！
    "preCloseSharpeRatio": null
}
```

**情况 B：OS 数据为空**（如 `alpha_detail_no_os.json`）

```json
{
    "startDate": "2024-01-01",
    "osISSharpeRatio": null,        // ← null！
    "preCloseSharpeRatio": null,
    "checks": [...]                 // 只有 checks，无实际指标
}
```

**关键发现**：
- `os` 对象**始终存在**，但**可能没有实际数据**
- 判断是否有 OS 数据的条件：`os.sharpe is not None`
- `osISSharpeRatio` 是现成的 OS/IS ratio，无需手动计算
- 当 OS 数据为空时，使用 `investabilityConstrained.sharpe / is.sharpe` 作为代理

### 1.5 V3 提取字段映射（修正版）

```python
def _parse_alpha_item_v3(item):
    is_data = item.get("is", {})
    os_data = item.get("os", {}) or {}
    settings = item.get("settings", {})
    regular = item.get("regular", {})
    
    # --- 基础指标（V2 已有）---
    base = {
        "id": item["id"],
        "fitness": is_data.get("fitness", 0.0),
        "sharpe": is_data.get("sharpe", 0.0),
        "returns": is_data.get("returns", 0.0),
        "drawdown": is_data.get("drawdown", 0.0),
        "margin": is_data.get("margin", 0.0),
        "turnover": is_data.get("turnover", 0.0),
        "longCount": is_data.get("longCount", 0),
        "shortCount": is_data.get("shortCount", 0),
        "expression": regular.get("code", ""),
        "neutralization": settings.get("neutralization", "unknown"),
        "decay": settings.get("decay", -1),
        "dateCreated": item.get("dateCreated"),
        "dateSubmitted": item.get("dateSubmitted"),
        "status": item.get("status"),
        "type": item.get("type", "REGULAR"),
        "prodCorrelation": is_data.get("prodCorrelation"),
        "selfCorrelation": is_data.get("selfCorrelation"),
        "maxTrade": settings.get("maxTrade", "OFF"),
    }
    
    # --- V3 新增字段 ---
    inv = is_data.get("investabilityConstrained", {})
    base.update({
        # Investability 约束后指标
        "inv_sharpe": inv.get("sharpe"),
        "inv_fitness": inv.get("fitness"),
        "inv_returns": inv.get("returns"),
        "inv_drawdown": inv.get("drawdown"),
        "inv_turnover": inv.get("turnover"),
        "inv_margin": inv.get("margin"),
        
        # OS 指标（可能为 None）
        "os_sharpe": os_data.get("sharpe"),
        "os_fitness": os_data.get("fitness"),
        "os_returns": os_data.get("returns"),
        "os_drawdown": os_data.get("drawdown"),
        "os_turnover": os_data.get("turnover"),
        "os_margin": os_data.get("margin"),
        "os_is_ratio": os_data.get("osISSharpeRatio"),
        
        # Dataset 推断（从 tags）
        "dataset_tags": item.get("tags", ["unknown"]) if item.get("tags") else ["unknown"],
    })
    
    return base
```

---

## 2. yearly-stats API 数据结构

### 2.1 API 端点

```
GET https://api.worldquantbrain.com/alphas/{alpha_id}/recordsets/yearly-stats
```

### 2.2 返回结构

```json
{
    "schema": {
        "name": "yearly-stats",
        "title": "Yearly Stats",
        "properties": [
            {"name": "year", "type": "year"},
            {"name": "pnl", "type": "amount"},
            {"name": "bookSize", "type": "amount"},
            {"name": "longCount", "type": "integer"},
            {"name": "shortCount", "type": "integer"},
            {"name": "turnover", "type": "percent"},
            {"name": "sharpe", "type": "decimal"},
            {"name": "returns", "type": "percent"},
            {"name": "drawdown", "type": "percent"},
            {"name": "margin", "type": "permyriad"},
            {"name": "fitness", "type": "decimal"},
            {"name": "stage", "type": "string"}
        ]
    },
    "records": [
        ["2014", 1474620, 20000000, 1533, 1083, 0.0839, 4.28, 0.1418, 0.0096, 0.003381, 4.56, "IS"],
        ["2015", 1054399, 20000000, 1596, 1127, 0.0916, 2.37, 0.1014, 0.0287, 0.002214, 2.13, "IS"],
        ...
    ]
}
```

### 2.3 关键特征

- `records` 是**二维数组**，不是对象数组
- 列顺序由 `schema.properties` 定义
- `stage` 列区分 "IS" / "OS" 年份
- 样例中有 10 年数据（2014-2023），全部 stage="IS"
- 每年包含完整的 `sharpe` / `returns` / `drawdown` / `fitness` / `turnover` / `margin`

### 2.4 解析代码

```python
def parse_yearly_stats(data):
    """
    输入: yearly-stats API 返回的 JSON
    输出: list[dict]，每项是一年的统计
    """
    properties = [p["name"] for p in data["schema"]["properties"]]
    records = []
    for row in data["records"]:
        record = dict(zip(properties, row))
        # 类型转换
        record["year"] = int(record["year"])
        record["sharpe"] = float(record["sharpe"]) if record["sharpe"] is not None else None
        record["returns"] = float(record["returns"]) if record["returns"] is not None else None
        record["drawdown"] = float(record["drawdown"]) if record["drawdown"] is not None else None
        record["fitness"] = float(record["fitness"]) if record["fitness"] is not None else None
        record["turnover"] = float(record["turnover"]) if record["turnover"] is not None else None
        record["margin"] = float(record["margin"]) if record["margin"] is not None else None
        records.append(record)
    return records
```

### 2.5 V3 中的使用方式

 yearly-stats **不在 filter_alphas 结果中**，需要：
1. `fetch_candidates()` 获取候选列表后
2. 对筛选后的候选 Alpha（而非全部），调用 yearly-stats API
3. 缓存结果（TTL 可设较长，如 24 小时，因为历史数据不会变）

**注意**：对大量 Alpha 逐个调用 yearly-stats API 会有性能问题。建议：
- 只在粗筛后（Layer 1 之后）对保留的 Alpha 获取
- 使用并发请求（ThreadPool）
- 缓存到本地（`data/yearly_stats_cache/{alpha_id}.json`）

---

## 3. Investability 衰减分析

### 3.1 样例对比

| Alpha | IS Sharpe | Inv Sharpe | 衰减率 | V3 处理 |
|-------|-----------|------------|--------|---------|
| `88gAZ3zv` (有 OS) | 1.6 | 0.9 | (1.6-0.9)/1.6 = **43.8%** | 标记 `moderate_decay` |
| `2ragnz35` (无 OS) | 1.96 | 1.86 | (1.96-1.86)/1.96 = **5.1%** | 正常 |

### 3.2 文档规则映射

文档建议："Sharpe ratio declines by approximately 60% or more after investability constraints"

```python
def classify_investability_decay(is_sharpe, inv_sharpe):
    if is_sharpe <= 0 or inv_sharpe is None:
        return "unknown", 0.5
    
    decay = (is_sharpe - inv_sharpe) / is_sharpe
    
    if decay >= 0.60:
        return "severe_decay", 0.2   # 大幅降权
    elif decay >= 0.40:
        return "moderate_decay", 0.6 # 中度降权
    elif decay >= 0.20:
        return "mild_decay", 0.85    # 轻度降权
    else:
        return "stable", 1.0         # 正常
```

---

## 4. Osmosis 平台状态数据（osmosis.json）

### 4.1 数据来源

通过 WQB 平台页面或 API 获取当前 consultant 的 Osmosis 分配概览。

### 4.2 结构

```json
[
    {"region": "USA", "delay": 1, "pointsAllocated": 100000, "alphas": 37},
    {"region": "USA", "delay": 0, "pointsAllocated": 0, "alphas": 0},
    {"region": "GLB", "delay": 1, "pointsAllocated": 0, "alphas": 0},
    {"region": "EUR", "delay": 1, "pointsAllocated": 100000, "alphas": 19},
    ...
]
```

### 4.3 关键发现

- **可用 regions**（11 个）：AMR, ASI, CHN, EUR, GLB, HKG, JPN, KOR, MEA, USA, IND
- **已分配 scopes**（4 个）：USA/D1, EUR/D1, ASI/D1, IND/D1
- **delay=0 全为 0**：用户当前未做 delay=0 的 Alpha
- **ASI 数量紧张**：仅 10 个 Alpha（正好门槛），质量筛选需更保守
- **GLB 未分配**：可能无合格 Alpha 或尚未配置

### 4.4 V3 中的使用

- **自动获取可用 scopes**：从平台拉取 `pointsAllocated > 0` 或 `alphas > 0` 的 scopes
- **监控门槛**：ASI/IND 接近 10 个门槛，分配前需特别关注
- **Region 列表不再硬编码**：从平台动态获取

---

## 5. 数据获取策略总结

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: filter_alphas API                                  │
│  ─────────────────────────                                  │
│  获取: id, is.*, os.*, settings.*, tags, classifications    │
│  包含: 基础指标 + investabilityConstrained + selfCorrelation │
│  成本: 1 次 API 调用（分页）                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 粗筛 (Layer 1: Hard Filters)                       │
│  ────────────────────────────────────                       │
│  过滤后保留 N 个候选（通常 20-50 个）                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: yearly-stats API（按需）                            │
│  ───────────────────────────────                            │
│  对 Layer 1 后的候选，逐个获取 yearly-stats                  │
│  成本: N 次 API 调用（可并发）                               │
│  缓存: 24h TTL（历史数据不变）                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 4: PnL returns 矩阵（按需）                            │
│  ───────────────────────────────                            │
│  对进一步筛选后的候选，获取 returns 时间序列                  │
│  用于: PnL correlation, drawdown overlap                     │
│  成本: 1 次 API 调用（get_alpha_results）                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 对 REQUIREMENTS.md 的修正

基于实际数据格式的发现，对需求文档做以下修正：

1. **`dataset` 字段**：settings 中不存在，改为从完整 `tags` 列表推断，字段名改为 `dataset_tags`（支持多标签）
2. **`category` 字段**：不存在，移除该维度，用 `dataset_tags` 替代
3. **`maxTrade`**：值为字符串 "OFF"/"ON"，不是 bool
4. **`yearly_stats`**：确认需要通过额外 API 获取，不在 filter_alphas 结果中
5. **`osISSharpeRatio`**：直接使用现成的 `os.osISSharpeRatio`，无需手动计算
6. **`investabilityConstrained`**：始终存在，可以直接用于衰减分析
