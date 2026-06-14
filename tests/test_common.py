"""common 工具的单元测试。"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from scripts.common import (
    EXCLUDED_PREFIXES,
    add_market_suffix,
    is_excluded,
    normalize_code,
    parse_date,
    retry,
)


# ===== normalize_code =====
def test_normalize_code_pads_zeros():
    assert normalize_code(1) == "000001"
    assert normalize_code("1") == "000001"
    assert normalize_code("000001") == "000001"
    assert normalize_code("  000001  ") == "000001"


# ===== add_market_suffix =====
@pytest.mark.parametrize("code,suffix", [
    ("000001", "SZ"),
    ("002500", "SZ"),
    ("300001", "SZ"),
    ("600000", "SH"),
    ("688981", "SH"),
    ("830xxx", "BJ"),
    ("920xxx", "BJ"),
])
def test_add_market_suffix(code, suffix):
    assert add_market_suffix(code) == f"{code}.{suffix}"


# ===== is_excluded =====
@pytest.mark.parametrize("code,excluded", [
    ("300750", True),    # 创业板
    ("301456", True),    # 创业板
    ("688981", True),    # 科创板
    ("689009", True),    # 科创板
    ("830xxx", True),    # 北交所
    ("920xxx", True),    # 北交所
    ("43xxxx", True),    # 北交所(老)
    ("000001", False),   # 深主板
    ("002500", False),   # 深主板
    ("600519", False),   # 沪主板
])
def test_is_excluded(code, excluded):
    assert is_excluded(code) is excluded


# ===== parse_date =====
def test_parse_date_normalize():
    d = parse_date("2025-12-25")
    assert isinstance(d, pd.Timestamp)
    assert d.hour == 0 and d.minute == 0
    assert str(d.date()) == "2025-12-25"


def test_parse_date_from_timestamp():
    d = parse_date(pd.Timestamp("2025-12-25 15:30:00"))
    assert str(d.date()) == "2025-12-25"


# ===== retry =====
def test_retry_success_first_try():
    calls = {"n": 0}

    @retry(max_attempts=3, initial_delay=0.01)
    def good():
        calls["n"] += 1
        return 42

    assert good() == 42
    assert calls["n"] == 1


def test_retry_eventually_succeeds():
    calls = {"n": 0}

    @retry(max_attempts=3, initial_delay=0.01, backoff=1.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("not yet")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_exhausted_raises():
    @retry(max_attempts=2, initial_delay=0.01, backoff=1.0,
           exceptions=(ValueError,))
    def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        always_fail()
