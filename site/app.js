(() => {
  const $ = (id) => document.getElementById(id);

  const fmtUsd = (n, signed = false) => {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    const sign = signed ? (n > 0 ? "+" : n < 0 ? "-" : "") : "";
    const abs = Math.abs(n);
    return sign + "$" + abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtPct = (n, signed = false, digits = 2) => {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    const sign = signed ? (n > 0 ? "+" : n < 0 ? "-" : "") : "";
    return sign + Math.abs(n).toFixed(digits) + "%";
  };
  const fmtEdge = (e) => {
    if (e === null || e === undefined || Number.isNaN(e)) return "—";
    const pct = e * 100;
    return (pct >= 0 ? "+" : "-") + Math.abs(pct).toFixed(1) + "%";
  };
  const edgeClass = (e) => {
    if (e === null || e === undefined || Number.isNaN(e)) return "";
    if (e >= 0.08) return "edge-strong";
    if (e >= 0.05) return "edge-ok";
    if (e > 0)     return "edge-weak";
    return "edge-neg";
  };
  const fmtProb = (p) => (p === null || p === undefined ? "—" : (p * 100).toFixed(1) + "%");

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
    if ($("since-date") && summary.tracking_since) $("since-date").textContent = summary.tracking_since;
  }

  function renderStats(s) {
    $("val-bankroll").textContent = fmtUsd(s.current_bankroll);
    const bankrollEl = $("val-bankroll");
    bankrollEl.classList.toggle("pos", s.current_bankroll > s.starting_bankroll);
    bankrollEl.classList.toggle("neg", s.current_bankroll < s.starting_bankroll);
    $("sub-bankroll").textContent = `from $${s.starting_bankroll.toLocaleString()} start`;

    const pnl = s.total_pnl;
    const pnlEl = $("val-pnl");
    pnlEl.textContent = fmtUsd(pnl, true);
    pnlEl.classList.toggle("pos", pnl > 0);
    pnlEl.classList.toggle("neg", pnl < 0);
    $("sub-pnl").textContent = `since ${s.tracking_since || "launch"}`;

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
    // Seed a starting point so a single-day curve still draws a line.
    const starting = (window.__SUMMARY__ && window.__SUMMARY__.starting_bankroll) || 1000;
    const origin = { x: -0.5, y: starting, date: window.__SUMMARY__?.tracking_since || "", label: "start", source: "start" };
    const points = closed.map((t, i) => ({
      x: i,
      y: t.bankroll_after,
      date: t.game_date,
      label: `${t.player} ${t.stat} ${t.side}`,
      source: t.source,
    }));
    const series = [origin, ...points];

    const ctx = $("chart").getContext("2d");
    if (chart) chart.destroy();
    const gradient = ctx.createLinearGradient(0, 0, 0, 320);
    gradient.addColorStop(0, "rgba(0, 255, 156, 0.28)");
    gradient.addColorStop(1, "rgba(0, 255, 156, 0)");

    chart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [
          {
            label: "Bankroll",
            data: series,
            parsing: false,
            borderColor: "#00ff9c",
            backgroundColor: gradient,
            borderWidth: 1.6,
            pointRadius: (c) => (c.dataIndex === 0 ? 0 : 3),
            pointHoverRadius: 5,
            pointBackgroundColor: "#00ff9c",
            pointBorderColor: "#070a09",
            pointBorderWidth: 1,
            fill: true,
            tension: 0.15,
            stepped: false,
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
                const idx = Math.round(v);
                const p = series[idx + 1];  // series has origin at -0.5
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
                const x = items[0].parsed.x;
                if (x < 0) return "initial bankroll";
                const p = points[Math.round(x)];
                return p ? `${p.date} · ${p.label}` : "";
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
    $("active-count-inline").textContent = `${active.length} open · awaiting tip-off`;
    if (active.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" style="color:var(--fg-mute); text-align:center; padding:22px;">no future bets on the board — run the model for the next slate</td></tr>`;
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
        <td class="num">${fmtProb(t.p_model)}</td>
        <td class="num ${edgeClass(t.edge)}">${fmtEdge(t.edge)}</td>
        <td class="num">${fmtUsd(t.stake)}</td>
        <td><span class="pill active">PENDING</span></td>
      </tr>
    `).join("");
  }

  let allClosed = [];
  function renderClosed() {
    const q = $("search").value.trim().toLowerCase();
    const res = $("filter-result").value;
    const filtered = allClosed.filter(t => {
      if (res === "win" && !t.won) return false;
      if (res === "loss" && t.won) return false;
      if (q && !(t.player.toLowerCase().includes(q) || t.stat.toLowerCase().includes(q))) return false;
      return true;
    });
    // latest first
    filtered.sort((a, b) => (b.game_date || "").localeCompare(a.game_date || "") || b.player.localeCompare(a.player));

    const tbody = document.querySelector("#closed-table tbody");
    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="11" style="color:var(--fg-mute); text-align:center; padding:22px;">no closed trades match</td></tr>`;
    } else {
      tbody.innerHTML = filtered.map(t => {
        const pnlCls = t.pnl > 0 ? "pnl-pos" : t.pnl < 0 ? "pnl-neg" : "";
        const resultPill = t.won ? `<span class="pill win">WIN</span>` : `<span class="pill loss">LOSS</span>`;
        return `
          <tr>
            <td>${t.game_date}</td>
            <td>${t.player}</td>
            <td>${t.stat}</td>
            <td class="num">${t.line}</td>
            <td class="side-${t.side.toLowerCase()}">${t.side}</td>
            <td class="num">${t.price.toFixed(2)}</td>
            <td class="num ${edgeClass(t.edge)}">${fmtEdge(t.edge)}</td>
            <td class="num">${t.actual !== null ? t.actual : "—"}</td>
            <td class="num">${fmtUsd(t.stake)}</td>
            <td class="num ${pnlCls}">${fmtUsd(t.pnl, true)}</td>
            <td>${resultPill}</td>
          </tr>`;
      }).join("");
    }
    $("closed-visible").textContent = filtered.length.toLocaleString();
    $("closed-total").textContent = allClosed.length.toLocaleString();
  }

  async function init() {
    const data = await load();
    window.__SUMMARY__ = data.summary;
    setStatus(data.summary);
    renderStats(data.summary);
    renderChart(data.trades);
    renderActive(data.trades);
    allClosed = data.trades.filter(t => t.status === "closed");
    renderClosed();
    ["search", "filter-result"].forEach(id => {
      const el = $(id);
      if (!el) return;
      el.addEventListener("input", renderClosed);
      el.addEventListener("change", renderClosed);
    });
  }
  init();
})();
