"""盘后交易信号生成。

语义:用户给出一个"信号日"(通常是今日收盘后,生成"明日开盘应执行的操作")。

策略:
- 周三 (weekday=2): 当前持仓全部卖出(涨停一字板除外)
- 周四 (weekday=3): 用周三收盘数据选 Top N,等权买入
- 其他: 持有(无操作)

输出结构清晰、便于 LLM 解析 / 推送给用户。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import pandas as pd

from scripts.common import logger, parse_date
from scripts.strategy.data_loader import get_default_loader
from scripts.strategy.select_stocks import (
    DEFAULT_PARAMS,
    select_stocks,
)

WEEKDAY_BUY = 3   # 周四
WEEKDAY_SELL = 2  # 周三


@dataclass
class TradeAction:
    """单只股票的买卖动作。"""
    code: str
    name: str
    action: str            # "buy" / "sell" / "hold"
    price: float | None = None       # 参考价(选股时为前一日收盘,信号时为信号日收盘)
    shares: int = 0                 # 建议股数(0 表示不操作)
    amount: float = 0.0             # 估算金额
    reason: str = ""                # 人话解释(给 LLM/用户看)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradingSignals:
    """某一日的完整交易信号。"""
    signal_date: str                       # 信号日(ISO 格式)
    weekday: int                           # 0=周一 ... 6=周日
    action_type: str                       # "buy" / "sell" / "hold"
    base_date: str                         # 用于"做选股/判定"的基准日(可能是前一天)
    buy_list: list[TradeAction] = field(default_factory=list)
    sell_list: list[TradeAction] = field(default_factory=list)
    hold_list: list[TradeAction] = field(default_factory=list)
    summary: str = ""                      # 人话总结

    def to_dict(self) -> dict:
        return {
            "signal_date": self.signal_date,
            "weekday": self.weekday,
            "action_type": self.action_type,
            "base_date": self.base_date,
            "buy_list": [a.to_dict() for a in self.buy_list],
            "sell_list": [a.to_dict() for a in self.sell_list],
            "hold_list": [a.to_dict() for a in self.hold_list],
            "summary": self.summary,
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)


def _price_for(snap: pd.DataFrame, code: str) -> float | None:
    row = snap[snap["股票代码"] == code]
    if row.empty:
        return None
    try:
        return float(row["收盘"].iloc[0])
    except (KeyError, TypeError, ValueError):
        return None


def generate_signals(
    signal_date: str | datetime,
    select_stock_num: int = 5,
    eps_threshold: float = 0.0,
    roe_threshold: float = 10.0,
    exclude_st: bool = True,
    budget: float = 10_000.0,
    held_positions: Optional[dict[str, int]] = None,
    loader=None,
) -> TradingSignals:
    """生成盘后交易信号(明日开盘应执行什么)。

    Args:
        signal_date: 信号日(通常为今日收盘后)。
        select_stock_num: 周四选股的标的数量。
        eps_threshold / roe_threshold: 基本面阈值。
        exclude_st: 是否剔除 ST。
        budget: 用于周四买入的总预算(元)。
        held_positions: 当前持仓 {code: shares},None 表示空仓。
        loader: 自定义 DataLoader(测试用),None 使用默认全局单例。

    Returns:
        TradingSignals 对象,包含 buy_list / sell_list / hold_list。

    Example:
        >>> sigs = generate_signals("2025-12-25", held_positions={"600519": 100})
        >>> print(sigs.summary)
        >>> for a in sigs.sell_list:
        ...     print(a.code, a.shares)
    """
    sig_ts = parse_date(signal_date)
    weekday = sig_ts.weekday()
    held_positions = held_positions or {}
    if loader is None:
        loader = get_default_loader()

    if weekday == WEEKDAY_SELL:
        # ===== 周三: 卖出所有持仓(涨停除外) =====
        return _signals_for_sell(sig_ts, loader, held_positions)
    if weekday == WEEKDAY_BUY:
        # ===== 周四: 用周三数据选股,等权买入 =====
        return _signals_for_buy(
            sig_ts, loader,
            select_stock_num=select_stock_num,
            eps_threshold=eps_threshold,
            roe_threshold=roe_threshold,
            exclude_st=exclude_st,
            budget=budget,
            held_positions=held_positions,
        )
    # ===== 其他日: 持有 =====
    return _signals_hold(sig_ts, loader, held_positions)


# ===== 内部:周三卖出 =====
def _signals_for_sell(
    sig_ts: pd.Timestamp,
    loader,
    held_positions: dict[str, int],
) -> TradingSignals:
    if not held_positions:
        summary = f"📉 {sig_ts.date()} 周三卖出日: 当前无持仓,无需卖出。"
        logger.info(summary)
        return TradingSignals(
            signal_date=sig_ts.strftime("%Y-%m-%d"),
            weekday=sig_ts.weekday(),
            action_type="sell",
            base_date=sig_ts.strftime("%Y-%m-%d"),
            summary=summary,
        )

    snap = loader.get_day_snapshot(sig_ts)
    if snap.empty:
        logger.error("统一底表中无 %s 的数据——请先运行 python -m scripts.cli update", sig_ts.date())
        return TradingSignals(
            signal_date=sig_ts.strftime("%Y-%m-%d"),
            weekday=sig_ts.weekday(),
            action_type="sell",
            base_date=sig_ts.strftime("%Y-%m-%d"),
            summary="无数据",
        )

    sell_list: list[TradeAction] = []
    hold_list: list[TradeAction] = []
    for code, shares in held_positions.items():
        row = snap[snap["股票代码"] == code]
        if row.empty:
            # 停牌
            hold_list.append(TradeAction(
                code=code, name="?", action="hold", shares=shares,
                reason="停牌,无法卖出",
            ))
            continue
        name = row["名称"].iloc[0] if "名称" in row.columns else "?"
        price = float(row["收盘"].iloc[0])
        prev_close = float(row.get("prev_close", pd.Series([price])).iloc[0]) if "prev_close" in row.columns else price
        is_limit_up = price >= prev_close * 1.10 - 1e-6

        if is_limit_up:
            hold_list.append(TradeAction(
                code=code, name=name, action="hold", price=price, shares=shares,
                reason="涨停一字板,无法卖出(顺延)",
            ))
        else:
            amount = price * shares
            sell_list.append(TradeAction(
                code=code, name=name, action="sell",
                price=price, shares=shares, amount=amount,
                reason=f"周三止盈,按收盘价 ¥{price:.2f} 全仓卖出",
            ))

    n_sell = len(sell_list)
    n_hold = len(hold_list)
    summary = (
        f"📉 {sig_ts.date()} 周三卖出日: "
        f"可卖出 {n_sell} 只,继续持有 {n_hold} 只(涨停/停牌)。"
    )
    logger.info(summary)
    return TradingSignals(
        signal_date=sig_ts.strftime("%Y-%m-%d"),
        weekday=sig_ts.weekday(),
        action_type="sell",
        base_date=sig_ts.strftime("%Y-%m-%d"),
        sell_list=sell_list,
        hold_list=hold_list,
        summary=summary,
    )


# ===== 内部:周四买入 =====
def _signals_for_buy(
    sig_ts: pd.Timestamp,
    loader,
    *,
    select_stock_num: int,
    eps_threshold: float,
    roe_threshold: float,
    exclude_st: bool,
    budget: float,
    held_positions: dict[str, int],
) -> TradingSignals:
    # 用 sig_ts 前一天的截面做选股
    prev_snap = loader.get_prev_day_snapshot(sig_ts)
    if prev_snap is None:
        logger.error("统一底表中无 %s 之前的交易日数据——请先运行 python -m scripts.cli update", sig_ts.date())
        return TradingSignals(
            signal_date=sig_ts.strftime("%Y-%m-%d"),
            weekday=sig_ts.weekday(),
            action_type="buy",
            base_date=sig_ts.strftime("%Y-%m-%d"),
            summary="无数据",
        )

    base_ts = pd.Timestamp(prev_snap["日期"].iloc[0]).normalize()
    expected_base_ts = sig_ts - pd.Timedelta(days=1)
    if base_ts != expected_base_ts:
        update_start = (base_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        update_end = expected_base_ts.strftime("%Y-%m-%d")
        summary = (
            f"数据过期: 周四买入需要 {expected_base_ts.date()} 的收盘数据,"
            f"统一底表当前只能取到 {base_ts.date()}。"
            f"请先运行 python -m scripts.cli update --start {update_start} --end {update_end}。"
        )
        logger.error(summary)
        return TradingSignals(
            signal_date=sig_ts.strftime("%Y-%m-%d"),
            weekday=sig_ts.weekday(),
            action_type="buy",
            base_date=base_ts.strftime("%Y-%m-%d"),
            summary=summary,
        )

    picks = select_stocks(
        prev_snap,
        select_stock_num=select_stock_num,
        eps_threshold=eps_threshold,
        roe_threshold=roe_threshold,
        exclude_st=exclude_st,
    )
    base_date = base_ts.strftime("%Y-%m-%d")

    cash_per_stock = budget / max(len(picks), 1)
    buy_list: list[TradeAction] = []
    hold_list: list[TradeAction] = [
        TradeAction(code=c, name="?", action="hold", shares=s,
                    reason="继续持有(非新选 Top)")
        for c, s in held_positions.items()
    ]

    for _, row in picks.iterrows():
        code = str(row["股票代码"])
        name = str(row.get("名称", "?"))
        price = float(row["收盘"])
        # 100 股取整
        shares = int(cash_per_stock // (price * 100)) * 100
        if shares == 0:
            buy_list.append(TradeAction(
                code=code, name=name, action="buy",
                price=price, shares=0,
                reason=f"资金不足(¥{cash_per_stock:.0f} 买不起 1 手 ¥{price*100:.0f}),跳过",
            ))
            continue
        amount = price * shares
        buy_list.append(TradeAction(
            code=code, name=name, action="buy",
            price=price, shares=shares, amount=amount,
            reason=f"周四开盘按 ¥{price:.2f} 买入 {shares} 股(等权 ¥{cash_per_stock:.0f})",
        ))

    summary = (
        f"📈 {sig_ts.date()} 周四买入日: "
        f"基于 {base_date} 数据,选出 {len(picks)} 只,实际可买 {sum(a.shares > 0 for a in buy_list)} 只。"
    )
    logger.info(summary)
    return TradingSignals(
        signal_date=sig_ts.strftime("%Y-%m-%d"),
        weekday=sig_ts.weekday(),
        action_type="buy",
        base_date=base_date,
        buy_list=buy_list,
        hold_list=hold_list,
        summary=summary,
    )


# ===== 内部:其他日持有 =====
def _signals_hold(
    sig_ts: pd.Timestamp,
    loader,
    held_positions: dict[str, int],
) -> TradingSignals:
    hold_list: list[TradeAction] = []
    snap = loader.get_day_snapshot(sig_ts)
    for code, shares in held_positions.items():
        row = snap[snap["股票代码"] == code] if not snap.empty else pd.DataFrame()
        if row.empty:
            hold_list.append(TradeAction(
                code=code, name="?", action="hold", shares=shares,
                reason="停牌或数据缺失,继续持有",
            ))
        else:
            name = row["名称"].iloc[0] if "名称" in row.columns else "?"
            price = float(row["收盘"].iloc[0]) if "收盘" in row.columns else None
            hold_list.append(TradeAction(
                code=code, name=name, action="hold",
                price=price, shares=shares,
                reason="非周三/周四,继续持有",
            ))

    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][sig_ts.weekday()]
    summary = f"⏸️  {sig_ts.date()} {weekday_cn}:非操作日,继续持有 {len(hold_list)} 只。"
    return TradingSignals(
        signal_date=sig_ts.strftime("%Y-%m-%d"),
        weekday=sig_ts.weekday(),
        action_type="hold",
        base_date=sig_ts.strftime("%Y-%m-%d"),
        hold_list=hold_list,
        summary=summary,
    )


# ===== 顶层便捷函数 =====
def get_signals_for_date(
    date: str | datetime,
    select_stock_num: int = 5,
    budget: float = 10_000.0,
    held_positions: Optional[dict[str, int]] = None,
) -> TradingSignals:
    """便捷函数:对某一日生成盘后交易信号。

    Example:
        >>> sigs = get_signals_for_date("2025-12-25")
        >>> print(sigs.to_json(indent=2))
    """
    return generate_signals(
        signal_date=date,
        select_stock_num=select_stock_num,
        budget=budget,
        held_positions=held_positions,
    )
