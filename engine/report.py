"""Render the weekly scan JSON (+ optional options picks and backtest summary) into one self-contained HTML page.

  python -m engine.report data/scan_latest.json [--options data/options_latest.json] [--backtest data/bt_report.json] -o report
  → report/index.html, report/data.json, report/charts/*.png. Publish index.html with the other files alongside.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

TEMPLATE = r"""<meta charset="utf-8">
<title>Leader Breakout Watchlist</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: desk sheet — regime strip, ready setups as chart cards, then near-setups and group leadership tables. */
:root {
  --bg: #f4f5f2; --panel: #ffffff; --ink: #16201d; --muted: #5d6b66; --line: #d9dfdb;
  --ema8: #0e9fb3; --ema21: #c2307a; --ema50: #7d8984; --trigger: #d97a06; --undercut: #7a4fc4; --target: #1d8a4e;
  --good: #1d8a4e; --warn: #c27c0e; --bad: #c0392b; --chip: #eef1ee;
  --f-display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --f-body: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f1513; --panel: #161e1b; --ink: #e4ebe7; --muted: #92a19b; --line: #26322d;
  --ema8: #38c6d9; --ema21: #e0559b; --ema50: #8b9893; --trigger: #f0a03a; --undercut: #a17ff0; --target: #43c07a;
  --good: #43c07a; --warn: #e3a33b; --bad: #ef6b5b; --chip: #1e2824; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0f1513; --panel: #161e1b; --ink: #e4ebe7; --muted: #92a19b; --line: #26322d;
  --ema8: #38c6d9; --ema21: #e0559b; --ema50: #8b9893; --trigger: #f0a03a; --undercut: #a17ff0; --target: #43c07a;
  --good: #43c07a; --warn: #e3a33b; --bad: #ef6b5b; --chip: #1e2824; color-scheme: dark }
body { background: var(--bg); color: var(--ink); font-family: var(--f-body); font-size: 15px; line-height: 1.5; }
.wrap { max-width: 1180px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 64px; display: grid; gap: 28px; }
h1, h2, h3 { font-family: var(--f-display); margin: 0; text-wrap: balance; letter-spacing: -0.01em; }
h1 { font-size: clamp(26px, 4vw, 38px); font-weight: 800; }
h2 { font-size: 20px; font-weight: 700; }
.eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
.mono, .num { font-family: var(--f-mono); font-variant-numeric: tabular-nums; }
header { display: grid; gap: 10px; }
.sub { color: var(--muted); max-width: 70ch; margin: 0; }
.regime { display: grid; grid-template-columns: auto 1fr; gap: 16px 24px; align-items: center; background: var(--panel); border: 1px solid var(--line); border-left: 6px solid var(--rc, var(--muted)); border-radius: 6px; padding: 16px 18px; }
.regime .state { font-family: var(--f-display); font-weight: 800; font-size: 22px; color: var(--rc); }
.idx { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.idx div { display: flex; gap: 6px; align-items: baseline; font-size: 13px; }
.pill { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--chip); color: var(--muted); white-space: nowrap; }
.pill.ok { color: var(--good); } .pill.no { color: var(--bad); }
.pill.ok::before { content: "✓"; } .pill.no::before { content: "✕"; }
.section-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.cards { display: grid; grid-template-columns: minmax(0, 1fr); gap: 22px; max-width: 980px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; display: grid; gap: 12px; padding: 16px; min-width: 0; }
.card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.tick { font-family: var(--f-display); font-weight: 800; font-size: 26px; line-height: 1; }
.meta { color: var(--muted); font-size: 13px; }
.chart { min-width: 0; } .chart img { display: block; width: 100%; height: auto; border-radius: 4px; border: 1px solid var(--line); background: #fff; }
.chart a { display: block; }
.levels { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.lv { display: grid; gap: 2px; padding: 8px 10px; background: var(--chip); border-radius: 4px; border-top: 3px solid var(--c, var(--line)); }
.lv b { font-family: var(--f-mono); font-weight: 500; font-size: 15px; }
.lv span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.checks { display: flex; flex-wrap: wrap; gap: 6px; }
.opt { font-size: 13px; border-top: 1px dashed var(--line); padding-top: 10px; color: var(--ink); }
.opt b { font-weight: 600; }
.ticket { display: grid; gap: 8px; border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; background: var(--chip); }
.ticket h3 { font-size: 14px; margin: 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ticket dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 6px 14px; margin: 0; }
.ticket dt { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.ticket dd { margin: 0; font-family: var(--f-mono); font-variant-numeric: tabular-nums; }
.ticket ol { margin: 0; padding-left: 20px; font-size: 13.5px; display: grid; gap: 2px; }
.ticket .note { font-size: 13px; color: var(--muted); }
.pill.warn { color: var(--warn); } .pill.bad { color: var(--bad); }
.empty { background: var(--panel); border: 1px dashed var(--line); border-radius: 6px; padding: 22px; color: var(--muted); }
.tbl { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; }
tr:last-child td { border-bottom: 0; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 18px; }
.bar { display: inline-block; height: 6px; border-radius: 3px; background: var(--ema8); vertical-align: middle; }
.rules { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 14px; }
.rule { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 14px; font-size: 14px; }
.rule h3 { font-size: 15px; margin-bottom: 6px; }
.rule p { margin: 0; color: var(--muted); }
.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--muted); }
.legend i { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-right: 5px; vertical-align: middle; }
.bt { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.bt div { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; display: grid; gap: 2px; }
.bt b { font-family: var(--f-mono); font-size: 18px; font-weight: 500; }
.bt span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
footer { color: var(--muted); font-size: 12.5px; max-width: 90ch; }
@media (max-width: 560px) { .levels { grid-template-columns: repeat(2, minmax(0, 1fr)); } .regime { grid-template-columns: 1fr; } }
</style>

<div class="wrap">
  <header>
    <div class="eyebrow" id="asof"></div>
    <h1>Leader Breakout Watchlist</h1>
    <p class="sub">Growth mode for a cash account under $100k: up to two positions using the whole account, from tight-base breakouts in leading industries and episodic pivots (big gaps on huge volume). Every entry is a buy-stop; the stop is the entry day's low and must sit above the max-stop line, or skip the trade. Idle cash waits in SPY.</p>
  </header>

  <section class="regime" id="regime"></section>

  <section style="display:grid;gap:14px" id="orderswrap">
    <div class="section-head"><h2>This week's orders</h2><span class="meta" id="acctnote"></span></div>
    <div class="tbl"><table id="orders"></table></div>
    <p class="meta" id="plan" style="margin:0"></p>
  </section>

  <section style="display:grid;gap:14px">
    <div class="section-head"><h2>Ready setups</h2>
      <span class="meta">Sorted by quality: RS, tightness, volume dry-up, industry rank</span>
    </div>
    <div class="cards" id="ready"></div>
  </section>

  <section style="display:grid;gap:14px">
    <div class="section-head"><h2>Leaders still forming</h2><span class="meta">Top stocks in leading industries that fail one or more setup checks</span></div>
    <div class="tbl"><table id="near"></table></div>
  </section>

  <section class="two">
    <div style="display:grid;gap:12px"><h2>Sectors</h2><div class="tbl"><table id="sectors"></table></div></div>
    <div style="display:grid;gap:12px"><h2>Industries</h2><div class="tbl"><table id="industries"></table></div></div>
  </section>

  <section id="btwrap" style="display:grid;gap:12px" hidden>
    <div class="section-head"><h2>Backtest of these rules</h2><span class="meta" id="btnote"></span></div>
    <div class="bt" id="bt"></div>
    <div class="chart" id="btchart"></div>
    <div class="tbl"><table id="btvar"></table></div>
  </section>

  <section style="display:grid;gap:12px">
    <h2>Trade plan</h2>
    <div class="rules">
      <div class="rule"><h3>Entry</h3><p>Breakouts: buy-stop just above the base high, valid all week. Episodic pivots: buy-stop above the gap day's high, valid the next day only. Never chase more than 1% above the trigger.</p></div>
      <div class="rule"><h3>Stop and size</h3><p>Low of the entry day. If that low is below the max-stop line at the fill, exit or don't take it. The backtest's worst-case version of this rule loses money, so honour it immediately. Up to 2 positions; the first fill can use the whole account.</p></div>
      <div class="rule"><h3>Trims</h3><p>Sell ¼ at the first target and move the stop to breakeven. Sell ¼ on a close below the 8 EMA, ¼ on a close below the 21 EMA, the rest on a close below the 50 EMA.</p></div>
      <div class="rule"><h3>Market filter and idle cash</h3><p>Risk-on: full size. Caution: half size. Risk-off: no new entries. Cash not in a trade sits in SPY; sell it at the open on days you have a live ticket.</p></div>
    </div>
  </section>

  <footer id="foot"></footer>
</div>

<script>
fetch('data.json', {cache: 'no-store'}).then(r => r.json()).then(render).catch(e => {
  document.getElementById('ready').innerHTML = `<div class="empty">Could not load this week's data (${String(e)}).</div>`;
});
function render(D) {
const S = D.scan, OPT = D.options || {}, BT = D.backtest, IMG = D.charts || {};
const TK = D.tickets || {tickets: []}, TIX = Object.fromEntries((TK.tickets || []).map(t => [t.ticker, t]));
const money = x => x == null ? '–' : '$' + Number(x).toLocaleString('en-US', {maximumFractionDigits: 0});
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const f = (x, d = 2) => x == null || !isFinite(x) ? '–' : Number(x).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
const pct = (x, d = 1) => x == null ? '–' : f(x, d) + '%';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

document.getElementById('asof').textContent = 'Data through ' + S.as_of + ' · for the week ahead';
const rc = ['--bad', '--warn', '--good'][S.regime];
const R = document.getElementById('regime');
R.style.setProperty('--rc', `var(${rc})`);
const stateTxt = ['Risk-off', 'Caution', 'Risk-on'][S.regime];
R.innerHTML = `<div><div class="eyebrow">Market regime</div><div class="state">${stateTxt}</div></div>
  <div style="display:grid;gap:6px;min-width:0"><div>${esc(S.regime_text)}</div><div class="idx">${
  Object.entries(S.index).map(([k, v]) => `<div><b class="mono">${k}</b> <span class="mono">${f(v.close)}</span>
    ${['ema8','ema21','ema50'].map(e => `<span class="pill ${v.close > v[e] ? 'ok' : 'no'}">${e.replace('ema','')}</span>`).join('')}</div>`).join('')}</div></div>`;

const ready = S.candidates.filter(c => c.setup.ready).sort((a, b) => ((a.kind === 'EP') - (b.kind === 'EP')) || (b.score || 0) - (a.score || 0));
const near = S.candidates.filter(c => !c.setup.ready);
const checkNames = {trend: 'Trend', base_length: 'Base ≥5d', depth: 'Depth', prior_move: 'Prior move', tight: 'Tight', volume_dry: 'Volume dry'};

function ticketHtml(t) {
  const flag = t.allowed ? `<span class="pill ok">${esc(t.size_note)}</span>` : `<span class="pill bad">${esc(t.size_note)}</span>`;
  return `<div class="ticket"><h3>Trade ticket ${flag}</h3>
    <dl><div><dt>Order</dt><dd>Buy ${t.shares} sh, stop ${f(t.buy_stop)} limit ${f(t.limit)}</dd></div>
      <div><dt>Cost</dt><dd>${money(t.cost)} (${t.pct_of_account}% of account)</dd></div>
      <div><dt>Worst-case risk</dt><dd>${money(t.risk_at_max_stop)} (${t.risk_pct_of_account}%) at ${f(t.max_stop)}</dd></div>
      <div><dt>First target</dt><dd>${f(t.t1)} · ${f(t.reward_risk, 1)}R</dd></div></dl>
    <div class="note">${esc(t.stop_rule)}.${t.undercut_entry ? ' ' + esc(t.undercut_entry) + '.' : ''}</div>
    <ol>${t.exits.map(e => `<li>Sell ${e.sell} sh when ${esc(e.when)}${e.then ? `, then ${esc(e.then)}` : ''}</li>`).join('')}</ol></div>`;
}
const A = TK.account;
if (A && TK.tickets.length) {
  document.getElementById('acctnote').textContent = `Account ${money(A.equity)} · up to ${A.max_positions} positions · cash only · +${money(A.monthly_deposit)}/month`;
  document.getElementById('plan').textContent = TK.plan + (S.regime === 0 ? ' The market is risk-off, so these are for when it turns; place nothing this week.' : '');
  document.getElementById('orders').innerHTML = `<thead><tr><th>#</th><th>Ticker</th><th class="num">Buy-stop</th><th class="num">Limit</th><th class="num">Shares</th><th class="num">Cost</th><th class="num">Max stop</th><th class="num">Risk</th><th class="num">Target</th><th>Status</th></tr></thead><tbody>${
    TK.tickets.map((t, i) => `<tr><td class="mono">${i + 1}</td><td><b class="mono">${esc(t.ticker)}</b></td><td class="num">${f(t.buy_stop)}</td><td class="num">${f(t.limit)}</td><td class="num">${t.shares}</td><td class="num">${money(t.cost)}</td><td class="num">${f(t.max_stop)}</td><td class="num">${money(t.risk_at_max_stop)}</td><td class="num">${f(t.t1)}</td><td>${t.allowed ? (i < A.max_positions ? '<span class="pill ok">place</span>' : '<span class="pill">backup</span>') : '<span class="pill bad">wait</span>'}</td></tr>`).join('')}</tbody>`;
} else document.getElementById('orderswrap').hidden = true;
const RC = document.getElementById('ready');
if (!ready.length) RC.innerHTML = `<div class="empty">No leader is in a ready base this week. The table below shows which are closest.</div>`;
ready.forEach((c, n) => {
  const s = c.setup, o = OPT[c.ticker];
  const el = document.createElement('article');
  el.className = 'card';
  el.innerHTML = `<div class="card-top"><div style="display:grid;gap:4px"><div class="tick">${esc(c.ticker)}</div>
      <div class="meta">${esc(c.name).slice(0, 48)}</div><div class="meta">${c.kind === 'EP' ? `<span class="pill warn">Episodic pivot · +${f(c.gap_pct, 0)}% gap on ${f(c.vol_x, 0)}× volume (${esc(S.ep_as_of)})</span> ` : ''}${esc(c.industry)}${c.industry_rank_top ? ` · industry #${c.industry_rank_top}` : ''}</div></div>
      <div style="display:grid;gap:4px;justify-items:end">${c.rs_rating != null ? `<span class="pill">RS ${f(c.rs_rating, 0)}</span>` : ''}<span class="pill">ADR ${pct(c.adr)}</span><span class="pill">Close ${f(c.close)}</span></div></div>
    <div class="chart">${IMG[c.ticker] ? `<img loading="lazy" src="${IMG[c.ticker]}" alt="${esc(c.ticker)} daily chart with base, entry trigger, max stop, undercut level and first target">` : ""}</div>
    <div class="levels">
      <div class="lv" style="--c:var(--trigger)"><span>Trigger</span><b>${f(s.trigger)}</b></div>
      <div class="lv" style="--c:var(--bad)"><span>Max stop</span><b>${f(s.max_stop)}</b></div>
      <div class="lv" style="--c:var(--target)"><span>First target</span><b>${f(s.t1)}</b></div>
      <div class="lv" style="--c:var(--undercut)"><span>${c.kind === 'EP' ? 'Gap-day low' : 'Base low'}</span><b>${f(s.undercut)}</b></div>
    </div>
    ${c.kind === 'EP' ? '' : `<div class="meta">Base ${s.base_len} days, ${pct(s.depth)} deep after a ${pct(s.prior_move, 0)} run · last 5 days ${pct(s.tight_pct)} range on ${f(s.dry, 2)}× normal volume · ${f(s.rr_at_max_stop, 1)}R to target if stopped at max · ${f(s.ext_atr, 1)} ATR above 8 EMA</div>`}
    ${TIX[c.ticker] ? ticketHtml(TIX[c.ticker]) : ''}
    ${o ? `<div class="opt"><b>Options alternative:</b> ${esc(o.summary)}</div>` : ''}`;
  RC.appendChild(el);
});

const N = document.getElementById('near');
N.innerHTML = `<thead><tr><th>Ticker</th><th>Industry</th><th class="num">RS</th><th class="num">Close</th><th class="num">Base high</th><th class="num">Depth</th><th>Missing</th></tr></thead><tbody>${
  near.map(c => { const miss = Object.entries(c.setup.checks || {}).filter(([k, v]) => !v).map(([k]) => checkNames[k] || k);
    return `<tr><td><b class="mono">${esc(c.ticker)}</b></td><td>${esc(c.industry)}</td><td class="num">${f(c.rs_rating, 0)}</td><td class="num">${f(c.close)}</td>
    <td class="num">${f(c.setup.trigger)}</td><td class="num">${pct(c.setup.depth)}</td><td><div class="checks">${miss.map(m => `<span class="pill no">${m}</span>`).join('') || '<span class="pill">history too short</span>'}</div></td></tr>`; }).join('')}</tbody>`;

const VNAME = {base: 'Growth mode (what this page trades)', optimistic_entry: 'Optimistic intraday entry', worst_case_entry: 'Worst-case intraday entry', idle_cash_not_spy: 'Idle cash stays cash', idle_qqq: 'Idle cash in QQQ', no_episodic_pivots: 'Breakouts only', with_undercuts: 'Add undercut entries', standard_mode_8x25pct: 'Standard mode (8 × 25%, for $100k+)', close_confirm_entry: 'Enter at close on volume', no_regime_filter: 'No market filter', no_undercut: 'Breakouts only (no undercuts)', t1_3R: 'First target at 3R', sector_gate_top4: 'Gate on top 4 sectors', article_scope_8x3: 'Article scope: 4 sectors, 8 industries × 3', wide_stops_1adr: 'Stops up to 1 ADR', rs_only_no_groups: 'Top RS stocks, no groups', pos_cap_40: 'Position cap 40%'};
const bar = (v, max) => `<span class="bar" style="width:${Math.max(4, 80 * v / max)}px"></span>`;
const SEC = document.getElementById('sectors'), top = new Set(S.top_sectors);
SEC.innerHTML = `<thead><tr><th>#</th><th>Sector</th><th class="num">Members</th><th class="num">Median RS</th><th class="num">Above 50 EMA</th><th>Score</th></tr></thead><tbody>${
  S.sectors.map((r, i) => `<tr><td class="mono">${i + 1}</td><td>${top.has(r.sector) ? '<b>' + esc(r.sector) + '</b>' : esc(r.sector)}</td><td class="num">${r.n}</td><td class="num">${f(r.rs_med, 0)}</td><td class="num">${pct(100 * r.breadth, 0)}</td><td>${bar(r.score, 100)}</td></tr>`).join('')}</tbody>`;
const IND = document.getElementById('industries');
IND.innerHTML = `<thead><tr><th>#</th><th>Industry</th><th class="num">Members</th><th class="num">Median RS</th><th class="num">Above 50</th></tr></thead><tbody>${
  S.industries.map((r, i) => `<tr><td class="mono">${i + 1}</td><td>${esc(r.industry)}<div class="meta">${esc(r.sector)}</div></td><td class="num">${r.n}</td><td class="num">${f(r.rs_med, 0)}</td><td class="num">${pct(100 * r.breadth, 0)}</td></tr>`).join('')}</tbody>`;

if (BT) {
  document.getElementById('btwrap').hidden = false;
  document.getElementById('btnote').textContent = BT.note || '';
  document.getElementById('bt').innerHTML = Object.entries(BT.metrics).map(([k, v]) => `<div><span>${esc(k)}</span><b>${typeof v === 'number' ? f(v, Math.abs(v) >= 100 ? 0 : 2) : esc(v)}</b></div>`).join('');
  if (BT.equity_png) document.getElementById('btchart').innerHTML = `<img loading="lazy" src="${BT.equity_png}" alt="Strategy equity curve against SPY, log scale">`;
  if (BT.variants) document.getElementById('btvar').innerHTML = `<thead><tr><th>Variant</th><th class="num">CAGR</th><th class="num">Max DD</th><th class="num">Sharpe</th><th class="num">Trades</th><th class="num">Profit factor</th></tr></thead><tbody>${
    Object.entries(BT.variants).map(([k, v]) => `<tr><td>${esc(VNAME[k] || k)}</td><td class="num">${pct(v['CAGR %'])}</td><td class="num">${pct(v['Max drawdown %'])}</td><td class="num">${f(v['Sharpe'])}</td><td class="num">${v['Trades']}</td><td class="num">${f(v['Profit factor'])}</td></tr>`).join('')}</tbody>`;
}
document.getElementById('foot').textContent = 'Universe: US common stocks from Nasdaq/NYSE/AMEX listings, grouped by Nasdaq sector and industry. Prices from Yahoo Finance, daily bars. Leaders: top 5 stocks by RS in the top 15 industries, price above 21 and 50 EMA, 10-day volume above 500k, ADR above 2%. This is a rules-based screen, not advice.';
}
</script>
"""


def build(scan: dict, options: dict | None, backtest: dict | None, out_dir: Path, tickets: dict | None = None,
          ep: dict | None = None) -> list[str]:
    """Write index.html + data.json + charts/*.png into out_dir. Returns the published file list (besides index)."""
    from .charts import setup_chart
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "charts").mkdir(exist_ok=True)
    files, charts = [], {}
    if ep and ep.get("candidates"):
        if tickets is None:
            from .tickets import tickets_for
            tickets = tickets_for(scan, ep=ep)
        scan = dict(scan)
        scan["ep_as_of"] = ep["as_of"]
        scan["candidates"] = list(scan["candidates"]) + ep["candidates"]
    for c in scan["candidates"]:
        if c["setup"]["ready"] and c.get("bars"):
            rel = f"charts/{c['ticker']}.png"
            (out_dir / rel).write_bytes(setup_chart(c))
            charts[c["ticker"]] = rel
            files.append(rel)
    for c in scan["candidates"]:
        c.pop("bars", None)
    scan.pop("index_bars", None)
    bt = dict(backtest) if backtest else None
    if bt and bt.get("equity_png"):
        (out_dir / "charts" / "equity.png").write_bytes(base64.b64decode(bt["equity_png"]))
        bt["equity_png"] = "charts/equity.png"
        files.append("charts/equity.png")
    if tickets is None:
        from .tickets import tickets_for
        tickets = tickets_for(scan)
    (out_dir / "data.json").write_text(json.dumps({"scan": scan, "options": options or {}, "backtest": bt,
                                                   "charts": charts, "tickets": tickets}))
    files.append("data.json")
    (out_dir / "index.html").write_text(TEMPLATE)
    return files


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--options")
    ap.add_argument("--backtest")
    ap.add_argument("--ep", default="data/ep_latest.json")
    ap.add_argument("-o", "--out", default="report")
    a = ap.parse_args()
    load = lambda p: json.loads(Path(p).read_text()) if p and Path(p).exists() else None
    files = build(load(a.scan), load(a.options), load(a.backtest), Path(a.out), ep=load(a.ep))
    print(json.dumps({"page": str(Path(a.out) / "index.html"), "files": files}))
