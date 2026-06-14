"""向量化回测引擎。

相对原 选股.ipynb 的 Python 循环实现,本版本做了向量化优化:
- 涨跌停判定一次性 groupby + shift
- 买卖动作一次性 merge
- 资金曲线迭代计算,但避免逐行 groupby.apply

输出:BacktestResult(评价指标 + 资金曲线 + 交易明细),可序列化为 JSON 给前端。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

from scripts.common import logger, parse_date
from scripts.strategy.data_loader import get_default_loader, load_daily_window
from scripts.strategy.select_stocks import select_stocks, DEFAULT_EXCLUDE_PREFIXES

WEEKDAY_BUY = 3
WEEKDAY_SELL = 2


@dataclass
class BacktestParams:
    """回测参数(可序列化)。"""
    start_date: str
    end_date: str
    init_cash: float = 10_000.0
    select_stock_num: int = 5
    eps_threshold: float = 0.0
    roe_threshold: float = 10.0
    c_rate: float = 1.2 / 10000      # 手续费
    t_rate: float = 1.0 / 1000       # 印花税(卖出单边)
    exclude_st: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = BacktestParams(
    start_date="2018-01-01",
    end_date="2025-12-31",
)


@dataclass
class BacktestResult:
    """回测结果(给前端/LLM 用)。"""
    params: BacktestParams
    asset_curve: list[dict] = field(default_factory=list)  # [{date, total_asset, cash, mv, drawdown, bench_value}, ...]
    trades: list[dict] = field(default_factory=list)      # [{date, code, name, action, price, shares, amount, cash_after}, ...]
    metrics: dict = field(default_factory=dict)            # {累计收益, 年化, 最大回撤, 夏普, ...}
    base_index: str = "沪深300"                             # 基准名
    base_index_code: str = "sh000300"

    def to_dict(self) -> dict:
        return {
            "params": self.params.to_dict(),
            "asset_curve": self.asset_curve,
            "trades": self.trades,
            "metrics": self.metrics,
            "base_index": self.base_index,
            "base_index_code": self.base_index_code,
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)


# ===== 工具:涨跌停标记 =====
def _add_limit_flags(df: pd.DataFrame) -> pd.DataFrame:
    """一次性给全表加 is_limit_up / is_limit_down(按股票代码分组,shift 1)。"""
    df = df.sort_values(["股票代码", "日期"]).copy()
    eps = 1e-6
    df["prev_close"] = df.groupby("股票代码")["收盘"].shift(1)
    df["is_limit_up"] = df["收盘"] >= df["prev_close"] * 1.10 - eps
    df["is_limit_down"] = df["收盘"] <= df["prev_close"] * 0.90 + eps
    return df


# ===== 工具:拉基准 =====
def _fetch_benchmark(symbol: str, start: str, end: str) -> pd.Series:
    """拉指数基准日线(简单复权收盘价)。"""
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=symbol)
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= parse_date(start)) & (df["date"] <= parse_date(end))]
    return df.set_index("date")["close"]


# ===== 评价指标 =====
def _calc_metrics(asset: pd.Series, bench: pd.Series, init_cash: float) -> dict:
    """计算评价指标。"""
    trading_days = 252
    n = len(asset)
    if n < 2:
        return {"error": "回测窗口太短"}

    total_ret = float(asset.iloc[-1] / init_cash - 1)
    annual_ret = float((1 + total_ret) ** (trading_days / n) - 1)
    cum_max = asset.cummax()
    drawdown = asset / cum_max - 1
    max_dd = float(drawdown.min())

    daily_ret = asset.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(trading_days)) if daily_ret.std() else 0.0

    if not bench.empty:
        bench_ret = float(bench.iloc[-1] / bench.iloc[0] - 1)
        bench_daily = bench.pct_change().dropna()
        # beta
        aligned = pd.concat([daily_ret, bench_daily], axis=1, join="inner").dropna()
        aligned.columns = ["s", "b"]
        if len(aligned) > 2 and aligned["b"].var() > 0:
            beta = float(aligned[["s", "b"]].cov().iloc[0, 1] / aligned["b"].var())
            alpha = float(
                (daily_ret.mean() - beta * bench_daily.mean()) * trading_days
            )
        else:
            beta = alpha = 0.0
    else:
        bench_ret = beta = alpha = 0.0

    return {
        "累计收益率": round(total_ret, 4),
        "年化收益率": round(annual_ret, 4),
        "最大回撤":   round(max_dd, 4),
        "夏普比率":   round(sharpe, 4),
        "基准累计收益率": round(bench_ret, 4),
        "alpha": round(alpha, 4),
        "beta": round(beta, 4),
        "交易日数": int(n),
        "期末总资产": round(float(asset.iloc[-1]), 2),
    }


# ===== 主回测 =====
def run_backtest(
    start_date: str = "2018-01-01",
    end_date: str = "2025-12-31",
    init_cash: float = 10_000.0,
    select_stock_num: int = 5,
    eps_threshold: float = 0.0,
    roe_threshold: float = 10.0,
    c_rate: float = 1.2 / 10000,
    t_rate: float = 1.0 / 1000,
    exclude_st: bool = True,
    include_benchmark: bool = True,
) -> BacktestResult:
    """执行向量化回测。

    Args:
        start_date / end_date: 回测窗口。
        init_cash: 初始资金。
        select_stock_num: 每周持仓数。
        eps_threshold / roe_threshold: 基本面过滤。
        c_rate: 手续费(双边)。
        t_rate: 印花税(卖出单边)。
        exclude_st: 剔除 ST。
        include_benchmark: 是否拉沪深 300 基准。

    Returns:
        BacktestResult 对象,内含 asset_curve / trades / metrics。

    Example:
        >>> result = run_backtest("2020-01-01", "2024-12-31")
        >>> print(result.metrics)
    """
    params = BacktestParams(
        start_date=start_date, end_date=end_date,
        init_cash=init_cash, select_stock_num=select_stock_num,
        eps_threshold=eps_threshold, roe_threshold=roe_threshold,
        c_rate=c_rate, t_rate=t_rate, exclude_st=exclude_st,
    )
    result = BacktestResult(params=params)

    logger.info("加载数据 %s ~ %s …", start_date, end_date)
    df = load_daily_window(start_date, end_date)
    if df.empty:
        logger.error("无数据,回测终止")
        return result

    df = _add_limit_flags(df)
    df["weekday"] = df["日期"].dt.weekday
    df = df.sort_values(["日期", "股票代码"]).reset_index(drop=True)

    # 预计算:每个交易日(周四)对应的"前一天截面"
    trade_dates = sorted(df["日期"].unique())
    date_to_prev: dict[pd.Timestamp, pd.Timestamp] = {}
    for i in range(1, len(trade_dates)):
        date_to_prev[trade_dates[i]] = trade_dates[i - 1]

    cash = init_cash
    positions: dict[str, int] = {}  # {code: shares}
    asset_records: list[dict] = []
    trade_records: list[dict] = []

    # 准备 close_dict 加速 O(1) 收盘价查询
    # 结构: {date: {code: close}}
    close_dict: dict[pd.Timestamp, dict[str, float]] = (
        df.groupby("日期")
        .apply(lambda g: dict(zip(g["股票代码"], g["收盘"])), include_groups=False)
        .to_dict()
    )
    is_limit_up_dict: dict[pd.Timestamp, dict[str, bool]] = (
        df.groupby("日期")
        .apply(lambda g: dict(zip(g["股票代码"], g["is_limit_up"].fillna(False))), include_groups=False)
        .to_dict()
    )

    for d in tqdm(trade_dates, desc="回测"):
        wd = d.weekday()
        day_close = close_dict.get(d, {})

        # ===== 周三:卖出 =====
        if wd == WEEKDAY_SELL and positions:
            for code in list(positions.keys()):
                shares = positions[code]
                price = day_close.get(code)
                if price is None:
                    # 停牌,顺延
                    continue
                if is_limit_up_dict.get(d, {}).get(code, False):
                    # 涨停,不能卖
                    continue
                amt = price * shares
                tax = amt * t_rate
                commission = amt * c_rate
                cash += amt - tax - commission
                trade_records.append({
                    "date": d.strftime("%Y-%m-%d"),
                    "code": code, "action": "sell",
                    "price": round(price, 4), "shares": shares,
                    "amount": round(amt, 2), "fee": round(tax + commission, 2),
                    "cash_after": round(cash, 2),
                })
                del positions[code]

        # ===== 周四:买入 =====
        if wd == WEEKDAY_BUY and cash > 0:
            prev_d = date_to_prev.get(d)
            if prev_d is None:
                pass
            else:
                prev_snap = df[df["日期"] == prev_d]
                picks = select_stocks(
                    prev_snap,
                    select_stock_num=select_stock_num,
                    eps_threshold=eps_threshold,
                    roe_threshold=roe_threshold,
                    exclude_st=exclude_st,
                )
                if not picks.empty:
                    per = cash / len(picks)
                    for _, row in picks.iterrows():
                        code = str(row["股票代码"])
                        name = str(row.get("名称", "?"))
                        price = float(row["收盘"])
                        shares = int(per // (price * 100)) * 100
                        if shares == 0:
                            continue
                        cost = price * shares
                        commission = cost * c_rate
                        if cash < cost + commission:
                            continue
                        cash -= cost + commission
                        positions[code] = positions.get(code, 0) + shares
                        trade_records.append({
                            "date": d.strftime("%Y-%m-%d"),
                            "code": code, "name": name, "action": "buy",
                            "price": round(price, 4), "shares": shares,
                            "amount": round(cost, 2), "fee": round(commission, 2),
                            "cash_after": round(cash, 2),
                        })

        # ===== 每日资产统计 =====
        market_value = sum(
            day_close.get(c, 0) * s for c, s in positions.items()
        )
        total_asset = cash + market_value
        cum_max = max((r["total_asset"] for r in asset_records), default=init_cash)
        cum_max = max(cum_max, total_asset)
        dd = total_asset / cum_max - 1
        asset_records.append({
            "date": d.strftime("%Y-%m-%d"),
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "total_asset": round(total_asset, 2),
            "drawdown": round(dd, 4),
            "position_count": len(positions),
        })

    result.asset_curve = asset_records
    result.trades = trade_records

    # ===== 基准 =====
    if include_benchmark:
        try:
            bench = _fetch_benchmark("sh000300", start_date, end_date)
            asset_series = pd.Series(
                [r["total_asset"] for r in asset_records],
                index=pd.to_datetime([r["date"] for r in asset_records]),
            )
            # 把基准前向 fill 到 asset 的所有日期
            bench = bench.reindex(asset_series.index).ffill()
            # 归一化到 init_cash
            bench_value = init_cash * bench / bench.iloc[0]
            asset_series_b = asset_series
            # 把每行的 bench_value 塞进 asset_curve
            bench_dict = bench_value.to_dict()
            for row in asset_records:
                d_ts = pd.Timestamp(row["date"])
                row["bench_value"] = round(float(bench_dict.get(d_ts, np.nan)), 2)
            result.metrics = _calc_metrics(asset_series_b, bench_value, init_cash)
        except Exception as e:  # noqa: BLE001
            logger.warning("拉基准失败: %s,仅返回策略曲线", e)
            asset_series = pd.Series(
                [r["total_asset"] for r in asset_records],
                index=pd.to_datetime([r["date"] for r in asset_records]),
            )
            result.metrics = _calc_metrics(asset_series, pd.Series(dtype=float), init_cash)
    else:
        asset_series = pd.Series(
            [r["total_asset"] for r in asset_records],
            index=pd.to_datetime([r["date"] for r in asset_records]),
        )
        result.metrics = _calc_metrics(asset_series, pd.Series(dtype=float), init_cash)

    logger.info("回测完成: %s", json.dumps(result.metrics, ensure_ascii=False))
    return result
