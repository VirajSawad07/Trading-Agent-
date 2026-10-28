/**
 * AURA QUANT — Live MT5 AI Quantitative Trading Desk
 * Frontend Controller & Real-Time Canvas Chart Engine
 */

// Application State
const state = {
  currentMode: 'micro_200',
  connected: false,
  account: null,
  market: {},
  openPositions: [],
  history: [],
  deliberation: null,
  chartBars: [],
  lastPrices: {},
  pollInterval: null,
};

// DOM Cache
const dom = {
  statusPill: document.getElementById('connection-status'),
  statusLabel: document.getElementById('status-label'),
  btnMode200: document.getElementById('btn-mode-200'),
  btnModeStd: document.getElementById('btn-mode-std'),

  // Tickers
  tickXau: document.getElementById('tick-xau'),
  spreadXau: document.getElementById('spread-xau'),
  tickBtc: document.getElementById('tick-btc'),
  tickEur: document.getElementById('tick-eur'),
  tickGbp: document.getElementById('tick-gbp'),

  // KPIs
  kpiBalance: document.getElementById('kpi-balance'),
  kpiBalanceSub: document.getElementById('kpi-balance-sub'),
  kpiEquity: document.getElementById('kpi-equity'),
  kpiEquitySub: document.getElementById('kpi-equity-sub'),
  kpiFloating: document.getElementById('kpi-floating'),
  kpiFloatingSub: document.getElementById('kpi-floating-sub'),
  kpiWinrate: document.getElementById('kpi-winrate'),
  kpiRatio: document.getElementById('kpi-ratio'),

  // Agent Council
  aiModelTag: document.getElementById('ai-model-tag'),
  regimeStatus: document.getElementById('regime-status'),
  regimeAdx: document.getElementById('regime-adx'),
  regimeBar: document.getElementById('regime-bar'),
  regimeDetail: document.getElementById('regime-detail'),

  quantStatus: document.getElementById('quant-status'),
  quantEv: document.getElementById('quant-ev'),
  quantBar: document.getElementById('quant-bar'),
  quantDetail: document.getElementById('quant-detail'),

  macroStatus: document.getElementById('macro-status'),
  macroLockout: document.getElementById('macro-lockout'),
  macroBar: document.getElementById('macro-bar'),
  macroDetail: document.getElementById('macro-detail'),

  consensusAction: document.getElementById('consensus-action'),
  consensusTitle: document.getElementById('consensus-title'),
  consensusSub: document.getElementById('consensus-sub'),
  consensusScore: document.getElementById('consensus-score'),

  // Chart Header
  goldLivePrice: document.getElementById('gold-live-price'),
  goldLiveChange: document.getElementById('gold-live-change'),
  activeRiskTag: document.getElementById('active-risk-tag'),
  canvas: document.getElementById('trading-chart'),

  // Tables
  openCount: document.getElementById('open-count'),
  positionsTbody: document.getElementById('positions-tbody'),
  historyTotal: document.getElementById('history-total'),
  historyTbody: document.getElementById('history-tbody'),

  terminalFeed: document.getElementById('terminal-feed'),
  toast: document.getElementById('toast'),
};

// Format currency
function formatUSD(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return '$0.00';
  const prefix = val < 0 ? '-$' : '$';
  return prefix + Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function showToast(message, type = 'success') {
  if (!dom.toast) return;
  dom.toast.textContent = message;
  dom.toast.className = `toast show ${type === 'danger' ? 'toast-danger' : 'toast-success'}`;
  setTimeout(() => {
    dom.toast.className = 'toast';
  }, 3500);
}

// -----------------------------------------------------------------------------
// API Services
// -----------------------------------------------------------------------------

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error('Status fetch failed');
    const data = await res.json();
    state.connected = data.connected;
    state.account = data;
    renderStatus();
    renderPositions(data.open_positions || []);
  } catch (err) {
    console.warn('Status poll error:', err);
    state.connected = false;
    renderStatus();
  }
}

async function fetchMarket() {
  try {
    const res = await fetch('/api/market');
    if (!res.ok) throw new Error('Market fetch failed');
    const data = await res.json();
    state.market = data.symbols || {};
    renderMarket();
  } catch (err) {
    console.warn('Market poll error:', err);
  }
}

