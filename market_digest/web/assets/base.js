(async () => {
  const badge = document.getElementById("global-research-badge");
  if (!badge) return;
  const refresh = async () => {
    try {
      const resp = await fetch("/api/research/active");
      if (!resp.ok) return;
      const jobs = await resp.json();
      if (jobs.length > 0) {
        badge.textContent = `🔍 ${jobs.length}`;
        badge.style.display = "inline";
      } else {
        badge.style.display = "none";
      }
    } catch {}
  };
  await refresh();
  setInterval(refresh, 10000);
})();
