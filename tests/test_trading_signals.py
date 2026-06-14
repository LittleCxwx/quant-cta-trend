"""trading_signals 单元测试(纯逻辑,不依赖真实数据)。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from scripts.strategy.trading_signals import (
    TradingSignals,
    generate_signals,
)


# ===== 准备 mock loader =====
def _mock_loader(snapshots: dict):
    """snapshots: {date_iso: DataFrame}"""
    loader = MagicMock()

    def get_day_snapshot(d):
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        return snapshots.get(key, pd.DataFrame()).copy()

    def get_prev_day_snapshot(d):
        ts = pd.Timestamp(d)
        keys = sorted(snapshots.keys())
        prev = [k for k in keys if pd.Timestamp(k) < ts]
        if not prev:
            return None
        return snapshots[prev[-1]].copy()

    loader.get_day_snapshot.side_effect = get_day_snapshot
    loader.get_prev_day_snapshot.side_effect = get_prev_day_snapshot
    return loader


# ===== 周三卖出 =====
def test_wednesday_sell():
    # 2025-12-24 是周三
    held = {"000001": 100, "000002": 200}
    snap = pd.DataFrame([
        {"股票代码": "000001", "名称": "A", "收盘": 10.0, "prev_close": 9.5, "is_limit_up": False},
        {"股票代码": "000002", "名称": "B", "收盘": 20.0, "prev_close": 19.0, "is_limit_up": False},
    ])
    loader = _mock_loader({"2025-12-24": snap})

    sigs = generate_signals(
        signal_date="2025-12-24",
        held_positions=held,
        budget=0,
        loader=loader,
    )
    assert sigs.action_type == "sell"
    assert len(sigs.sell_list) == 2
    assert sigs.sell_list[0].code == "000001"
    assert sigs.sell_list[0].shares == 100


def test_wednesday_no_holdings_does_not_require_snapshot():
    """无持仓的周三卖出日不应被行情数据缺口阻断。"""
    loader = MagicMock()
    sigs = generate_signals(
        signal_date="2026-06-10",
        held_positions={},
        loader=loader,
    )

    assert sigs.action_type == "sell"
    assert sigs.sell_list == []
    assert sigs.hold_list == []
    assert "无持仓" in sigs.summary
    loader.get_day_snapshot.assert_not_called()


def test_wednesday_limit_up_skip():
    """涨停一字板不能卖。"""
    held = {"000001": 100}
    snap = pd.DataFrame([{
        "股票代码": "000001", "名称": "A", "收盘": 11.0,
        "prev_close": 10.0, "is_limit_up": True,
    }])
    loader = _mock_loader({"2025-12-24": snap})
    sigs = generate_signals(signal_date="2025-12-24", held_positions=held, loader=loader)
    assert sigs.action_type == "sell"
    assert sigs.sell_list == []
    assert len(sigs.hold_list) == 1
    assert "涨停" in sigs.hold_list[0].reason


# ===== 周四买入 =====
def test_thursday_buy():
    # 2025-12-25 是周四
    prev_snap = pd.DataFrame([
        {"日期": pd.Timestamp("2025-12-24"),
         "股票代码": "000001", "名称": "A", "EPSJB": 1.0, "ROEJQ": 15.0, "流通市值": 5e8, "收盘": 5.0},
        {"日期": pd.Timestamp("2025-12-24"),
         "股票代码": "000002", "名称": "B", "EPSJB": 0.5, "ROEJQ": 12.0, "流通市值": 1e9, "收盘": 8.0},
        {"日期": pd.Timestamp("2025-12-24"),
         "股票代码": "000003", "名称": "C", "EPSJB": 0.3, "ROEJQ": 11.0, "流通市值": 2e9, "收盘": 15.0},
    ])
    loader = _mock_loader({"2025-12-24": prev_snap})
    sigs = generate_signals(
        signal_date="2025-12-25",
        select_stock_num=2,
        budget=20_000.0,
        held_positions={},
        loader=loader,
    )
    assert sigs.action_type == "buy"
    assert sigs.base_date == "2025-12-24"
    assert len(sigs.buy_list) == 2
    # 应选 000001(最小市值) 和 000002
    codes = [b.code for b in sigs.buy_list]
    assert "000001" in codes
    assert "000002" in codes


def test_thursday_buy_rejects_stale_base_date():
    """周四买入不能用过期的前一交易日截面冒充周三数据。"""
    stale_snap = pd.DataFrame([
        {"日期": pd.Timestamp("2026-06-05"),
         "股票代码": "000001", "名称": "A", "EPSJB": 1.0, "ROEJQ": 15.0, "流通市值": 5e8, "收盘": 5.0},
    ])
    loader = _mock_loader({"2026-06-05": stale_snap})

    sigs = generate_signals(
        signal_date="2026-06-11",
        budget=100_000.0,
        held_positions={},
        loader=loader,
    )

    assert sigs.action_type == "buy"
    assert sigs.base_date == "2026-06-05"
    assert sigs.buy_list == []
    assert "数据过期" in sigs.summary
    assert "2026-06-10" in sigs.summary


# ===== 其他日持有 =====
def test_other_day_hold():
    # 2025-12-22 是周一
    snap = pd.DataFrame([{
        "股票代码": "000001", "名称": "A", "收盘": 10.0,
    }])
    loader = _mock_loader({"2025-12-22": snap})
    sigs = generate_signals(
        signal_date="2025-12-22", held_positions={"000001": 100}, loader=loader,
    )
    assert sigs.action_type == "hold"
    assert len(sigs.hold_list) == 1


# ===== dataclass 序列化 =====
def test_trading_signals_to_dict():
    sigs = TradingSignals(
        signal_date="2025-12-25", weekday=3, action_type="buy",
        base_date="2025-12-24", summary="test",
    )
    d = sigs.to_dict()
    assert d["signal_date"] == "2025-12-25"
    assert d["action_type"] == "buy"
    assert isinstance(d["buy_list"], list)
    assert d["summary"] == "test"
