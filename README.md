# wqb-toolkit

WorldQuant Brain Alpha Research Automation Toolkit

## Overview

`wqb-toolkit` is a Python toolkit for automating alpha research workflows on the WorldQuant Brain (WQB) platform. It provides core infrastructure for:

- **Alpha Simulation**: Multi-threaded batch simulation with queue-based result handling
- **Alpha Machine**: Genetic iteration pipeline for alpha expression evolution
- **Correlation Analysis**: Self, PPAC, prod, and self_web correlation calculations
- **Database Management**: PostgreSQL ORM with SQLAlchemy for alpha metadata and PnL caching
- **Super Alpha Tools**: Construction and simulation of SUPER-type alphas

## Installation

```bash
pip install wqb-toolkit
```

### Prerequisites

- Python >= 3.10
- PostgreSQL (for database features)
- `wqb` SDK (WorldQuant Brain official SDK, install via pip)

## Quick Start

```python
from wqbkit.app.core.alpha_db_core import AlphaDbCore
from wqbkit.modules.correlation import AlphaCalcCorr

core = AlphaDbCore()
calcor = AlphaCalcCorr()
```

## Configuration

Create a `.env` file in your project root:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=WorldQuant
DB_USER=your_db_user
DB_PASSWORD=your_db_password
WQB_USERNAME=your_wqb_username
WQB_PASSWORD=your_wqb_password
WQB_API_BASE_URL=https://www.worldquantbrain.com
```

## License

MIT