async function fetchHistory() {
  try {
    const res = await fetch('/api/history');
    if (!res.ok) throw new Error('History fetch failed');
    const data = await res.json();
    state.history = data.deals || [];
    renderHistory(data);
  } catch (err) {
    console.warn('History poll error:', err);
  }
}

async function fetchDeliberation() {
  try {
    const res = await fetch('/api/agent-deliberation');
    if (!res.ok) throw new Error('Deliberation fetch failed');
    const data = await res.json();
    state.deliberation = data;
    renderDeliberation();
  } catch (err) {
    console.warn('Deliberation poll error:', err);
  }
}

async function fetchChartData() {
  try {
    const res = await fetch('/api/chart-data?symbol=XAUUSD&count=42');
    if (!res.ok) throw new Error('Chart fetch failed');
    const data = await res.json();
    if (data.bars && data.bars.length > 0) {
      state.chartBars = data.bars;
      drawCandlestickChart();
    }
  } catch (err) {
    console.warn('Chart poll error:', err);
  }
}

async function fetchBotLogs() {
  try {
    const res = await fetch('/api/bot-logs');
    if (!res.ok) return;
    const data = await res.json();
    renderBotLogs(data);
  } catch (err) {
    console.warn('Bot logs error:', err);
  }
}

// -----------------------------------------------------------------------------
// Renderers
// -----------------------------------------------------------------------------

function renderStatus() {
  const acc = state.account;
  if (!acc) return;

  // Connection Pill
  if (state.connected) {
    dom.statusPill.className = 'status-pill online';
    dom.statusLabel.textContent = `MT5 CONNECTED (#${acc.login || 'DEMO'})`;
  } else {
    dom.statusPill.className = 'status-pill offline';
    dom.statusLabel.textContent = 'MT5 RECONNECTING...';
  }

  // KPIs
  if (acc.balance !== undefined) {
    dom.kpiBalance.textContent = formatUSD(acc.balance);
    const gain = acc.balance - 100000.0;
    if (gain >= 0) {
      dom.kpiBalanceSub.textContent = `+${formatUSD(gain)} Realized Gain`;
      dom.kpiBalanceSub.className = 'kpi-sub positive';
    } else {
      dom.kpiBalanceSub.textContent = `${formatUSD(gain)} Drawdown`;
      dom.kpiBalanceSub.className = 'kpi-sub negative';
    }
  }

  if (acc.equity !== undefined) {
    dom.kpiEquity.textContent = formatUSD(acc.equity);
    const growth = ((acc.equity - 100000.0) / 100000.0) * 100;
    dom.kpiEquitySub.textContent = `${growth >= 0 ? '+' : ''}${growth.toFixed(2)}% Net Growth`;
    dom.kpiEquitySub.className = `kpi-sub ${growth >= 0 ? 'positive' : 'negative'}`;
  }

  if (acc.floating_pnl !== undefined) {
    const fl = acc.floating_pnl;
    dom.kpiFloating.textContent = `${fl >= 0 ? '+' : ''}${formatUSD(fl)}`;
    dom.kpiFloating.className = `kpi-value ${fl >= 0 ? 'positive' : 'negative'}`;
    const openCount = acc.open_positions ? acc.open_positions.length : 0;
    dom.kpiFloatingSub.textContent = `${openCount} Active Position${openCount === 1 ? '' : 's'} Open`;
  }
}

function renderMarket() {
  const syms = state.market;

  // Gold
  const gold = syms['XAUUSD'] || syms['XAUUSDs'];
  if (gold) {
    const priceStr = `$${gold.bid.toFixed(2)}`;
    dom.tickXau.textContent = priceStr;
    dom.spreadXau.textContent = `${gold.spread_points} pts`;
    dom.goldLivePrice.textContent = priceStr;

    // Price change calculation
    if (state.lastPrices['XAUUSD']) {
      const diff = gold.bid - state.lastPrices['XAUUSD'];
      const pct = (diff / state.lastPrices['XAUUSD']) * 100;
      if (pct !== 0) {
        dom.goldLiveChange.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
        dom.goldLiveChange.className = `price-change ${pct >= 0 ? 'positive' : 'negative'}`;
      }
    }
    state.lastPrices['XAUUSD'] = gold.bid;
  }

  // BTC
  const btc = syms['BTCUSD'] || syms['BTCUSDs'];
  if (btc) dom.tickBtc.textContent = `$${btc.bid.toFixed(1)}`;

  // EURUSD
  const eur = syms['EURUSD'];
  if (eur) dom.tickEur.textContent = eur.bid.toFixed(5);

  // GBPUSD
  const gbp = syms['GBPUSD'];
  if (gbp) dom.tickGbp.textContent = gbp.bid.toFixed(5);
}

