"""统一底表的数据访问层。

把"如何从大 CSV 里取一个截面 / 一段时间"封装成易用的函数。
设计上尽量减少 IO:大文件只读一次,通过 dtype 优化 + 索引缓存避免重复解析。
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from scripts.common import STOCK_LIST_CSV, UNIFIED_CSV, logger, parse_date


class DataLoader:
    """延迟加载 + 简单缓存的数据访问器。

    用法::

        loader = DataLoader()
        df = loader.load(start="2018-01-01", end="2025-12-31")
        # 第二次调用 load() 会复用缓存(除非传了不同的 start/end)
    """

    def __init__(self, path: Path | str = UNIFIED_CSV) -> None:
        self.path = Path(path)
        self._cache: Optional[pd.DataFrame] = None
        self._cache_key: tuple | None = None

    def _read_full(self) -> pd.DataFrame:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            raise FileNotFoundError(
                f"统一底表不存在: {self.path}\n"
                f"请先运行: python -m scripts.cli update --start 2026-01-01"
            )
        logger.info("首次加载统一底表(可能耗时数秒): %s", self.path)
        df = pd.read_csv(
            self.path,
            dtype={"股票代码": str, "股票代码_full": str, "名称": str},
        )
        df["日期"] = pd.to_datetime(df["日期"])
        if "NOTICE_DATE" in df.columns:
            df["NOTICE_DATE"] = pd.to_datetime(df["NOTICE_DATE"], errors="coerce")
        self._cache = df
        return df

    def load(
        self,
        start: Optional[str | datetime] = None,
        end: Optional[str | datetime] = None,
    ) -> pd.DataFrame:
        """读取全表(或经 start/end 切片)。

        Args:
            start: 起始日期(包含)。
            end: 结束日期(包含)。

        Returns:
            切片后的 DataFrame,按 [日期, 股票代码] 排序。
        """
        df = self._read_full()
        key = (str(start) if start else None, str(end) if end else None)
        if key == self._cache_key:
            return df
        sliced = df
        if start is not None:
            sliced = sliced[sliced["日期"] >= parse_date(start)]
        if end is not None:
            sliced = sliced[sliced["日期"] <= parse_date(end)]
        sliced = sliced.sort_values(["日期", "股票代码"]).reset_index(drop=True)
        self._cache_key = key
        self._cache = sliced  # 用切片替换缓存(避免大表反复过滤)
        return sliced

    def latest_trade_date(self) -> pd.Timestamp:
        """统一底表里最近的交易日。"""
        return self.load()["日期"].max()

    def get_day_snapshot(self, trade_date: str | datetime) -> pd.DataFrame:
        """取某一日的全市场截面(所有股票当日数据)。"""
        td = parse_date(trade_date)
        df = self.load()
        return df[df["日期"] == td].copy()

    def get_prev_day_snapshot(
        self, trade_date: str | datetime
    ) -> Optional[pd.DataFrame]:
        """取 trade_date 之前最近一个交易日(用于"用前一天数据做选股")。"""
        td = parse_date(trade_date)
        df = self.load()
        days = pd.DatetimeIndex(df["日期"].dropna().unique()).sort_values()
        prev = days[days < td]
        if len(prev) == 0:
            return None
        return df[df["日期"] == prev[-1]].copy()

    def invalidate(self) -> None:
        """清缓存(在外部更新了 CSV 后调用)。"""
        self._cache = None
        self._cache_key = None


# ===== 模块级单例 =====
_default_loader: Optional[DataLoader] = None


def get_default_loader() -> DataLoader:
    global _default_loader
    if _default_loader is None:
        _default_loader = DataLoader()
    return _default_loader


# ===== 顶层便捷函数 =====
def load_unified(
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """读取统一底表(带缓存)。

    Example:
        >>> df = load_unified("2024-01-01", "2024-12-31")
    """
    return get_default_loader().load(start, end)


def load_daily_window(
    start: str, end: str
) -> pd.DataFrame:
    """读取 [start, end] 窗口的日线数据(用于回测)。"""
    return load_unified(start, end)


def load_stock_list() -> pd.DataFrame:
    """读取过滤后的股票代码表(3403 只主板)。"""
    return pd.read_csv(STOCK_LIST_CSV, dtype={"代码": str})
