# wqbkit

WorldQuant Brain (WQB) Alpha Research Automation Toolkit

**Version: 0.4.3**

**[English](#overview) | [中文](#概述)**

---

## Overview

`wqbkit` is a Python toolkit that automates alpha research workflows on the [WorldQuant Brain](https://www.worldquantbrain.com) (WQB) platform. It covers the entire alpha lifecycle — from simulation and scoring to correlation analysis, genetic expression evolution, and Osmosis competition allocation.

### Key Features

| Module | Description | DB Required |
|--------|-------------|-------------|
| `AlphaBaseCore` | WQB authentication, HTTP request wrapper with 429 retry | No |
| `AlphaDbCore` | `AlphaBaseCore` + PostgreSQL ORM + PnL cache + token extraction | Yes |
| `AlphaCalcCorr` | Multi-metric correlation engine (self / ppac / prod / self_web) | No* |
| `AlphaGenerator` | Expression factory (0/1/2/3-order) with operator/field validation | No |
| `AlphaMachine` | Genetic iteration pipeline — pruning, deduplication, next-generation | Yes |
| `AlphaSimulator` | Multi-threaded batch simulation scheduler with queue-based results | Yes |
| `SuperAlphaSimulator` | Dedicated simulator for SUPER-type alphas | Yes |
| `AlphaDyeing` | SUPER alpha construction and combo template management | No |
| `Osmosis V3` | `OsmosisAlphaSelectorV3` + `OsmosisAllocatorV3` + `OsmosisClearV3` + `OsmosisRunnerV3` | Partial |
| `sc_send` | Bark (iOS) push notification for long-running jobs | No |

> *`AlphaCalcCorr` works without DB, but PnL caching is disabled. All PnL data is fetched from WQB API directly, with local pickle caching for `alpha_returns` to avoid repeated API calls.

### DB_ENABLE Behavior

Set `DB_ENABLE=false` in `.env` to disable all database-dependent features:

| `DB_ENABLE=true` | `DB_ENABLE=false` |
|------------------|-------------------|
| `AlphaDbCore`, `AlphaCalcCorr`, `AlphaMachine`, `AlphaSimulator` available | Only `AlphaBaseCore`, `AlphaCalcCorr`, `AlphaGenerator`, `AlphaDyeing`, `OsmosisAllocatorV3`, `OsmosisClearV3` available |
| PnL cached in PostgreSQL | PnL fetched from API every time (with local pickle cache for `alpha_returns`) |
| Full functionality | Sufficient for correlation analysis and expression generation |

---

## Installation

```bash
pip install wqbkit
```

### Prerequisites

- Python >= 3.10
- `wqb` SDK — WorldQuant Brain official Python client

```bash
pip install wqb
```

### Optional: PostgreSQL

Only required if `DB_ENABLE=true` (default):

```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt-get install postgresql

# Or use Docker
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=yourpassword postgres:15
```

Tables are **auto-created** on first `AlphaDBManager` initialization — no manual schema setup needed.

---

## Quick Start

### Minimal Setup (No Database)

Create `.env` in your project root:

```env
DB_ENABLE=false
WQB_USERNAME=your_wqb_username
WQB_PASSWORD=your_wqb_password
```

```python
from wqbkit import AlphaCalcCorr, AlphaGenerator

# Correlation analysis (no DB needed)
calcor = AlphaCalcCorr()
results = calcor.calculate(
    alpha=["alpha_id_1", "alpha_id_2"],
    calc_type="self",      # or "ppac", "prod", "self_web"
    skip_cache=False
)
print(results)

# Expression generation (no DB needed)
gen = AlphaGenerator()
exprs = gen.second_order_factory("ts_mean(close, 20)", region="USA", atom=True)
```

### Full Setup (With Database)

```env
DB_ENABLE=true
DB_HOST=localhost
DB_PORT=5432
DB_NAME=WorldQuant
DB_USER=postgres
DB_PASSWORD=your_db_password
WQB_USERNAME=your_wqb_username
WQB_PASSWORD=your_wqb_password
```

```python
from wqbkit import AlphaDbCore, AlphaSimulator, AlphaMachine, OsmosisRunnerV3

# Core with DB caching
core = AlphaDbCore()

# Simulation with DB queue
sim = AlphaSimulator()
sim.simulator()

# Genetic evolution
machine = AlphaMachine()
machine.machine(task_id=123)

# Osmosis full pipeline
runner = OsmosisRunnerV3()
runner.run(update=True, dry_run=False)
```

---

## Configuration

Create a `.env` file in your **project root directory**.

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `WQB_USERNAME` | *(none)* | WQB login username |
| `WQB_PASSWORD` | *(none)* | WQB login password |

### Database

| Variable | Default | Required if `DB_ENABLE=true` |
|----------|---------|------------------------------|
| `DB_ENABLE` | `true` | Set `false` to disable all DB features |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `WorldQuant` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | *(empty)* | Database password |

### Project Root (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `WQB_PROJECT_ROOT` | Auto-detected | Override project root for `data/` and `logs/` paths. Useful when running scripts from a subdirectory. |

Auto-detection logic:
- **Editable install** (`pip install -e .`): uses the source code directory
- **Regular install** (`pip install wqbkit`): uses `Path.cwd()` (current working directory)

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_RETRIES` | `5` | Max retry attempts for WQB API calls |
| `RETRY_DELAY_BASE` | `2` | Base delay (seconds) for exponential backoff on 429 |
| `BARK_KEY` | *(empty)* | Bark device key for iOS push notifications |
| `BARK_BASE_URL` | `https://api.day.app` | Bark server URL |

`wqbkit` automatically loads `.env` on import via `python-dotenv`.

---

## Runtime Paths

Logs and data are written to your **project root directory**, never inside the package:

| Type | Default Path | Notes |
|------|-------------|-------|
| Logs | `{project_root}/logs/` | Rotated daily, 30-day retention |
| Correlation cache | `{project_root}/data/correlation/` | `alpha_ids`, `alpha_returns.pkl` |
| Osmosis data | `{project_root}/data/Osmosis/` | Cache, blacklist, maxtrade map |

---

## API Reference

### Core Classes

```python
from wqbkit import (
    AlphaBaseCore,          # WQB session + HTTP + retry (no DB)
    AlphaDbCore,            # AlphaBaseCore + DB + PnL cache
    AlphaCalcCorr,          # Correlation analysis engine
    AlphaGenerator,         # Expression factory
    AlphaSimulator,         # Multi-threaded simulation scheduler
    AlphaMachine,           # Genetic iteration pipeline
    AlphaDyeing,            # SUPER alpha builder
    SuperAlphaSimulator,    # SUPER alpha simulator
    OsmosisAlphaSelectorV3, # Osmosis V3 selector
    OsmosisAllocatorV3,     # Osmosis V3 allocator
    OsmosisClearV3,         # Osmosis V3 score clearer
    OsmosisRunnerV3,        # Osmosis V3 end-to-end runner
    sc_send,                # Push notification helper
    schemas,                # Data models: FactorData, TaskData, SimulationData
)
```

### Conditional Availability (DB_ENABLE=false)

When `DB_ENABLE=false`:

```python
from wqbkit import (
    AlphaBaseCore,       # ✅
    AlphaCalcCorr,       # ✅ (caching disabled, local pickle fallback)
    AlphaGenerator,      # ✅
    AlphaDyeing,         # ✅
    OsmosisAllocatorV3,  # ✅
    OsmosisClearV3,      # ✅
    sc_send,             # ✅
)

from wqbkit import AlphaDbCore       # ✅ works, but dbmanager=None
from wqbkit import AlphaSimulator    # ❌ RuntimeError on init
from wqbkit import AlphaMachine      # ❌ RuntimeError on init
```

### Correlation Analysis

```python
from wqbkit import AlphaCalcCorr

calcor = AlphaCalcCorr()

# Batch compute correlations with progress bar
results = calcor.calculate(
    alpha=["alpha_id_1", "alpha_id_2", "alpha_id_3"],
    calc_type="self",      # "self" | "ppac" | "prod" | "self_web"
    skip_cache=False,      # use DB cache if available
    show_detail=False      # print correlation matrix
)
# Returns: {"alpha_id_1": 0.72, "alpha_id_2": 0.85, ...}
```

`alpha_returns` is incrementally cached to `{project_root}/data/correlation/alpha_returns.pkl`.
- First run: fetches all PnL via API (~1-2s per 50 alphas)
- Subsequent runs: only fetches PnL for **newly submitted alphas**

### Osmosis V3

```python
from wqbkit import OsmosisAlphaSelectorV3, OsmosisAllocatorV3, OsmosisRunnerV3

# 1. Select alphas
selector = OsmosisAlphaSelectorV3()
df = selector.select(region="USA")

# 2. Allocate scores
allocator = OsmosisAllocatorV3()
df = allocator.allocate(df, method="mixed")
allocator.update_osmosis_points(df, dry_run=False)

# 3. Or run the full pipeline
runner = OsmosisRunnerV3()
runner.run(update=True, dry_run=False)
```

### Alpha Simulation

```python
from wqbkit import AlphaSimulator

sim = AlphaSimulator()

# Run the main simulation loop (reads tasks from DB queue)
sim.simulator()
```

---

## Project Structure

```
wqbkit/
├── app/
│   ├── config.py          # PROJECT_ROOT, DATA_DIR, LOGS_DIR, Config class
│   ├── core/
│   │   ├── alpha_base_core.py    # WQB auth, HTTP, retry
│   │   ├── alpha_db_core.py      # PnL cache, token extraction, tag generator
│   │   ├── decorators.py         # @retry_decorator
│   │   ├── logger.py             # Unified logging to LOGS_DIR
│   │   └── wqb_urls.py           # WQB API endpoint constants
│   ├── database/
│   │   ├── db_models.py          # SQLAlchemy ORM models (auto-created on init)
│   │   ├── alpha_db_manager.py   # CRUD operations
│   │   └── schemas.py            # Dataclasses: FactorData, SimulationData, TaskData
│   └── utils/
│       └── alpha_utils.py        # extract_tokens helper
└── modules/
    ├── regular_alpha/
    │   ├── alpha_simulator.py    # Multi-threaded simulation scheduler
    │   ├── alpha_machine.py      # Genetic iteration pipeline
    │   └── alpha_generator.py    # Expression factory
    ├── super_alpha/
    │   ├── super_alpha_simulator.py
    │   ├── super_alpha_creator.py
    │   └── alpha_dyeing.py
    ├── correlation/
    │   └── alpha_calc_corr.py    # Correlation engine with incremental caching
    ├── message/
    │   └── alpha_message_sender.py
    └── competitions/
        └── Osmosis/
            ├── osmosis_selector_v3.py
            ├── osmosis_allocator_v3.py
            ├── osmosis_clear_v3.py
            └── osmosis_runner_v3.py
```

---

## FAQ

**Q: Do I need PostgreSQL?**

A: No — set `DB_ENABLE=false` and use `AlphaCalcCorr`, `AlphaGenerator`, `AlphaDyeing`, `OsmosisAllocatorV3` without any database.

**Q: Tables are not created?**

A: Tables are auto-created when any DB-dependent class (e.g., `AlphaSimulator`) is first instantiated. No manual `CREATE TABLE` needed.

**Q: Where are logs and cache stored?**

A: In your **project root directory** under `logs/` and `data/`, never inside the `site-packages/wqbkit/` folder. Use `WQB_PROJECT_ROOT` to override the root path.

**Q: Can I use wqbkit in a Jupyter Notebook?**

A: Yes. Create `.env` in the notebook's working directory, or set `WQB_PROJECT_ROOT` to your project folder.

**Q: How do I update to the latest version?**

A: `pip install -U wqbkit`

---

## License

MIT

---

## 概述

`wqbkit` 是一个用于自动化 [WorldQuant Brain](https://www.worldquantbrain.com) 平台 Alpha 研究的 Python 工具包，覆盖 Alpha 全生命周期：模拟、评分、去相关、遗传迭代进化、Osmosis 竞赛分配。

### 核心功能

| 模块 | 说明 | 是否需要数据库 |
|------|------|---------------|
| `AlphaBaseCore` | WQB 认证、HTTP 封装、429 重试 | 否 |
| `AlphaDbCore` | `AlphaBaseCore` + PostgreSQL ORM + PnL 缓存 + token 提取 | 是 |
| `AlphaCalcCorr` | 多指标相关性引擎（self / ppac / prod / self_web） | 否* |
| `AlphaGenerator` | 表达式工厂（0/1/2/3 阶），带算子/字段校验 | 否 |
| `AlphaMachine` | 遗传迭代管线：剪枝、去重、下一代 | 是 |
| `AlphaSimulator` | 多线程批量模拟调度器，队列式结果处理 | 是 |
| `SuperAlphaSimulator` | SUPER 类型 Alpha 专用模拟器 | 是 |
| `AlphaDyeing` | SUPER Alpha 构造与 combo 模板管理 | 否 |
| `Osmosis V3` | 选股器 + 分配器 + 清仓器 + 运行器 | 部分 |
| `sc_send` | Bark (iOS) 推送通知，用于长时任务提醒 | 否 |

> *`AlphaCalcCorr` 无需数据库即可运行，但 PnL 缓存失效。所有 PnL 数据直接从 WQB API 获取，`alpha_returns` 会通过本地 pickle 增量缓存，避免重复调 API。

### DB_ENABLE 行为

在 `.env` 中设置 `DB_ENABLE=false` 可禁用所有数据库相关功能：

| `DB_ENABLE=true` | `DB_ENABLE=false` |
|------------------|-------------------|
| `AlphaDbCore`、`AlphaCalcCorr`、`AlphaMachine`、`AlphaSimulator` 可用 | 仅 `AlphaBaseCore`、`AlphaCalcCorr`、`AlphaGenerator`、`AlphaDyeing`、`OsmosisAllocatorV3`、`OsmosisClearV3` 可用 |
| PnL 缓存在 PostgreSQL 中 | PnL 每次从 API 获取（`alpha_returns` 有本地 pickle 增量缓存） |
| 完整功能 | 足以进行相关性分析和表达式生成 |

---

## 安装

```bash
pip install wqbkit
```

### 前置依赖

- Python >= 3.10
- `wqb` SDK — WorldQuant Brain 官方 Python 客户端

```bash
pip install wqb
```

### 可选：PostgreSQL

仅在 `DB_ENABLE=true`（默认）时需要：

```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt-get install postgresql

# 或使用 Docker
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=yourpassword postgres:15
```

首次实例化 `AlphaDBManager` 时**自动建表**，无需手动执行 `CREATE TABLE`。

---

## 快速开始

### 最小配置（无数据库）

在项目根目录创建 `.env`：

```env
DB_ENABLE=false
WQB_USERNAME=your_wqb_username
WQB_PASSWORD=your_wqb_password
```

```python
from wqbkit import AlphaCalcCorr, AlphaGenerator

# 相关性分析（无需数据库）
calcor = AlphaCalcCorr()
results = calcor.calculate(
    alpha=["alpha_id_1", "alpha_id_2"],
    calc_type="self",      # 或 "ppac", "prod", "self_web"
    skip_cache=False
)
print(results)

# 表达式生成（无需数据库）
gen = AlphaGenerator()
exprs = gen.second_order_factory("ts_mean(close, 20)", region="USA", atom=True)
```

### 完整配置（启用数据库）

```env
DB_ENABLE=true
DB_HOST=localhost
DB_PORT=5432
DB_NAME=WorldQuant
DB_USER=postgres
DB_PASSWORD=your_db_password
WQB_USERNAME=your_wqb_username
WQB_PASSWORD=your_wqb_password
```

```python
from wqbkit import AlphaDbCore, AlphaSimulator, AlphaMachine, OsmosisRunnerV3

# 带数据库缓存的核心
core = AlphaDbCore()

# 模拟（带数据库队列）
sim = AlphaSimulator()
sim.simulator()

# 遗传进化
machine = AlphaMachine()
machine.machine(task_id=123)

# Osmosis 全流程
runner = OsmosisRunnerV3()
runner.run(update=True, dry_run=False)
```

---

## 配置说明

在项目根目录创建 `.env` 文件。

### 必填

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WQB_USERNAME` | *(无)* | WQB 登录用户名 |
| `WQB_PASSWORD` | *(无)* | WQB 登录密码 |

### 数据库

| 变量 | 默认值 | `DB_ENABLE=true` 时是否必填 |
|------|--------|----------------------------|
| `DB_ENABLE` | `true` | 设为 `false` 禁用所有数据库功能 |
| `DB_HOST` | `localhost` | PostgreSQL 主机 |
| `DB_PORT` | `5432` | PostgreSQL 端口 |
| `DB_NAME` | `WorldQuant` | 数据库名 |
| `DB_USER` | `postgres` | 数据库用户 |
| `DB_PASSWORD` | *(空)* | 数据库密码 |

### 项目根目录（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WQB_PROJECT_ROOT` | 自动检测 | 覆盖 `data/` 和 `logs/` 的根路径。在子目录运行脚本时有用。 |

自动检测逻辑：
- **Editable install** (`pip install -e .`): 使用源码目录
- **常规安装** (`pip install wqbkit`): 使用 `Path.cwd()`（当前工作目录）

### 可选

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_RETRIES` | `5` | WQB API 调用最大重试次数 |
| `RETRY_DELAY_BASE` | `2` | 429 限流指数退避基数（秒） |
| `BARK_KEY` | *(空)* | Bark 设备密钥，用于 iOS 推送通知 |
| `BARK_BASE_URL` | `https://api.day.app` | Bark 服务器地址 |

`wqbkit` 通过 `python-dotenv` 在导入时自动加载 `.env`。

---

## 运行时路径

日志和数据写入**项目根目录**，绝不会写入包内部：

| 类型 | 默认路径 | 说明 |
|------|---------|------|
| 日志 | `{project_root}/logs/` | 按天轮转，保留 30 天 |
| 相关性缓存 | `{project_root}/data/correlation/` | `alpha_ids`、`alpha_returns.pkl` |
| Osmosis 数据 | `{project_root}/data/Osmosis/` | 缓存、黑名单、maxtrade 映射 |

---

## API 参考

### 核心类

```python
from wqbkit import (
    AlphaBaseCore,          # WQB 会话 + HTTP + 重试（无数据库）
    AlphaDbCore,            # AlphaBaseCore + 数据库 + PnL 缓存
    AlphaCalcCorr,          # 相关性分析引擎
    AlphaGenerator,         # 表达式工厂
    AlphaSimulator,         # 多线程模拟调度器
    AlphaMachine,           # 遗传迭代管线
    AlphaDyeing,            # SUPER alpha 构建器
    SuperAlphaSimulator,    # SUPER alpha 模拟器
    OsmosisAlphaSelectorV3, # Osmosis V3 选股器
    OsmosisAllocatorV3,     # Osmosis V3 分配器
    OsmosisClearV3,         # Osmosis V3 清仓器
    OsmosisRunnerV3,        # Osmosis V3 全流程运行器
    sc_send,                # 推送通知辅助函数
    schemas,                # 数据模型：FactorData、TaskData、SimulationData
)
```

### 条件可用性（DB_ENABLE=false）

当 `DB_ENABLE=false` 时：

```python
from wqbkit import (
    AlphaBaseCore,       # ✅
    AlphaCalcCorr,       # ✅（缓存失效，使用本地 pickle 回退）
    AlphaGenerator,      # ✅
    AlphaDyeing,         # ✅
    OsmosisAllocatorV3,  # ✅
    OsmosisClearV3,      # ✅
    sc_send,             # ✅
)

from wqbkit import AlphaDbCore       # ✅ 可用，但 dbmanager=None
from wqbkit import AlphaSimulator    # ❌ 初始化时报 RuntimeError
from wqbkit import AlphaMachine      # ❌ 初始化时报 RuntimeError
```

### 相关性分析

```python
from wqbkit import AlphaCalcCorr

calcor = AlphaCalcCorr()

# 批量计算相关性，带进度条
results = calcor.calculate(
    alpha=["alpha_id_1", "alpha_id_2", "alpha_id_3"],
    calc_type="self",      # "self" | "ppac" | "prod" | "self_web"
    skip_cache=False,      # 如可用则使用数据库缓存
    show_detail=False      # 打印相关性矩阵
)
# 返回：{"alpha_id_1": 0.72, "alpha_id_2": 0.85, ...}
```

`alpha_returns` 以增量方式缓存到 `{project_root}/data/correlation/alpha_returns.pkl`。
- 首次运行：通过 API 获取所有 PnL（每 50 个 alpha 约 1-2 秒）
- 后续运行：仅获取**新提交 alpha** 的 PnL

### Osmosis V3

```python
from wqbkit import OsmosisAlphaSelectorV3, OsmosisAllocatorV3, OsmosisRunnerV3

# 1. 选股
selector = OsmosisAlphaSelectorV3()
df = selector.select(region="USA")

# 2. 分配分数
allocator = OsmosisAllocatorV3()
df = allocator.allocate(df, method="mixed")
allocator.update_osmosis_points(df, dry_run=False)

# 3. 或运行全流程
runner = OsmosisRunnerV3()
runner.run(update=True, dry_run=False)
```

### Alpha 模拟

```python
from wqbkit import AlphaSimulator

sim = AlphaSimulator()

# 运行主模拟循环（从数据库队列读取任务）
sim.simulator()
```

---

## 常见问题

**Q: 我需要 PostgreSQL 吗？**

A: 不需要 — 设置 `DB_ENABLE=false`，即可在无数据库环境下使用 `AlphaCalcCorr`、`AlphaGenerator`、`AlphaDyeing`、`OsmosisAllocatorV3`。

**Q: 表没有自动创建？**

A: 首次实例化任何数据库依赖类（如 `AlphaSimulator`）时自动建表。无需手动执行 `CREATE TABLE`。

**Q: 日志和缓存存在哪里？**

A: 在**项目根目录**的 `logs/` 和 `data/` 下，绝不会写入 `site-packages/wqbkit/` 文件夹。通过 `WQB_PROJECT_ROOT` 覆盖根路径。

**Q: 可以在 Jupyter Notebook 中使用吗？**

A: 可以。在 notebook 工作目录创建 `.env`，或设置 `WQB_PROJECT_ROOT` 指向你的项目文件夹。

**Q: 如何更新到最新版本？**

A: `pip install -U wqbkit`

---

## 许可证

MIT
