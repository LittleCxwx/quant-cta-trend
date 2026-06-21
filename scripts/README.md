# scripts/ · AI 友好的核心代码库

> 所有公开函数都带 **PEP 484 type hints + Google-style docstring**，
> 可被 LLM 直接 `import` 理解，也可通过 CLI 在 shell 中运行。

## 目录结构

```
scripts/
├── common.py                # 路径/日志/重试/板块过滤等基础工具
├── cli.py                   # 统一 CLI 入口
├── data/                    # 数据爬取与预处理
│   ├── fetch_daily.py       # 增量拉日 K 线
│   ├── fetch_market_value.py # 增量拉流通市值
│   ├── fetch_annual.py      # 拉最新年报/中报(可选)
│   ├── build_unified.py     # 合并成统一底表
│   └── update_all.py        # 一键更新入口
└── strategy/                # 核心策略逻辑
    ├── data_loader.py       # DataLoader + 顶层便捷函数
    ├── select_stocks.py     # 选股函数(select_stocks / select_stocks_for_date)
    ├── trading_signals.py   # 盘后交易信号
    └── backtest.py          # 向量化回测引擎
```

## CLI 用法

```bash
# 数据
python -m scripts.cli update --start 2026-01-01 [--with-annual] [--reset]
python -m scripts.cli update --start 2026-01-01 --codes 600519 000001

# 选股
python -m scripts.cli select --date 2025-12-25 --num 5 [--format json] [--output picks.csv]

# 盘后信号
python -m scripts.cli signals --date 2025-12-25 --budget 100000 \
                              --holdings "600519:100,000001:200" [--format json]
python -m scripts.cli signals --date 2025-12-25 --budget 100000 \
                              --positions-file data/positions.json --save-positions
# data/positions.json 支持旧格式 {"000001": 100};
# 用 --save-positions 新写入时会保存 shares/cost_price/cost_amount,卖出时显示估算盈亏。

# 回测
python -m scripts.cli backtest --start 2018-01-01 --end 2025-12-31 \
                               --num 5 --cash 10000 \
                               --output result.json --csv asset_curve.csv

# Web
python -m scripts.cli serve --host 0.0.0.0 --port 8000
```

## 作为 Python 模块使用

```python
from scripts.strategy import (
    select_stocks_for_date,
    get_signals_for_date,
    run_backtest,
    load_unified,
)

# 1. 单日选股
picks = select_stocks_for_date(date="2026-06-07", num=5)
print(picks[["股票代码", "名称", "EPSJB", "ROEJQ", "流通市值"]])

# 2. 盘后交易信号
sigs = get_signals_for_date(
    date="2026-06-07",
    budget=100_000.0,
    held_positions={"600519": 100, "000001": 200},
)
print(sigs.summary)
for a in sigs.buy_list:
    print(f"  BUY {a.code} {a.shares}股 @¥{a.price}")
for a in sigs.sell_list:
    print(f"  SELL {a.code} {a.shares}股 @¥{a.price}")

# 3. 回测
result = run_backtest(
    start_date="2018-01-01",
    end_date="2025-12-31",
    init_cash=10_000.0,
    select_stock_num=5,
)
print(result.metrics)
# 资金曲线
for row in result.asset_curve[-10:]:
    print(row["date"], row["total_asset"], row["drawdown"])
```

## 给 LLM 的接口说明

所有公开 API 的 docstring 都按以下结构编写：

```
Args:
    param_name (type): 说明。

Returns:
    返回类型: 说明。

Raises:
    异常类型: 触发条件。

Example:
    >>> # 可直接复制的最小示例
```

LLM 可以直接读源码 + docstring 完成任务：

- **「选 5 只今天该买的」** → 调 `select_stocks_for_date`
- **「算一下回测」** → 调 `run_backtest`
- **「明天该买/卖什么」** → 调 `get_signals_for_date`
- **「最近一次数据是什么时候」** → 调 `load_unified` / `DataLoader().latest_trade_date()`

## 配置文件位置

通过 `scripts/common.py` 集中管理：

| 常量 | 路径 |
| --- | --- |
| `PROJECT_ROOT` | 项目根目录 |
| `DATA_DIR` | `data/` |
| `STOCK_LIST_CSV` | `data/stock_zh_a_spot_em_filtered.csv` |
| `STOCK_LIST_SUFFIX_CSV` | `data/stock_zh_a_spot_em_filtered_with_suffix.csv` |
| `DAILY_DIR` | `data/stock_daily_data/` |
| `ALL_DAILY_CSV` | `data/all_stocks_daily.csv` |
| `UNIFIED_CSV` | `data/A股_日行情_年报_流通市值.csv` |
| `PROGRESS_DIR` | `data/.progress/` |

## 重试与断点续传

每个爬取脚本都使用：

- `scripts.common.retry()` 装饰器（指数退避，默认 3 次）
- `scripts.common.ProgressTracker` 持久化断点（`data/.progress/.fetch_*.json`）

如果想强制全量重跑某只股票：

```bash
python -m scripts.data.fetch_daily --start 2026-01-01 --codes 600519 --reset
```

## 测试

```bash
python -m pytest tests/ -v
```

当前覆盖：

- `tests/test_common.py` — 路径/重试/板块过滤
- `tests/test_select_stocks.py` — 选股过滤/排序/边界
- `tests/test_trading_signals.py` — 周三卖出/周四买入/持有/涨停跳过