function renderDeliberation() {
  const d = state.deliberation;
  if (!d) return;

  // AI model tag
  if (d.macro_agent && d.macro_agent.model) {
    dom.aiModelTag.textContent = `${d.macro_agent.model.toUpperCase()} ACTIVE`;
  }

  // Regime Agent
  if (d.regime_agent) {
    dom.regimeStatus.textContent = d.regime_agent.regime.replace('_', ' ');
    dom.regimeAdx.textContent = d.regime_agent.adx;
    dom.regimeBar.style.width = `${Math.min(100, Math.round(d.regime_agent.confidence * 100))}%`;
    dom.regimeDetail.textContent = d.regime_agent.detail || 'Trend alignment verified.';
  }

  // Quant Agent
  if (d.quant_agent) {
    const domPct = Math.round(d.quant_agent.dominance * 100);
    dom.quantStatus.textContent = `${d.quant_agent.action} (${domPct}% DOM)`;
    dom.quantEv.textContent = d.quant_agent.ev;
    dom.quantBar.style.width = `${domPct}%`;
    dom.quantDetail.textContent = d.quant_agent.detail || 'Alpha features positive EV.';
  }

  // Macro Agent
  if (d.macro_agent) {
    dom.macroStatus.textContent = d.macro_agent.bias;
    dom.macroLockout.textContent = d.macro_agent.veto ? 'LOCKOUT VETO' : 'CLEAR (NO VETO)';
    dom.macroLockout.className = `val ${d.macro_agent.veto ? 'negative' : 'safe'}`;
    dom.macroDetail.textContent = d.macro_agent.detail || 'Macro tailwinds active.';
  }

  // Consensus
  if (d.consensus) {
    dom.consensusAction.textContent = `${d.consensus.action} CONSENSUS`;
    dom.consensusAction.className = `consensus-badge ${d.consensus.action.toLowerCase() === 'buy' ? 'buy' : 'sell'}`;
    dom.consensusTitle.textContent = d.consensus.title || 'Signal Execution Approved';
    dom.consensusSub.textContent = `Confidence: ${Math.round(d.consensus.score * 100)}% • ${d.consensus.risk_rule}`;
    dom.consensusScore.textContent = d.consensus.score.toFixed(2);
  }
}

function renderPositions(positions) {
  dom.openCount.textContent = positions.length;

  if (positions.length === 0) {
    dom.positionsTbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty-state">No open positions. AI agents scanning for high EV pullback setups...</td>
      </tr>
    `;
    return;
  }

  let html = '';
  positions.forEach(p => {
    const pnlClass = p.profit >= 0 ? 'profit-pos' : 'profit-neg';
    const tagClass = p.type === 'BUY' ? 'tag-buy' : 'tag-sell';
    html += `
      <tr>
        <td>#${p.ticket}</td>
        <td><strong>${p.symbol}</strong></td>
        <td><span class="${tagClass}">${p.type}</span></td>
        <td>${p.lots.toFixed(2)}</td>
        <td>$${p.open_price.toFixed(2)}</td>
        <td>$${p.current_price.toFixed(2)}</td>
        <td>${p.sl ? `$${p.sl.toFixed(2)}` : '<span style="color:var(--text-muted)">None</span>'}</td>
        <td>${p.tp ? `$${p.tp.toFixed(2)}` : '<span style="color:var(--text-muted)">None</span>'}</td>
        <td class="${pnlClass}">${p.profit >= 0 ? '+' : ''}$${p.profit.toFixed(2)}</td>
      </tr>
    `;
  });
  dom.positionsTbody.innerHTML = html;
}

function renderHistory(data) {
  const deals = data.deals || [];
  const totalProfit = data.total_realized_profit || 0;

  dom.historyTotal.textContent = `${totalProfit >= 0 ? '+' : ''}${formatUSD(totalProfit)}`;
  dom.historyTotal.className = `badge ${totalProfit >= 0 ? 'profit-badge' : 'demo-badge'}`;

  // Update Win Rate KPI
  if (deals.length > 0) {
    const wins = deals.filter(d => d.profit > 0).length;
    const wr = ((wins / deals.length) * 100).toFixed(1);
    dom.kpiWinrate.textContent = `${wr}%`;
  }

  if (deals.length === 0) {
    dom.historyTbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-state">No closed deals in the last 7 days.</td>
      </tr>
    `;
    return;
  }

  let html = '';
  deals.forEach(d => {
    const pnlClass = d.profit >= 0 ? 'profit-pos' : 'profit-neg';
    const tagClass = d.type === 'BUY' ? 'tag-buy' : 'tag-sell';
    html += `
      <tr>
        <td style="color:var(--text-muted); font-size:0.75rem">${d.time}</td>
        <td>#${d.ticket}</td>
        <td><strong>${d.symbol}</strong></td>
        <td>${d.volume.toFixed(2)}</td>
        <td>$${d.price.toFixed(2)}</td>
        <td class="${pnlClass}">${d.profit >= 0 ? '+' : ''}$${d.profit.toFixed(2)}</td>
        <td style="color:var(--text-secondary); font-size:0.72rem">${d.comment}</td>
      </tr>
    `;
  });
  dom.historyTbody.innerHTML = html;
}

