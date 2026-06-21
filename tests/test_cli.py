"""CLI 辅助逻辑测试。"""

from __future__ import annotations

import argparse
import json

import pytest

import scripts.cli as cli
from scripts.strategy.trading_signals import TradeAction, TradingSignals


def test_parse_holdings_normalizes_codes_and_skips_zero():
    assert cli._parse_holdings("1:100,600519:200,000002:0") == {
        "000001": 100,
        "600519": 200,
    }


def test_parse_holdings_rejects_invalid_format():
    with pytest.raises(ValueError, match="holdings 格式错误"):
        cli._parse_holdings("000001=100")


def test_positions_file_round_trip(tmp_path):
    path = tmp_path / "positions.json"

    cli._save_positions(path, {"1": 100, "600519": "200", "000002": 0})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "000001": 100,
        "600519": 200,
    }
    assert cli._load_positions(path) == {"000001": 100, "600519": 200}


def test_position_records_round_trip_with_cost(tmp_path):
    path = tmp_path / "positions.json"

    cli._save_position_records(path, {
        "1": {"shares": 100, "cost_price": 10.0, "name": "A"},
    })

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "000001": {
            "shares": 100,
            "name": "A",
            "cost_price": 10.0,
            "cost_amount": 1000.0,
        }
    }
    assert cli._load_positions(path) == {"000001": 100}
    assert cli._load_position_records(path)["000001"]["cost_price"] == 10.0


def test_apply_signals_to_positions_sells_and_buys():
    sigs = TradingSignals(
        signal_date="2026-06-04",
        weekday=3,
        action_type="buy",
        base_date="2026-06-03",
        sell_list=[
            TradeAction(code="000001", name="A", action="sell", shares=100),
            TradeAction(code="600519", name="B", action="sell", shares=100),
        ],
        buy_list=[
            TradeAction(code="2", name="C", action="buy", shares=200),
            TradeAction(code="000003", name="D", action="buy", shares=0),
        ],
    )

    assert cli._apply_signals_to_positions(
        {"000001": 100, "600519": 300},
        sigs,
    ) == {
        "000002": 200,
        "600519": 200,
    }


def test_apply_signals_to_position_records_tracks_cost_basis():
    sigs = TradingSignals(
        signal_date="2026-06-04",
        weekday=3,
        action_type="buy",
        base_date="2026-06-03",
        buy_list=[
            TradeAction(code="000001", name="A", action="buy", price=12.0, shares=100, amount=1200.0),
        ],
        sell_list=[
            TradeAction(code="600519", name="B", action="sell", price=110.0, shares=100, amount=11000.0),
        ],
    )

    out = cli._apply_signals_to_position_records(
        {
            "000001": {"shares": 100, "cost_price": 10.0, "cost_amount": 1000.0},
            "600519": {"shares": 200, "cost_price": 100.0, "cost_amount": 20000.0},
        },
        sigs,
    )

    assert out["000001"]["shares"] == 200
    assert out["000001"]["cost_price"] == 11.0
    assert out["000001"]["cost_amount"] == 2200.0
    assert out["600519"]["shares"] == 100
    assert out["600519"]["cost_amount"] == 10000.0


def test_sell_pnl_text_reports_profit_and_loss():
    profit = TradeAction(code="000001", name="A", action="sell", price=12.0, shares=100)
    loss = TradeAction(code="000001", name="A", action="sell", price=9.0, shares=100)

    records = {"000001": {"shares": 100, "cost_price": 10.0, "cost_amount": 1000.0}}

    assert "估算盈利 ¥200.00" in cli._sell_pnl_text(profit, records)
    assert "估算亏损 ¥100.00" in cli._sell_pnl_text(loss, records)


