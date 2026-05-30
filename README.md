# wqbkit

WorldQuant Brain (WQB) Alpha Research Automation Toolkit

**[English](#overview) | [中文](#概述)**

---

## Overview

`wqbkit` is a Python toolkit that automates alpha research workflows on the [WorldQuant Brain](https://www.worldquantbrain.com) (WQB) platform. It covers the entire alpha lifecycle — from simulation and scoring to correlation analysis, genetic expression evolution, and Osmosis competition allocation.

### Key Features

| Module | Description |
|--------|-------------|
| `AlphaBaseCore` | WQB authentication, HTTP request wrapper with 429 retry |
| `AlphaDbCore` | `AlphaBaseCore` + PostgreSQL ORM + PnL cache + token extraction |
| `AlphaCalcCorr` | Multi-metric correlation engine (self / ppac / prod / self_web) |
| `AlphaGenerator` | Expression factory (0/1/2/3-order) with operator/field validation |
| `AlphaMachine` | Genetic iteration pipeline — pruning, deduplication, next-generation |
| `AlphaSimulator` | Multi-threaded batch simulation scheduler with queue-based results |
| `SuperAlphaSimulator` | Dedicated simulator for SUPER-type alphas |
| `AlphaDyeing` | SUPER alpha construction and combo template management |
| `Osmosis V3` | `OsmosisAlphaSelectorV3` + `OsmosisAllocatorV3` + `OsmosisClearV3` + `OsmosisRunnerV3` |
| `sc_send` | Bark (iOS) push notification for long-running jobs |

---

## Installation

```bash
pip install wqbkit
```

### Prerequisites

- Python >= 3.10
- PostgreSQL (optional, for local alpha metadata caching)
- `wqb` SDK — WorldQuant Brain official Python client

```bash
pip install wqb
```

---

## Quick Start

```python
from wqbkit import AlphaDbCore, AlphaCalcCorr, AlphaGenerator, OsmosisRunnerV3

# Initialize core (auto-loads .env if present)
core = AlphaDbCore()

# Correlation analysis
calcor = AlphaCalcCorr()
self_corr = calcor.calc_corr(alpha_id, calc_type='self')

# Generate expressions
generator = AlphaGenerator()
new_exprs = generator.second_order_factory(
    expression="ts_mean(close, 20)",
    region="USA",
    atom=True
)

# Osmosis V3 pipeline
runner = OsmosisRunnerV3()
runner.run(update=True, dry_run=False)
```

---

## Configuration

Create a `.env` file in your **project root directory** (the directory above `wqbkit/` in editable-install mode):

```env
# Database (optional)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=WorldQuant
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# WQB Credentials
WQB_USERNAME=your_wqb_username
WQB_PASSWORD=your_wqb_password

# Retry
MAX_RETRIES=5
RETRY_DELAY_BASE=2

# Bark Push (optional)
BARK_KEY=your_bark_device_key
```

`wqbkit` automatically loads `.env` on import via `python-dotenv`.

### Runtime Paths

Logs and temporary data are written to your **project root directory**, never inside the package:

| Type | Default Path | Configurable via |
|------|-------------|------------------|
| Logs | `{project_root}/logs/` | `config.LOGS_DIR` |
| Correlation cache | `{project_root}/data/correlation/` | `config.DATA_DIR / "correlation"` |
| Osmosis data | `{project_root}/data/Osmosis/` | `config.DATA_DIR / "Osmosis"` |

---

## API Reference

### Core Classes

```python
from wqbkit import (
    AlphaBaseCore,          # WQB session + HTTP + retry
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

### Correlation Analysis

```python
from wqbkit import AlphaCalcCorr

calcor = AlphaCalcCorr()

# Compute correlations
corr = calcor.calc_corr(alpha_id, calc_type='self')     # self-correlation
corr = calcor.calc_corr(alpha_id, calc_type='ppac')     # ppac correlation
corr = calcor.calc_corr(alpha_id, calc_type='prod')     # prod correlation
```

### Alpha Simulation

```python
from wqbkit import AlphaSimulator

sim = AlphaSimulator()

# Single alpha simulation
result = sim.simulate(expression="rank(close)", region="USA", universe="TOP3000")

# Batch simulation from database queue
sim.run_batch_simulation(task_id=123)
```

---

## Project Structure

```
wqbkit/
├── app/
│   ├── core/          # AlphaBaseCore, AlphaDbCore, decorators, logger, URLs
│   ├── database/      # SQLAlchemy models, AlphaDBManager, schemas
│   └── utils/         # Token extraction helpers
└── modules/
    ├── regular_alpha/ # AlphaSimulator, AlphaMachine, AlphaGenerator
    ├── super_alpha/   # SuperAlphaSimulator, AlphaDyeing, SuperAlphaCreator
    ├── correlation/   # AlphaCalcCorr
    ├── message/       # Bark push notifications
    └── competitions/
        └── Osmosis/   # Osmosis V3 toolkit
```

---

## License

MIT

---

## 概述

`wqbkit` 是一个用于自动化 [WorldQuant Brain](https://www.worldquantbrain.com) 平台 Alpha 研究的 Python 工具包，覆盖 Alpha 全生命周期：模拟、评分、去相关、遗传迭代进化、Osmosis 竞赛分配。

### 核心功能

| 模块 | 说明 |
|------|------|
| `AlphaBaseCore` | WQB 认证、HTTP 封装、429 重试 |
| `AlphaDbCore` | `AlphaBaseCore` + PostgreSQL ORM + PnL 缓存 + token 提取 |
| `AlphaCalcCorr` | 多指标相关性引擎（self / ppac / prod / self_web） |
| `AlphaGenerator` | 表达式工厂（0/1/2/3 阶），带算子/字段校验 |
| `AlphaMachine` | 遗传迭代管线：剪枝、去重、下一代 |
| `AlphaSimulator` | 多线程批量模拟调度器，队列式结果处理 |
| `SuperAlphaSimulator` | SUPER 类型 Alpha 专用模拟器 |
| `AlphaDyeing` | SUPER Alpha 构造与 combo 模板管理 |
| `Osmosis V3` | `OsmosisAlphaSelectorV3` + `OsmosisAllocatorV3` + `OsmosisClearV3` + `OsmosisRunnerV3` |
| `sc_send` | Bark (iOS) 推送通知，用于长时任务提醒 |

### 快速开始

```python
from wqbkit import AlphaDbCore, AlphaCalcCorr, AlphaGenerator, OsmosisRunnerV3

core = AlphaDbCore()
calcor = AlphaCalcCorr()
generator = AlphaGenerator()
runner = OsmosisRunnerV3()
runner.run(update=True, dry_run=False)
```

### 配置说明

在项目根目录创建 `.env`：

```env
WQB_USERNAME=your_username
WQB_PASSWORD=your_password
```

日志和运行时数据统一写入项目根目录的 `logs/` 和 `data/` 下，不会写入包内部。
