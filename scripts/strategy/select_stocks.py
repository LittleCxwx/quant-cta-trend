"""选股策略核心。

策略定义(与原 选股.ipynb / 未来选股.ipynb 保持一致):
    1. 板块过滤:剔除 30x/301/688/689/8/92/43 开头(创业板/科创板/北交所)
    2. 基本面过滤:EPSJB > 0 且 ROEJQ > 10
    3. 排序:按 流通市值 升序,取 Top N

不依赖:交易日历 / 撮合逻辑 / 持仓状态(纯截面选股)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from scripts.common import EXCLUDED_PREFIXES, is_excluded
from scripts.strategy.data_loader import get_default_loader

# ===== 策略元信息 =====
STRATEGY_NAME = "周四小市值+基本面策略"
STRATEGY_VERSION = "1.0"
DEFAULT_EXCLUDE_PREFIXES = EXCLUDED_PREFIXES

# ===== 默认阈值(可由调用方覆盖)=====
DEFAULT_PARAMS: dict = {
    "select_stock_num": 5,
    "eps_threshold": 0.0,         # EPSJB > eps_threshold
    "roe_threshold": 10.0,        # ROEJQ > roe_threshold (%)
    "mv_ascending": True,         # 流通市值升序(小市值优先)
    "exclude_st": True,           # 剔除 ST / *ST
}


def _filter_excluded_codes(
    df: pd.DataFrame,
    code_col: str = "股票代码",
    exclude_st: bool = True,
) -> pd.DataFrame:
    """按代码前缀 + ST 名称剔除。"""
    mask = ~df[code_col].astype(str).str.startswith(EXCLUDED_PREFIXES)
    if exclude_st and "名称" in df.columns:
        mask &= ~df["名称"].astype(str).str.contains(r"ST|\*ST", regex=True, na=False)
    return df[mask]


def select_stocks(
    day_df: pd.DataFrame,
    select_stock_num: int = 5,
    eps_threshold: float = 0.0,
    roe_threshold: float = 10.0,
    exclude_st: bool = True,
) -> pd.DataFrame:
    """对单日截面应用选股策略。

    Args:
        day_df: 某一日的全市场 DataFrame,必须含
            [股票代码, 名称, EPSJB, ROEJQ, 流通市值, 收盘] 列。
        select_stock_num: 选出股票数量(默认 5)。
        eps_threshold: EPSJB 阈值,默认 0(仅保留盈利股)。
        roe_threshold: ROEJQ 阈值(%),默认 10。
        exclude_st: 是否剔除 ST / *ST 股(默认 True)。

    Returns:
        按 流通市值 升序排列的 Top N DataFrame,字段:
        [股票代码, 名称, EPSJB, ROEJQ, 收盘, 流通市值, 选股权重]。

    Raises:
        KeyError: 缺少必要列。

    Example:
        >>> from scripts.strategy import select_stocks
        >>> snap = loader.get_day_snapshot("2025-12-25")
        >>> picks = select_stocks(snap, select_stock_num=5)
    """
    required = {"股票代码", "EPSJB", "ROEJQ", "流通市值"}
    missing = required - set(day_df.columns)
    if missing:
        raise KeyError(f"day_df 缺少字段: {missing}")

    df = day_df.copy()

    # 1. 板块 / ST 过滤
    df = _filter_excluded_codes(df, exclude_st=exclude_st)

    # 2. 基本面过滤
    df = df[(df["EPSJB"] > eps_threshold) & (df["ROEJQ"] > roe_threshold)]

    # 3. 排序 + Top N
    df = df.sort_values("流通市值", ascending=True).head(select_stock_num).copy()

    # 4. 计算等权(若资金不足可由调用方重算)
    if not df.empty:
        df["选股权重"] = 1.0 / select_stock_num

    return df.reset_index(drop=True)


def select_stocks_for_date(
    date: str | datetime,
    select_stock_num: int = 5,
    eps_threshold: float = 0.0,
    roe_threshold: float = 10.0,
    exclude_st: bool = True,
    use_prev_day: bool = True,
    loader=None,
) -> pd.DataFrame:
    """便捷函数:对某一日(或其前一日)做选股。

    Args:
        date: 目标日期 ``YYYY-MM-DD``。
        select_stock_num: 选出股票数量。
        eps_threshold / roe_threshold: 基本面阈值。
        exclude_st: 是否剔除 ST / *ST。
        use_prev_day: True = 用 date 之前的最近一个交易日数据
            (与"周四用周三数据选股"对齐);False = 用 date 当日。
        loader: 自定义 DataLoader(测试用)。

    Returns:
        选股结果 DataFrame。

    Example:
        >>> picks = select_stocks_for_date("2025-12-25")
        >>> print(picks[["股票代码", "名称", "EPSJB", "ROEJQ", "流通市值"]])
    """
    if loader is None:
        loader = get_default_loader()
    if use_prev_day:
        snap = loader.get_prev_day_snapshot(date)
        if snap is None:
            raise ValueError(f"{date} 之前没有可用的交易日数据")
    else:
        snap = loader.get_day_snapshot(date)
        if snap.empty:
            raise ValueError(f"{date} 当日没有数据(可能不是交易日或数据缺失)")

    return select_stocks(
        snap,
        select_stock_num=select_stock_num,
        eps_threshold=eps_threshold,
        roe_threshold=roe_threshold,
        exclude_st=exclude_st,
    )