function renderBotLogs(data) {
  if (!dom.terminalFeed) return;
  const lines = data.lines || [];
  if (lines.length === 0) return;

  let html = '';
  lines.forEach(line => {
    let cls = 'terminal-line';
    if (line.includes('BUY') || line.includes('FILLED')) cls += ' buy-line';
    else if (line.includes('SELL')) cls += ' sell-line';
    else if (line.includes('RISK') || line.includes('BLOCKED')) cls += ' risk-line';
    else if (line.includes('======') || line.includes('Audit')) cls += ' audit-line';
    html += `<div class="${cls}">${escapeHtml(line)}</div>`;
  });
  dom.terminalFeed.innerHTML = html;
  dom.terminalFeed.scrollTop = dom.terminalFeed.scrollHeight;
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
}

// -----------------------------------------------------------------------------
// Interactive Candlestick Chart (Canvas Engine)
// -----------------------------------------------------------------------------

function drawCandlestickChart() {
  const canvas = dom.canvas;
  if (!canvas || state.chartBars.length === 0) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();

  // Set internal resolution
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;

  // Clear canvas
  ctx.clearRect(0, 0, w, h);

  const bars = state.chartBars;
  const count = bars.length;

  // Find min and max price
  let minPrice = Infinity;
  let maxPrice = -Infinity;
  bars.forEach(b => {
    if (b.low < minPrice) minPrice = b.low;
    if (b.high > maxPrice) maxPrice = b.high;
  });

  // Add padding
  const paddingY = (maxPrice - minPrice) * 0.1 || 1.0;
  minPrice -= paddingY;
  maxPrice += paddingY;
  const priceRange = maxPrice - minPrice;

  // Chart layout dimensions
  const chartRight = w - 65; // Price scale gutter
  const chartBottom = h - 24; // Time scale gutter
  const chartTop = 10;
  const chartLeft = 10;
  const chartW = chartRight - chartLeft;
  const chartH = chartBottom - chartTop;

  // Coordinate transforms
  function getY(price) {
    return chartBottom - ((price - minPrice) / priceRange) * chartH;
  }

  // Draw Subtle Grid Lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.lineWidth = 1;
  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i++) {
    const p = minPrice + (priceRange / gridSteps) * i;
    const y = getY(p);
    ctx.beginPath();
    ctx.moveTo(chartLeft, y);
    ctx.lineTo(chartRight, y);
    ctx.stroke();

    // Price label
    ctx.fillStyle = '#64748b';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`$${p.toFixed(1)}`, chartRight + 6, y + 3);
  }

  // Bar spacing & width
  const barSpacing = chartW / count;
  const candleW = Math.max(3, barSpacing * 0.65);

  // Draw Candlesticks
  bars.forEach((b, i) => {
    const x = chartLeft + i * barSpacing + barSpacing / 2;
    const yOpen = getY(b.open);
    const yClose = getY(b.close);
    const yHigh = getY(b.high);
    const yLow = getY(b.low);

    const isBull = b.close >= b.open;
    const color = isBull ? '#10b981' : '#f43f5e';

    // Wick
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x, yHigh);
    ctx.lineTo(x, yLow);
    ctx.stroke();

    // Body
    ctx.fillStyle = color;
    const bodyTop = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(2, Math.abs(yClose - yOpen));
    ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyHeight);

    // Time label on selected bars
    if (i % 8 === 0 || i === count - 1) {
      ctx.fillStyle = '#64748b';
      ctx.font = '9px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(b.time, x, chartBottom + 16);
    }
  });

  // Calculate & Draw EMA20 Line
  if (bars.length >= 10) {
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    const period = 10;
    const k = 2 / (period + 1);
    let ema = bars[0].close;

    bars.forEach((b, i) => {
      ema = b.close * k + ema * (1 - k);
      const x = chartLeft + i * barSpacing + barSpacing / 2;
      const y = getY(ema);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // Draw Current Live Price Dotted Line
  const lastBar = bars[bars.length - 1];
  const lastPrice = lastBar.close;
  const lastY = getY(lastPrice);

  ctx.strokeStyle = 'rgba(245, 158, 11, 0.8)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(chartLeft, lastY);
  ctx.lineTo(chartRight, lastY);
  ctx.stroke();
  ctx.setLineDash([]); // Reset line dash

  // Live Price Badge on Axis
  ctx.fillStyle = '#f59e0b';
  ctx.fillRect(chartRight + 2, lastY - 8, 60, 16);
  ctx.fillStyle = '#000';
  ctx.font = 'bold 9px JetBrains Mono, monospace';
  ctx.textAlign = 'left';
  ctx.fillText(`$${lastPrice.toFixed(2)}`, chartRight + 5, lastY + 3);
}

// -----------------------------------------------------------------------------
// User Interactive Controls
// -----------------------------------------------------------------------------

async function toggleMode(mode) {
  state.currentMode = mode;

  if (mode === 'micro_200') {
    dom.btnMode200.className = 'mode-btn active';
    dom.btnModeStd.className = 'mode-btn';
    dom.activeRiskTag.textContent = '0.01 Lots ($5 Max Risk • 1:3 Target)';
    showToast('Switched to $200 Micro Mode (Strict 0.01 Lots)');
  } else {
    dom.btnMode200.className = 'mode-btn';
    dom.btnModeStd.className = 'mode-btn active';
    dom.activeRiskTag.textContent = '0.05 Lots (Standard Pro Mode)';
    showToast('Switched to Standard Pro Mode (0.05 Lots)');
  }

  try {
    await fetch('/api/toggle-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    fetchDeliberation();
  } catch (err) {
    console.error('Mode toggle failed:', err);
  }
}

async function triggerKillSwitch() {
  const confirmed = confirm(
    'EMERGENCY LIQUIDATION CONFIRMATION:\n\nAre you sure you want to immediately close ALL active MT5 open positions at market price?'
  );

  if (!confirmed) return;

  try {
    showToast('Executing Emergency Liquidation...', 'danger');
    const res = await fetch('/api/kill-switch', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('All positions liquidated successfully!', 'success');
      fetchStatus();
      fetchHistory();
    } else {
      showToast('Liquidation warning: ' + data.message, 'danger');
    }
  } catch (err) {
    showToast('Kill-switch failed: ' + err.message, 'danger');
  }
}

// Make functions globally available for HTML onclick attributes
window.toggleMode = toggleMode;
window.triggerKillSwitch = triggerKillSwitch;

// Resize canvas automatically on window resize
window.addEventListener('resize', () => {
  drawCandlestickChart();
});

// -----------------------------------------------------------------------------
// Application Lifecycle
// -----------------------------------------------------------------------------

async function init() {
  console.log('[AuraQuant] Initializing Live MT5 AI Trading Desk...');

  // Immediate first load
  await fetchStatus();
  await fetchMarket();
  await fetchDeliberation();
  await fetchHistory();
  await fetchChartData();
  await fetchBotLogs();

  // 2000ms periodic polling loop
  state.pollInterval = setInterval(async () => {
    await fetchStatus();
    await fetchMarket();
    await fetchChartData();
    await fetchBotLogs();
  }, 2000);

  // 5000ms slower polling for history & macro deliberation
  setInterval(async () => {
    await fetchDeliberation();
    await fetchHistory();
  }, 5000);
}

document.addEventListener('DOMContentLoaded', init);
