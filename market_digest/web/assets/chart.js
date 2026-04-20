(async () => {
  const container = document.getElementById("kr-chart");
  if (!container || !window.LightweightCharts) return;
  const ticker = container.dataset.ticker;
  if (!ticker) return;

  let bars = [];
  try {
    const resp = await fetch(`/api/chart/${ticker}`);
    if (!resp.ok) throw new Error(`http ${resp.status}`);
    bars = await resp.json();
  } catch (e) {
    container.textContent = "차트를 불러올 수 없습니다";
    return;
  }
  if (!bars.length) {
    container.textContent = "차트 데이터 없음";
    return;
  }

  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const chart = LightweightCharts.createChart(container, {
    height: 360,
    layout: {
      background: {color: dark ? "#1b1b1b" : "#ffffff"},
      textColor: dark ? "#eee" : "#333",
    },
    grid: {
      vertLines: {color: dark ? "#2a2a2a" : "#eee"},
      horzLines: {color: dark ? "#2a2a2a" : "#eee"},
    },
    rightPriceScale: {borderVisible: false},
    timeScale: {borderVisible: false, rightOffset: 3, fixLeftEdge: true},
    crosshair: {mode: 0},
  });

  const candle = chart.addCandlestickSeries({
    upColor: "#ef4444", downColor: "#2563eb",
    wickUpColor: "#ef4444", wickDownColor: "#2563eb",
    borderVisible: false,
  });
  candle.setData(bars);

  const volume = chart.addHistogramSeries({
    priceFormat: {type: "volume"},
    priceScaleId: "",
    scaleMargins: {top: 0.8, bottom: 0},
    color: dark ? "#555" : "#ccc",
  });
  volume.setData(bars.map(b => ({
    time: b.time,
    value: b.volume,
    color: b.close >= b.open ? "rgba(239,68,68,0.5)" : "rgba(37,99,235,0.5)",
  })));

  chart.timeScale().fitContent();

  window.addEventListener("resize", () => {
    chart.applyOptions({width: container.clientWidth});
  });
})();
