(async () => {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const count = document.getElementById("search-count");

  let cards = [];
  try {
    cards = await (await fetch("cards.json")).json();
  } catch (e) {
    count.textContent = "검색 데이터를 불러오지 못했습니다.";
    return;
  }

  const render = (matches) => {
    count.textContent = `결과 ${matches.length}`;
    results.innerHTML = matches.map((c) => {
      const flag = c.region === "us" ? "🇺🇸" : "🇰🇷";
      const href = `${c.date}/${c.id}.html`;
      const tag = c.house ? `<span class="tag">[${c.house}]</span>` : "";
      const nameLine = c.name ? `<span class="name">${c.name}</span>` : "";
      const ticker = c.ticker ? ` (${c.ticker})` : "";
      const meta = (c.opinion || c.target) ? `<span class="meta">· ${c.opinion || ""} ${c.target || ""}</span>` : "";
      const blurb = c.company_blurb ? `<span class="blurb">${c.company_blurb}</span>` : "";
      return `<li><a class="card" href="${href}"><span class="date-chip">${c.date}</span> ${flag} ${tag} ${nameLine}${ticker} <span class="dash">—</span> <span class="headline">${c.headline}</span> ${meta}${blurb}</a></li>`;
    }).join("");
  };

  const match = (q) => {
    q = q.trim().toLowerCase();
    if (!q) return [];
    return cards.filter((c) => {
      const hay = [c.name, c.ticker, c.house, c.headline].filter(Boolean).join(" ").toLowerCase();
      return hay.includes(q);
    });
  };

  input.addEventListener("input", () => render(match(input.value)));
  input.focus();
})();
