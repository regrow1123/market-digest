(async () => {
  const strip = document.getElementById("research-strip");
  if (!strip) return;

  const refresh = async () => {
    try {
      const resp = await fetch("/api/research/active");
      if (!resp.ok) return;
      const jobs = await resp.json();
      if (jobs.length > 0) {
        const tickers = jobs.map((j) => j.ticker).join(", ");
        strip.textContent = `리서치 진행중 · ${tickers} (${jobs.length})`;
        strip.style.display = "block";
        document.body.classList.add("has-research-strip");
      } else {
        strip.style.display = "none";
        document.body.classList.remove("has-research-strip");
      }
    } catch {}
  };
  await refresh();
  setInterval(refresh, 10000);
})();
