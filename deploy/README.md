# Deploying the web digest (dynamic)

## 1. FastAPI app (systemd)

```bash
sudo cp deploy/market-digest-web.service.example /etc/systemd/system/market-digest-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now market-digest-web
curl -s http://127.0.0.1:8087/healthz   # -> {"ok":true}
```

## 2. Caddy (reverse proxy)

```bash
# append the block from deploy/Caddyfile.example to /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl -I http://localhost:8086/healthz    # -> 200 via Caddy
```

## 3. Cloudflare Tunnel + Access

Ingress already routes the hostname to `http://localhost:8086`. Cloudflare
Access policy (email allowlist) is configured in the Cloudflare dashboard.

## 4. FMP API key

1. Register free account at https://site.financialmodelingprep.com/developer/docs
2. Copy API key into `.env`:
   ```
   FMP_API_KEY=your_key_here
   ```
3. Free tier: 250 calls/day.

## 5. Daily run

The existing cron that invokes `python -m market_digest.run` now writes JSON + blurbs only. The web app reads from NAS on every request; no build step required.

## 6. Deep research from the web

On any detail page for a ticker that has no research yet:
1. Click "🔍 딥 리서치 시작".
2. Status line updates as the background job progresses.
3. On completion, browser auto-navigates to the research page.
4. You can leave the page — the job keeps running; come back or watch the global badge (top-right) for progress.
