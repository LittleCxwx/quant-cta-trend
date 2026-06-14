"""select_stocks 单元测试。

不需要真实数据,纯用 mock DataFrame 验证过滤/排序逻辑。
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.common import EXCLUDED_PREFIXES
from scripts.strategy.select_stocks import (
    DEFAULT_EXCLUDE_PREFIXES,
    select_stocks,
)


def _make_snap(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_excluded_prefixes_consistency():
    """确保 EXCLUDED_PREFIXES 覆盖了所有需剔除板块。"""
    expected = ("300", "301", "688", "689", "8", "92", "43")
    assert set(EXCLUDED_PREFIXES) == set(expected)
    assert set(DEFAULT_EXCLUDE_PREFIXES) == set(expected)


def test_select_stocks_basic():
    """基本功能:过滤+排序+Top N。"""
    snap = _make_snap([
        # code     name      close  EPS   ROE  market_cap
        ("000001", "A银行", 10.0, 1.0, 15.0, 1e9),   # 应入选
        ("600519", "B白酒", 1500.0, 30.0, 25.0, 2e11),  # 太大,不入
        ("300750", "C宁德", 200.0, 5.0, 20.0, 1e10),  # 创业板,不入
        ("688981", "D中芯", 50.0, 1.0, 12.0, 5e9),     # 科创板,不入
        ("000002", "E万科", 8.0, 0.5, 11.0, 8e8),      # 应入选(最小)
        ("002133", "F广宇", 5.0, 0.2, 12.0, 5e8),      # 应入选
        ("000666", "ST华联", 3.0, 0.1, 30.0, 2e8),    # ST(名称含 ST)
    ])
    snap.columns = ["股票代码", "名称", "收盘", "EPSJB", "ROEJQ", "流通市值"]

    out = select_stocks(snap, select_stock_num=3, exclude_st=True)

    # 应包含 000002(最小市值)和 002133(第二小)
    codes = set(out["股票代码"])
    assert "000002" in codes
    assert "002133" in codes
    # 不应包含创业板/科创板
    assert "300750" not in codes
    assert "688981" not in codes
    # 600519 市值太大,不应入选
    assert "600519" not in codes
    # ST 名称包含 ST,不应入选(exclude_st=True)
    assert "000666" not in codes
    # 排序应按 流通市值 升序
    assert list(out["流通市值"]) == sorted(out["流通市值"])
    assert len(out) == 3


def test_select_stocks_eps_roe_filter():
    """EPS <= 0 或 ROE <= 10 的股应被剔除。"""
    snap = _make_snap([
        ("000001", "A", 10.0, -1.0, 20.0, 1e9),    # EPS<0, 剔除
        ("000002", "B", 8.0,  1.0,  5.0, 1e9),     # ROE<10, 剔除
        ("000003", "C", 5.0,  0.1, 12.0, 1e9),     # 应入选
    ])
    snap.columns = ["股票代码", "名称", "收盘", "EPSJB", "ROEJQ", "流通市值"]
    out = select_stocks(snap, select_stock_num=5)
    assert list(out["股票代码"]) == ["000003"]


def test_select_stocks_top_n():
    """超过 N 只时只取 N。"""
    snap = _make_snap([
        (f"00000{i}", f"X{i}", 5.0, 0.5, 15.0, float(i * 1e8))
        for i in range(1, 8)
    ])
    snap.columns = ["股票代码", "名称", "收盘", "EPSJB", "ROEJQ", "流通市值"]
    out = select_stocks(snap, select_stock_num=3)
    assert len(out) == 3
    # 应取市值最小的 3 只
    assert set(out["股票代码"]) == {"000001", "000002", "000003"}


def test_select_stocks_empty_when_no_match():
    """全被过滤掉时返回空 DataFrame。"""
    snap = _make_snap([
        ("300750", "创业板", 10.0, 1.0, 15.0, 1e9),
        ("688981", "科创板", 10.0, 1.0, 15.0, 1e9),
    ])
    snap.columns = ["股票代码", "名称", "收盘", "EPSJB", "ROEJQ", "流通市值"]
    out = select_stocks(snap, select_stock_num=5)
    assert out.empty


def test_select_stocks_missing_columns_raises():
    """缺少必要列时应抛 KeyError。"""
    snap = pd.DataFrame({"股票代码": ["000001"], "名称": ["A"]})
    with pytest.raises(KeyError):
        select_stocks(snap, select_stock_num=5)
