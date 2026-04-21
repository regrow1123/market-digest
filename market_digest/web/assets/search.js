(async () => {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const count = document.getElementById("search-count");

  let cards = [];
  try {
    cards = await (await fetch("/cards.json")).json();
  } catch (e) {
    count.hidden = false;
    count.textContent = "검색 데이터를 불러오지 못했습니다.";
    return;
  }

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const render = (matches) => {
    count.textContent = `결과 ${matches.length}`;
    results.innerHTML = matches.map((c) => {
      const dir = c.direction || "neutral";
      const region = c.region === "us" ? "US" : "KR";
      const href = `/${c.date}/${c.id}`;
      const house = c.house ? `<b class="house">${esc(c.house)}</b>` : "";
      const tickerRow = c.ticker ? `<span class="sep">·</span><span class="ticker">${esc(c.ticker)}</span>` : "";
      const nameLine = c.name
        ? `<div class="name">${esc(c.name)}${c.ticker ? `<span class="ticker-inline">${esc(c.ticker)}</span>` : ""}</div>`
        : "";
      const metaParts = [];
      if (c.opinion) metaParts.push(esc(c.opinion).toUpperCase());
      if (c.target) metaParts.push(esc(c.target));
      const meta = metaParts.length
        ? `<div class="meta meta-${dir}">${metaParts.join(" · ")}</div>`
        : "";
      const blurb = c.company_blurb ? `<div class="blurb">${esc(c.company_blurb)}</div>` : "";
      const trailingDate = `<span class="date-trailing">${esc(c.date)}</span>`;
      return `<li><a class="card card-${dir}" href="${href}">`
        + `<span class="accent"></span>`
        + `<div class="card-body">`
        +   `<div class="eyebrow"><span class="region">${region}</span>${house}${tickerRow}</div>`
        +   nameLine
        +   `<div class="headline">${esc(c.headline)}</div>`
        +   meta
        +   blurb
        + `</div>`
        + trailingDate
        + `</a></li>`;
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

  const onInput = () => {
    const q = input.value.trim();
    if (!q) {
      count.hidden = true;
      results.hidden = true;
      results.innerHTML = "";
      count.textContent = "";
      return;
    }
    const matches = match(q);
    count.hidden = false;
    results.hidden = false;
    render(matches);
  };

  input.addEventListener("input", onInput);
  input.focus();
})();
