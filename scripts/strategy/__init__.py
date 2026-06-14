"""策略模块:把"数据 + 选股 + 信号 + 回测"封装为可被 LLM/CLI/Web 调用的 API。

设计原则:
- 每个公开函数都带完整 type hints + Google-style docstring
- 任何函数都能在 1 秒内被独立 import & 调用
- 无隐式全局状态
"""

from scripts.strategy.data_loader import (
    DataLoader,
    load_daily_window,
    load_stock_list,
    load_unified,
)
from scripts.strategy.select_stocks import (
    DEFAULT_EXCLUDE_PREFIXES,
    STRATEGY_NAME,
    select_stocks,
    select_stocks_for_date,
)
from scripts.strategy.trading_signals import (
    TradingSignals,
    generate_signals,
    get_signals_for_date,
)
from scripts.strategy.backtest import (
    BacktestResult,
    DEFAULT_PARAMS,
    run_backtest,
)

__all__ = [
    # data_loader
    "DataLoader",
    "load_daily_window",
    "load_stock_list",
    "load_unified",
    # select_stocks
    "select_stocks",
    "select_stocks_for_date",
    "DEFAULT_EXCLUDE_PREFIXES",
    "STRATEGY_NAME",
    # trading_signals
    "TradingSignals",
    "generate_signals",
    "get_signals_for_date",
    # backtest
    "BacktestResult",
    "run_backtest",
    "DEFAULT_PARAMS",
]
