(() => {
  const $ = (id) => document.getElementById(id);
  const fmtUsd = (n, signed = false) => {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    const sign = signed ? (n > 0 ? "+" : n < 0 ? "-" : "") : "";
    const abs = Math.abs(n);
    return sign + "$" + abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtPct = (n, signed = false) => {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    const sign = signed ? (n > 0 ? "+" : n < 0 ? "-" : "") : "";
    return sign + Math.abs(n).toFixed(2) + "%";
  };

  async function load() {
    try {
      const resp = await fetch("trades.json", { cache: "no-cache" });
      if (!resp.ok) throw new Error("trades.json fetch failed: " + resp.status);
      return await resp.json();
    } catch (err) {
      $("status-dot").classList.add("err");
      $("status-text").textContent = "OFFLINE";
      console.error(err);
      throw err;
    }
  }

  function setStatus(summary) {
    $("status-dot").classList.add("ok");
    $("status-text").textContent = "LIVE";
    $("last-updated").textContent = "updated " + new Date(summary.last_updated).toISOString().replace("T", " ").slice(0, 16) + "Z";
  }

  function renderStats(s) {
    $("val-bankroll").textContent = fmtUsd(s.current_bankroll);
    const pnl = s.total_pnl;
    const pnlEl = $("val-pnl");
    pnlEl.textContent = fmtUsd(pnl, true);
    pnlEl.classList.toggle("pos", pnl > 0);
    pnlEl.classList.toggle("neg", pnl < 0);

    const roiEl = $("val-roi");
    roiEl.textContent = fmtPct(s.roi_pct, true);
    roiEl.classList.toggle("pos", s.roi_pct > 0);
    roiEl.classList.toggle("neg", s.roi_pct < 0);
    $("sub-staked").textContent = s.total_staked.toLocaleString();

    $("val-winrate").textContent = fmtPct(s.win_rate_pct);
    $("sub-wl").textContent = `${s.wins}-${s.losses}`;
    $("val-closed").textContent = s.closed_count.toLocaleString();
    $("val-active").textContent = s.active_count.toLocaleString();
  }

  let chart;
  function renderChart(trades) {
    const closed = trades.filter(t => t.status === "closed" && t.bankroll_after !== null);
    const points = closed.map((t, i) => ({
      x: i,
      y: t.bankroll_after,
      date: t.game_date,
      source: t.source,
    }));
    const liveStart = closed.findIndex(t => t.source === "live");

    const ctx = $("chart").getContext("2d");
    if (chart) chart.destroy();
    const gradient = ctx.createLinearGradient(0, 0, 0, 320);
    gradient.addColorStop(0, "rgba(0, 255, 156, 0.25)");
    gradient.addColorStop(1, "rgba(0, 255, 156, 0)");

    chart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [
          {
            label: "Bankroll",
            data: points,
            parsing: false,
            borderColor: "#00ff9c",
            backgroundColor: gradient,
            borderWidth: 1.4,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: "#00ff9c",
            fill: true,
            tension: 0.08,
            segment: {
              borderColor: (c) => (liveStart >= 0 && c.p0.parsed.x >= liveStart ? "#00ff9c" : "#6fa38d"),
              borderWidth: (c) => (liveStart >= 0 && c.p0.parsed.x >= liveStart ? 2 : 1.2),
            },
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500 },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        scales: {
          x: {
            type: "linear",
            ticks: {
              color: "#3d5a4f",
              callback: (v) => {
                const p = points[Math.round(v)];
                return p ? p.date : "";
              },
              maxTicksLimit: 8,
              font: { family: "JetBrains Mono", size: 10 },
            },
            grid: { color: "rgba(27,42,36,0.45)", drawTicks: false },
          },
          y: {
            ticks: {
              color: "#3d5a4f",
              callback: (v) => "$" + v.toLocaleString(),
              font: { family: "JetBrains Mono", size: 10 },
            },
            grid: { color: "rgba(27,42,36,0.45)", drawTicks: false },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#070a09",
            borderColor: "#2a3e36",
            borderWidth: 1,
            titleColor: "#00ff9c",
            bodyColor: "#c7ffe3",
            titleFont: { family: "JetBrains Mono", size: 11 },
            bodyFont: { family: "JetBrains Mono", size: 11 },
            callbacks: {
              title: (items) => {
                const p = points[items[0].parsed.x];
                return p ? `${p.date} · ${p.source}` : "";
              },
              label: (item) => `bankroll: $${item.parsed.y.toFixed(2)}`,
            },
          },
        },
      },
    });
  }

  function renderActive(trades) {
    const tbody = document.querySelector("#active-table tbody");
    const active = trades.filter(t => t.status === "active");
    $("active-count-inline").textContent = `${active.length} open`;
    if (active.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="color:var(--fg-mute); text-align:center; padding:22px;">no active trades — next slate pending</td></tr>`;
      return;
    }
    tbody.innerHTML = active.map(t => `
      <tr>
        <td>${t.game_date}</td>
        <td>${t.player}</td>
        <td>${t.stat}</td>
        <td class="num">${t.line}</td>
        <td class="side-${t.side.toLowerCase()}">${t.side}</td>
        <td class="num">${t.price.toFixed(2)}</td>
        <td class="num">${fmtUsd(t.stake)}</td>
        <td><span class="pill active">PENDING</span></td>
      </tr>
    `).join("");
  }

  let allClosed = [];
  function renderClosed() {
    const q = $("search").value.trim().toLowerCase();
    const src = $("filter-source").value;
    const res = $("filter-result").value;
    const filtered = allClosed.filter(t => {
      if (src !== "all" && t.source !== src) return false;
      if (res === "win" && !t.won) return false;
      if (res === "loss" && t.won) return false;
      if (q && !(t.player.toLowerCase().includes(q) || t.stat.toLowerCase().includes(q))) return false;
      return true;
    });
    // latest first
    filtered.sort((a, b) => (b.game_date || "").localeCompare(a.game_date || "") || b.player.localeCompare(a.player));

    const tbody = document.querySelector("#closed-table tbody");
    tbody.innerHTML = filtered.slice(0, 500).map(t => {
      const pnlCls = t.pnl > 0 ? "pnl-pos" : t.pnl < 0 ? "pnl-neg" : "";
      const resultPill = t.won ? `<span class="pill win">WIN</span>` : `<span class="pill loss">LOSS</span>`;
      const srcPill = t.source === "live" ? `<span class="pill live">LIVE</span>` : `<span class="pill backtest">BT</span>`;
      return `
        <tr>
          <td>${t.game_date}</td>
          <td>${t.player}</td>
          <td>${t.stat}</td>
          <td class="num">${t.line}</td>
          <td class="side-${t.side.toLowerCase()}">${t.side}</td>
          <td class="num">${t.price.toFixed(2)}</td>
          <td class="num">${t.actual !== null ? t.actual : "—"}</td>
          <td class="num">${fmtUsd(t.stake)}</td>
          <td class="num ${pnlCls}">${fmtUsd(t.pnl, true)}</td>
          <td>${resultPill}</td>
          <td>${srcPill}</td>
        </tr>`;
    }).join("");
    $("closed-visible").textContent = Math.min(filtered.length, 500).toLocaleString();
    $("closed-total").textContent = allClosed.length.toLocaleString();
  }

  async function init() {
    const data = await load();
    setStatus(data.summary);
    renderStats(data.summary);
    renderChart(data.trades);
    renderActive(data.trades);
    allClosed = data.trades.filter(t => t.status === "closed");
    renderClosed();
    ["search", "filter-source", "filter-result"].forEach(id => {
      $(id).addEventListener("input", renderClosed);
      $(id).addEventListener("change", renderClosed);
    });
  }
  init();
})();
