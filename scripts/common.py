"""通用工具：路径、日志、断点续传、重试装饰器。

所有脚本共享这个模块，避免重复实现。
"""

from __future__ import annotations

import functools
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, TypeVar

import pandas as pd

# ===== 路径常量(项目根目录)=====
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
STOCK_LIST_CSV = DATA_DIR / "stock_zh_a_spot_em_filtered.csv"
STOCK_LIST_SUFFIX_CSV = DATA_DIR / "stock_zh_a_spot_em_filtered_with_suffix.csv"
DAILY_DIR = DATA_DIR / "stock_daily_data"
ALL_DAILY_CSV = DATA_DIR / "all_stocks_daily.csv"
UNIFIED_CSV = DATA_DIR / "A股_日行情_年报_流通市值.csv"
PROGRESS_DIR = DATA_DIR / ".progress"

# ===== 日志 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scripts")


# ===== 断点续传 =====
class ProgressTracker:
    """轻量级断点续传：把"已完成集合"持久化到 JSON。

    Example:
        tracker = ProgressTracker("daily_fetched")
        for code in codes:
            if tracker.has(code):
                continue
            # ... 干活 ...
            tracker.add(code)
    """

    def __init__(self, name: str, persist_dir: Path | None = None) -> None:
        self.name = name
        self.persist_dir = persist_dir or PROGRESS_DIR
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.persist_dir / f".{name}.json"
        self._done: set[str] = set(self._load())

    def _load(self) -> Iterable[str]:
        if self.path.exists():
            try:
                return set(json.loads(self.path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                logger.warning("进度文件损坏,从头开始: %s", self.path)
        return set()

    def _flush(self) -> None:
        self.path.write_text(
            json.dumps(sorted(self._done), ensure_ascii=False, indent=0),
            encoding="utf-8",
        )

    def has(self, key: str) -> bool:
        return key in self._done

    def add(self, key: str) -> None:
        self._done.add(key)
        self._flush()

    def discard(self, key: str) -> None:
        self._done.discard(key)
        self._flush()

    def reset(self) -> None:
        self._done.clear()
        if self.path.exists():
            self.path.unlink()

    def __len__(self) -> int:
        return len(self._done)


# ===== 重试装饰器 =====
T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """指数退避重试装饰器。

    Args:
        max_attempts: 最大尝试次数(含首次)。
        initial_delay: 首次重试前的等待秒数。
        backoff: 每次重试间隔的乘数。
        exceptions: 触发重试的异常类型。

    Example:
        @retry(max_attempts=5, initial_delay=2.0)
        def call_akshare(...):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    logger.warning(
                        "%s 第 %d/%d 次失败: %s, %.1fs 后重试",
                        func.__name__, attempt, max_attempts, e, delay,
                    )
                    time.sleep(delay)
                    delay *= backoff
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


# ===== 日期工具 =====
def parse_date(s: str | datetime | pd.Timestamp) -> pd.Timestamp:
    """统一解析日期字符串/对象为 pd.Timestamp(归零到午夜)。"""
    ts = pd.Timestamp(s)
    return ts.normalize()


def daterange(start: str, end: str) -> list[pd.Timestamp]:
    """返回 [start, end] 闭区间内所有自然日。"""
    s, e = parse_date(start), parse_date(end)
    return list(pd.date_range(s, e, freq="D"))


def trading_days_between(start: str, end: str) -> list[pd.Timestamp]:
    """返回 [start, end] 内的所有 A 股交易日。

    简化做法：用 ak.tool_trade_date_hist_sina() 拉交易日历,缓存到内存。
    """
    import akshare as ak
    s, e = parse_date(start), parse_date(end)
    cal = ak.tool_trade_date_hist_sina()
    cal["trade_date"] = pd.to_datetime(cal["trade_date"])
    return cal[(cal["trade_date"] >= s) & (cal["trade_date"] <= e)]["trade_date"].tolist()


# ===== 股票代码规范化 =====
def normalize_code(code: str | int) -> str:
    """把任意形式的股票代码规范成 6 位字符串(保留前导 0)。"""
    return str(code).strip().zfill(6)


def add_market_suffix(code: str) -> str:
    """按代码前缀加 .SZ / .SH / .BJ 后缀。"""
    code = normalize_code(code)
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("8", "9")):
        return f"{code}.BJ"
    return code


# ===== 板块过滤(全项目唯一来源)=====
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "300", "301",   # 创业板
    "688", "689",   # 科创板
    "8",             # 北交所(83/87)
    "92",            # 北交所(92)
    "43",            # 北交所(43,历史遗留)
)


def is_excluded(code: str) -> bool:
    """是否属于本策略剔除的板块(创业板/科创板/北交所)。"""
    code = normalize_code(code)
    return code.startswith(EXCLUDED_PREFIXES)
