(() => {
  const btn = document.getElementById("research-btn");
  const status = document.getElementById("research-status");
  if (!btn || !status) return;

  const ticker = btn.dataset.ticker;
  const date = btn.dataset.date;

  const setStatus = (text) => { status.textContent = text; };

  const poll = async (jobId) => {
    while (true) {
      await new Promise(r => setTimeout(r, 5000));
      const resp = await fetch(`/api/research/status/${jobId}`);
      if (!resp.ok) { setStatus("상태 조회 실패 — 페이지 새로고침 후 재시도"); return; }
      const body = await resp.json();
      if (body.status === "done" && body.output_url) {
        setStatus("완료 — 이동 중…");
        window.location.href = body.output_url;
        return;
      }
      if (body.status === "failed") {
        setStatus(`실패: ${body.error || "알 수 없음"}`);
        btn.disabled = false;
        return;
      }
      setStatus(`생성 중 (${body.status})…`);
    }
  };

  const start = async () => {
    btn.disabled = true;
    setStatus("요청 중…");
    try {
      const resp = await fetch("/api/research", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({ticker, date}),
      });
      if (!resp.ok) { setStatus("요청 실패"); btn.disabled = false; return; }
      const body = await resp.json();
      if (body.status === "done" && body.output_url) {
        window.location.href = body.output_url;
        return;
      }
      if (body.job_id) poll(body.job_id);
    } catch (e) {
      setStatus("네트워크 오류");
      btn.disabled = false;
    }
  };

  btn.addEventListener("click", start);

  // On load, check if an active job already exists for this (ticker, date)
  (async () => {
    try {
      const resp = await fetch("/api/research/active");
      if (!resp.ok) return;
      const jobs = await resp.json();
      const existing = jobs.find(j => j.ticker.toUpperCase() === ticker.toUpperCase() && j.date === date);
      if (existing) {
        btn.disabled = true;
        setStatus("이미 요청됨 — 상태 확인 중…");
        poll(existing.job_id);
      }
    } catch {}
  })();
})();