def test_cmd_signals_saves_positions_file(tmp_path, monkeypatch, capsys):
    import scripts.strategy

    path = tmp_path / "positions.json"
    called = {}

    def fake_get_signals_for_date(date, select_stock_num, budget, held_positions):
        called["date"] = date
        called["select_stock_num"] = select_stock_num
        called["budget"] = budget
        called["held_positions"] = held_positions
        return TradingSignals(
            signal_date=date,
            weekday=3,
            action_type="buy",
            base_date="2026-06-03",
            buy_list=[
                TradeAction(code="1", name="A", action="buy", price=10.0, shares=100, amount=1000.0),
            ],
            summary="ok",
        )

    monkeypatch.setattr(scripts.strategy, "get_signals_for_date", fake_get_signals_for_date)
    args = argparse.Namespace(
        date="2026-06-04",
        num=5,
        budget=100_000.0,
        holdings=None,
        positions_file=str(path),
        save_positions=True,
        format="json",
    )

    assert cli._cmd_signals(args) == 0

    assert called == {
        "date": "2026-06-04",
        "select_stock_num": 5,
        "budget": 100_000.0,
        "held_positions": None,
    }
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "000001": {
            "shares": 100,
            "name": "A",
            "cost_price": 10.0,
            "cost_amount": 1000.0,
        }
    }
    assert json.loads(capsys.readouterr().out)["action_type"] == "buy"


def test_cmd_signals_loads_positions_file(tmp_path, monkeypatch):
    import scripts.strategy

    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"000001": 100}), encoding="utf-8")
    called = {}

    def fake_get_signals_for_date(date, select_stock_num, budget, held_positions):
        called["held_positions"] = held_positions
        return TradingSignals(
            signal_date=date,
            weekday=2,
            action_type="sell",
            base_date=date,
            sell_list=[
                TradeAction(code="000001", name="A", action="sell", shares=100),
            ],
            summary="ok",
        )

    monkeypatch.setattr(scripts.strategy, "get_signals_for_date", fake_get_signals_for_date)
    args = argparse.Namespace(
        date="2026-06-10",
        num=5,
        budget=100_000.0,
        holdings=None,
        positions_file=str(path),
        save_positions=False,
        format="text",
    )

    assert cli._cmd_signals(args) == 0
    assert called["held_positions"] == {"000001": 100}


def test_cmd_signals_prints_sell_pnl_from_positions_file(tmp_path, monkeypatch, capsys):
    import scripts.strategy

    path = tmp_path / "positions.json"
    path.write_text(
        json.dumps({"000001": {"shares": 100, "cost_price": 10.0, "cost_amount": 1000.0}}),
        encoding="utf-8",
    )

    def fake_get_signals_for_date(date, select_stock_num, budget, held_positions):
        return TradingSignals(
            signal_date=date,
            weekday=2,
            action_type="sell",
            base_date=date,
            sell_list=[
                TradeAction(code="000001", name="A", action="sell", price=12.0, shares=100),
            ],
            summary="ok",
        )

    monkeypatch.setattr(scripts.strategy, "get_signals_for_date", fake_get_signals_for_date)
    args = argparse.Namespace(
        date="2026-06-10",
        num=5,
        budget=100_000.0,
        holdings=None,
        positions_file=str(path),
        save_positions=False,
        format="text",
    )

    assert cli._cmd_signals(args) == 0
    assert "估算盈利 ¥200.00" in capsys.readouterr().out


def test_cmd_signals_save_positions_reads_default_file(tmp_path, monkeypatch, capsys):
    import scripts.strategy

    path = tmp_path / "positions.json"
    path.write_text(
        json.dumps({"000001": {"shares": 100, "cost_price": 10.0, "cost_amount": 1000.0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_POSITIONS_FILE", path)

    def fake_get_signals_for_date(date, select_stock_num, budget, held_positions):
        assert held_positions == {"000001": 100}
        return TradingSignals(
            signal_date=date,
            weekday=2,
            action_type="sell",
            base_date=date,
            sell_list=[
                TradeAction(code="000001", name="A", action="sell", price=9.0, shares=100),
            ],
            summary="ok",
        )

    monkeypatch.setattr(scripts.strategy, "get_signals_for_date", fake_get_signals_for_date)
    args = argparse.Namespace(
        date="2026-06-10",
        num=5,
        budget=100_000.0,
        holdings=None,
        positions_file=None,
        save_positions=True,
        format="text",
    )

    assert cli._cmd_signals(args) == 0
    assert "估算亏损 ¥100.00" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8")) == {}
