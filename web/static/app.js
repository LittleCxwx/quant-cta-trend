/* ====================================================================
 * 量化策略前端 - Vanilla JS (无构建工具,无 npm)
 * 与 FastAPI 后端通信,渲染 4 个标签页: 选股 / 回测 / 信号 / 数据
 * ==================================================================== */

(function () {
  "use strict";

  // ===== 工具 =====
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function fmtPct(v) {
    if (v === null || v === undefined || v === "" || isNaN(v)) return "-";
    return (v * 100).toFixed(2) + "%";
  }
  function fmtNum(v, digits = 2) {
    if (v === null || v === undefined || v === "" || isNaN(v)) return "-";
    return Number(v).toFixed(digits);
  }
  function fmtYi(v) {
    if (!v) return "-";
    return (Number(v) / 1e8).toFixed(2);
  }
  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  async function apiGet(path) {
    const r = await fetch(path);
    if (!r.ok) {
      let detail = "请求失败";
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return r.json();
  }
  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let detail = "请求失败";
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return r.json();
  }

  // ===== 标签页切换 =====
  $$(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".tab").forEach(b => b.classList.remove("active"));
      $$(".tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${btn.dataset.tab}`).classList.add("active");
    });
  });

  // ===== 数据状态(头部)=====
  async function loadDataStatus() {
    try {
      const s = await apiGet("/api/data/status");
      const status = s.unified_exists
        ? `数据: ${s.unified_min_date} ~ ${s.unified_max_date} (${(s.unified_rows / 1e6).toFixed(1)}M 行)`
        : "⚠️ 统一底表不存在,请先运行 scripts.cli update";
      $("#data-status").textContent = status;
      $("#data-detail").textContent = JSON.stringify(s, null, 2);
    } catch (e) {
      $("#data-status").textContent = "❌ 后端不可达";
    }
  }
  $("#btn-refresh-status").addEventListener("click", loadDataStatus);

  // ===== 默认日期 =====
  function setDefaultDates() {
    const today = new Date().toISOString().slice(0, 10);
    $$('input[type="date"]').forEach(i => {
      if (!i.value) i.value = today;
    });
  }

  // ===== 1. 选股 =====
  $("#form-select").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const params = new URLSearchParams({
      date: fd.get("date"),
      num: fd.get("num"),
      roe: fd.get("roe"),
      eps: fd.get("eps"),
      include_st: fd.get("include_st") ? "true" : "false",
    });
    const btn = e.target.querySelector("button");
    btn.disabled = true; btn.textContent = "运行中…";
    try {
      const res = await apiGet(`/api/select?${params}`);
      $("#select-meta").textContent = `(${res.picks.length} 只)`;
      const tbody = $("#table-select tbody");
      tbody.innerHTML = res.picks.map((p, i) => `
        <tr>
          <td>${i + 1}</td>
          <td>${escapeHtml(p.股票代码)}</td>
          <td>${escapeHtml(p.名称)}</td>
          <td>${fmtNum(p.收盘)}</td>
          <td>${fmtNum(p.EPSJB)}</td>
          <td>${fmtNum(p.ROEJQ)}</td>
          <td>${fmtYi(p.流通市值)}</td>
          <td>${fmtPct(p.选股权重)}</td>
        </tr>
      `).join("") || '<tr><td colspan="8" style="text-align:center;color:#9ca3af;">无符合条件股票</td></tr>';
    } catch (err) {
      alert("选股失败:" + err.message);
    } finally {
      btn.disabled = false; btn.textContent = "运行选股";
    }
  });

  // ===== 2. 回测 =====
  let backtestChart = null;
  $("#form-backtest").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      start: fd.get("start"),
      end: fd.get("end"),
      num: Number(fd.get("num")),
      cash: Number(fd.get("cash")),
      roe: Number(fd.get("roe")),
      eps: Number(fd.get("eps")),
      c_rate: Number(fd.get("c_rate")) / 10000,  // ‱ → 比例
      t_rate: Number(fd.get("t_rate")) / 1000,   // ‰ → 比例
      include_st: !!fd.get("include_st"),
    };
    const btn = e.target.querySelector("button");
    btn.disabled = true; btn.textContent = "回测中(可能 30 秒)…";
    try {
      const r = await apiPost("/api/backtest", body);
      renderBacktest(r);
    } catch (err) {
      alert("回测失败:" + err.message);
    } finally {
      btn.disabled = false; btn.textContent = "运行回测";
    }
  });

  function renderBacktest(r) {
    // 评价指标
    const m = r.metrics || {};
    const isPos = v => (typeof v === "number" && v > 0);
    const cls = v => isPos(v) ? "positive" : (v < 0 ? "negative" : "");
    $("#metrics").innerHTML = [
      ["累计收益", fmtPct(m.累计收益率), cls(m.累计收益率)],
      ["年化收益", fmtPct(m.年化收益率), cls(m.年化收益率)],
      ["最大回撤", fmtPct(m.最大回撤), "negative"],
      ["夏普比率", fmtNum(m.夏普比率)],
      ["基准收益", fmtPct(m.基准累计收益率), cls(m.基准累计收益率)],
      ["Alpha",    fmtNum(m.alpha), cls(m.alpha)],
      ["Beta",     fmtNum(m.beta)],
      ["期末资产", fmtNum(m.期末总资产, 0)],
    ].map(([label, val, c]) => `
      <div class="metric-card">
        <div class="label">${label}</div>
        <div class="value ${c}">${val}</div>
      </div>
    `).join("");

    // 交易记录
    $("#trades-count").textContent = `(${r.trades.length} 笔)`;
    $("#table-trades tbody").innerHTML = r.trades.slice(-200).map(t => `
      <tr>
        <td>${escapeHtml(t.date)}</td>
        <td class="action-${t.action}">${t.action.toUpperCase()}</td>
        <td>${escapeHtml(t.code)}</td>
        <td>${escapeHtml(t.name || "-")}</td>
        <td>${fmtNum(t.price)}</td>
        <td>${t.shares}</td>
        <td>${fmtNum(t.amount, 0)}</td>
        <td>${fmtNum(t.fee, 0)}</td>
        <td>${fmtNum(t.cash_after, 0)}</td>
      </tr>
    `).join("") || '<tr><td colspan="9" style="text-align:center;color:#9ca3af;">无交易</td></tr>';

    // 图表
    renderChart(r);
  }

  function renderChart(r) {
    const el = $("#chart-backtest");
    if (!backtestChart) backtestChart = echarts.init(el);
    window.addEventListener("resize", () => backtestChart && backtestChart.resize());

    const dates = r.asset_curve.map(a => a.date);
    const assets = r.asset_curve.map(a => a.total_asset);
    const benches = r.asset_curve.map(a => a.bench_value || null);
    const drawdowns = r.asset_curve.map(a => +(a.drawdown * 100).toFixed(2));

    const buyPts = (r.trades || []).filter(t => t.action === "buy").slice(0, 300).map(t => ({
      coord: [t.date, t.price], value: "B",
    }));
    const sellPts = (r.trades || []).filter(t => t.action === "sell").slice(0, 300).map(t => ({
      coord: [t.date, t.price], value: "S",
    }));

    const option = {
      title: { text: "策略资金 & 回撤 vs 沪深300", left: "center", top: 6 },
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      legend: { top: 30, data: ["策略总资产", "沪深300", "回撤(%)"] },
      grid: [
        { left: 60, right: 60, top: 70, height: "55%" },
        { left: 60, right: 60, top: "72%", height: "20%" },
      ],
      xAxis: [
        { type: "category", data: dates, gridIndex: 0, axisLabel: { fontSize: 11 } },
        { type: "category", data: dates, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { name: "资金(元)", gridIndex: 0, scale: true },
        { name: "回撤(%)", gridIndex: 1, scale: true, splitNumber: 4 },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1] },
        { type: "slider", xAxisIndex: [0, 1], height: 18, bottom: 10 },
      ],
      series: [
        {
          name: "策略总资产", type: "line", data: assets, smooth: true,
          lineStyle: { color: "#1f77b4", width: 2 },
          itemStyle: { color: "#1f77b4" },
          markPoint: { data: buyPts, symbol: "triangle", symbolSize: 6, itemStyle: { color: "red" } },
        },
        {
          name: "沪深300", type: "line", data: benches, smooth: true,
          lineStyle: { color: "#ff7f0e", width: 1.5 },
          itemStyle: { color: "#ff7f0e" },
        },
        {
          name: "回撤(%)", type: "line", xAxisIndex: 1, yAxisIndex: 1,
          data: drawdowns,
          lineStyle: { color: "#dc2626", width: 1 },
          areaStyle: { color: "rgba(220,38,38,0.12)" },
          itemStyle: { color: "#dc2626" },
        },
      ],
    };
    backtestChart.setOption(option, true);
  }

  // ===== 3. 交易信号 =====
  $("#form-signals").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const params = new URLSearchParams({
      date: fd.get("date"),
      num: fd.get("num"),
      budget: fd.get("budget"),
    });
    if (fd.get("holdings")) params.set("holdings", fd.get("holdings"));
    const btn = e.target.querySelector("button");
    btn.disabled = true; btn.textContent = "生成中…";
    try {
      const s = await apiGet(`/api/signals?${params}`);
      $("#signal-meta").textContent = `(${s.action_type.toUpperCase()})`;
      $("#signal-summary").textContent = s.summary;
      const renderRows = (arr) => arr.length
        ? arr.map(a => `
          <tr>
            <td>${escapeHtml(a.code)}</td>
            <td>${escapeHtml(a.name || "-")}</td>
            <td>${a.price != null ? fmtNum(a.price) : "-"}</td>
            <td>${a.shares}</td>
            <td>${a.amount ? fmtNum(a.amount, 0) : "-"}</td>
            <td>${escapeHtml(a.reason)}</td>
          </tr>
        `).join("")
        : '<tr><td colspan="6" style="text-align:center;color:#9ca3af;">无</td></tr>';
      $("#table-buy tbody").innerHTML = renderRows(s.buy_list);
      $("#table-sell tbody").innerHTML = renderRows(s.sell_list);
      $("#table-hold tbody").innerHTML = (s.hold_list || []).map(a => `
        <tr>
          <td>${escapeHtml(a.code)}</td>
          <td>${escapeHtml(a.name || "-")}</td>
          <td>${a.price != null ? fmtNum(a.price) : "-"}</td>
          <td>${a.shares}</td>
          <td>${escapeHtml(a.reason)}</td>
        </tr>
      `).join("") || '<tr><td colspan="5" style="text-align:center;color:#9ca3af;">无</td></tr>';
    } catch (err) {
      alert("生成信号失败:" + err.message);
    } finally {
      btn.disabled = false; btn.textContent = "生成信号";
    }
  });

  // ===== 启动 =====
  setDefaultDates();
  loadDataStatus();
})();
