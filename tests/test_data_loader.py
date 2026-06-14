"""DataLoader 的单元测试。"""

from __future__ import annotations

import pandas as pd

from scripts.strategy.data_loader import DataLoader


def test_get_prev_day_snapshot_uses_latest_date_before_target(tmp_path):
    fp = tmp_path / "unified.csv"
    pd.DataFrame([
        {"日期": "2026-06-05", "股票代码": "000001", "名称": "A", "收盘": 10.0},
        {"日期": "2026-06-05", "股票代码": "000002", "名称": "B", "收盘": 20.0},
        {"日期": "2026-06-10", "股票代码": "000001", "名称": "A", "收盘": 11.0},
        {"日期": "2026-06-10", "股票代码": "000002", "名称": "B", "收盘": 21.0},
    ]).to_csv(fp, index=False)

    snap = DataLoader(fp).get_prev_day_snapshot("2026-06-11")

    assert snap is not None
    assert set(snap["股票代码"]) == {"000001", "000002"}
    assert snap["日期"].dt.strftime("%Y-%m-%d").unique().tolist() == ["2026-06-10"]


def test_get_prev_day_snapshot_returns_none_before_first_date(tmp_path):
    fp = tmp_path / "unified.csv"
    pd.DataFrame([
        {"日期": "2026-06-05", "股票代码": "000001", "名称": "A", "收盘": 10.0},
    ]).to_csv(fp, index=False)

    assert DataLoader(fp).get_prev_day_snapshot("2026-06-05") is None
