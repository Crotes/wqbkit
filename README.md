# wqbkit

WorldQuant Brain (WQB) Alpha Research Automation Toolkit

**[English](#overview) | [中文](#概述)**

---

## Overview

`wqbkit` is a Python toolkit that automates alpha research workflows on the [WorldQuant Brain](https://www.worldquantbrain.com) (WQB) platform. It covers the entire alpha lifecycle — from simulation and scoring to correlation analysis and genetic expression evolution.

### Key Features

| Module | Description |
|--------|-------------|
| `AlphaDbCore` | WQB authentication, HTTP request wrapper with exponential backoff retry |
| `AlphaSimulator` | Multi-threaded batch simulation scheduler with queue-based result handling |
| `AlphaMachine` | Genetic iteration pipeline — pruning, deduplication, and next-generation expression factories |
| `AlphaCalcCorr` | Multi-metric correlation engine (self / ppac / prod / self_web) with greedy max-independent-set |
| `SuperAlphaSimulator` | Dedicated simulator for SUPER-type alphas |
| `AlphaDyeing` | SUPER alpha construction and combo template management |
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
from wqbkit import AlphaDbCore, AlphaCalcCorr, AlphaGenerator

# Initialize core (auto-loads .env if present)
core = AlphaDbCore()

# Run correlation analysis
calcor = AlphaCalcCorr()
self_corr = calcor.calculate(alpha_ids, 'self')

# Generate next-generation expressions
generator = AlphaGenerator()
new_exprs = generator.second_order_factory(
    expression="ts_mean(close, 20)",
    region="USA",
    atom=True
)
```

---

## Configuration

Create a `.env` file in your working directory:

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
WQB_API_BASE_URL=https://www.worldquantbrain.com

# Logging & Retry
LOG_LEVEL=INFO
MAX_RETRIES=5
RETRY_DELAY_BASE=2

# Bark Push (optional)
BARK_KEY=your_bark_device_key
```

`wqbkit` automatically loads `.env` on import via `python-dotenv`.

---

## API Reference

### Core Classes

```python
from wqbkit import (
    AlphaBaseCore,       # WQB session + HTTP + retry
    AlphaDbCore,         # AlphaBaseCore + DB + PnL cache
    AlphaCalcCorr,       # Correlation analysis engine
    AlphaGenerator,      # Expression factory (0/1/2/3-order)
    AlphaSimulator,      # Multi-threaded simulation scheduler
    AlphaMachine,        # Genetic iteration pipeline
    AlphaDyeing,         # SUPER alpha builder
    SuperAlphaSimulator, # SUPER alpha simulator
    sc_send,             # Push notification helper
    schemas,             # Data models: FactorData, TaskData, SimulationData, FieldDate
)
```

### Correlation Analysis

```python
from wqbkit import AlphaCalcCorr

calcor = AlphaCalcCorr()

# Compute correlations
corrs = calcor.calculate(alpha_ids, metric='self')      # self-correlation
corrs = calcor.calculate(alpha_ids, metric='ppac')      # ppac correlation
corrs = calcor.calculate(alpha_ids, metric='prod')      # prod correlation

# Max independent alpha set (greedy approximation)
independent_alphas = calcor.max_independent_alphas(alpha_ids, threshold=0.7)
```

### Alpha Simulation

```python
from wqbkit import AlphaSimulator
from wqbkit.schemas import FactorData

sim = AlphaSimulator()

# Single alpha simulation
result = sim.simulate(expression="rank(close)", region="USA", universe="TOP3000")

# Batch simulation from database queue
sim.run_batch_simulation(task_id=123)
```

### Database Models

```python
from wqbkit import schemas

factor = schemas.FactorData(
    expression="rank(close)",
    region="USA",
    universe="TOP3000",
    neutralization="SUBINDUSTRY",
    decay=4,
)
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
    ├── correlation/   # AlphaCalcCorr (self/ppac/prod/self_web)
    ├── message/       # Bark push notifications
    └── competitions/  # Osmosis V1/V2/V3 toolkit
```

---

## License

MIT

---

## 概述

`wqbkit` 是一个用于自动化 [WorldQuant Brain](https://www.worldquantbrain.com) 平台 Alpha 研究的 Python 工具包，覆盖 Alpha 全生命周期：模拟、评分、去相关、遗传迭代进化。

### 核心功能

| 模块 | 说明 |
|------|------|
| `AlphaDbCore` | WQB 认证、HTTP 封装、指数退避重试 |
| `AlphaSimulator` | 多线程批量模拟调度器，队列式结果处理 |
| `AlphaMachine` | 遗传迭代管线：剪枝、去重、下一代表达式工厂 |
| `AlphaCalcCorr` | 多指标相关性引擎（self/ppac/prod/self_web），贪心最大独立集 |
| `SuperAlphaSimulator` | SUPER 类型 Alpha 专用模拟器 |
| `AlphaDyeing` | SUPER Alpha 构造与 combo 模板管理 |
| `sc_send` | Bark (iOS) 推送通知，用于长时任务提醒 |

### 快速开始

```python
from wqbkit import AlphaDbCore, AlphaCalcCorr, AlphaGenerator

core = AlphaDbCore()
calcor = AlphaCalcCorr()
new_exprs = AlphaGenerator().second_order_factory("ts_mean(close, 20)", region="USA")
```
