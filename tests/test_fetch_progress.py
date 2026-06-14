"""断点续传进度键的回归测试。"""

from __future__ import annotations

import pandas as pd

from scripts.common import ProgressTracker
from scripts.data import fetch_daily, fetch_market_value


def _tracker_factory(progress_dir):
    def factory(name: str):
        return ProgressTracker(name, persist_dir=progress_dir)

    return factory


def test_fetch_daily_ignores_legacy_progress_for_later_end(tmp_path, monkeypatch):
    daily_dir = tmp_path / "stock_daily_data"
    progress_dir = tmp_path / ".progress"
    daily_dir.mkdir()

    pd.DataFrame([
        {
            "日期": "2026-06-05",
            "股票代码": "000001",
            "开盘": 10.0,
            "收盘": 10.5,
            "最高": 10.8,
            "最低": 9.9,
            "成交量": 1000,
            "成交额": pd.NA,
            "振幅": pd.NA,
            "涨跌幅": pd.NA,
            "涨跌额": pd.NA,
            "换手率": pd.NA,
        }
    ]).to_csv(daily_dir / "000001.csv", index=False)

    # 旧版本只记录股票代码,这不能阻止更晚 end 日期的增量更新。
    ProgressTracker(fetch_daily.PROGRESS_NAME, persist_dir=progress_dir).add("000001")
    calls: list[tuple[str, str, str]] = []

    def fake_fetch_one(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        calls.append((symbol, start_date, end_date))
        return pd.DataFrame([
            {
                "日期": "2026-06-10",
                "股票代码": "000001",
                "开盘": 11.0,
                "收盘": 11.5,
                "最高": 11.8,
                "最低": 10.9,
                "成交量": 2000,
                "成交额": pd.NA,
                "振幅": pd.NA,
                "涨跌幅": pd.NA,
                "涨跌额": pd.NA,
                "换手率": pd.NA,
            }
        ])

    monkeypatch.setattr(fetch_daily, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(fetch_daily, "PROGRESS_DIR", progress_dir)
    monkeypatch.setattr(fetch_daily, "ProgressTracker", _tracker_factory(progress_dir))
    monkeypatch.setattr(fetch_daily, "_fetch_one", fake_fetch_one)

    assert fetch_daily.run("2026-06-01", "2026-06-10", ["000001"]) == 1
    assert calls == [("000001", "20260606", "20260610")]

    out = pd.read_csv(daily_dir / "000001.csv", dtype={"股票代码": str})
    assert out["日期"].max() == "2026-06-10"

    tracker = ProgressTracker(fetch_daily.PROGRESS_NAME, persist_dir=progress_dir)
    assert tracker.has("000001:20260610")


def test_fetch_market_value_ignores_legacy_progress_for_later_target(tmp_path, monkeypatch):
    cache_dir = tmp_path / "market_value_cache"
    progress_dir = tmp_path / ".progress"
    cache_dir.mkdir()

    pd.DataFrame([
        {"日期": "2026-06-05", "流通市值": 1000.0},
    ]).to_csv(cache_dir / "000001.csv", index=False)

    ProgressTracker(fetch_market_value.PROGRESS_NAME, persist_dir=progress_dir).add("000001")
    calls: list[str] = []

    def fake_fetch_one(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return pd.DataFrame([
            {"日期": pd.Timestamp("2026-06-10"), "流通市值": 1200.0},
        ])

    monkeypatch.setattr(fetch_market_value, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(fetch_market_value, "ProgressTracker", _tracker_factory(progress_dir))
    monkeypatch.setattr(fetch_market_value, "_fetch_one", fake_fetch_one)

    assert fetch_market_value.run(["000001"], target_date="2026-06-10") == 1
    assert calls == ["000001"]

    out = pd.read_csv(cache_dir / "000001.csv")
    assert out["日期"].max() == "2026-06-10"

    tracker = ProgressTracker(fetch_market_value.PROGRESS_NAME, persist_dir=progress_dir)
    assert tracker.has("000001:20260610")
