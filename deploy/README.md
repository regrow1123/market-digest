# Deploying the web digest

## 1. Caddy

```bash
sudo apt install caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile.market-digest
# Then either append the block to /etc/caddy/Caddyfile or import it.
sudo systemctl enable --now caddy
curl -I http://localhost:8086    # should return 200 or 404 if site/ isn't built yet
```

## 2. Cloudflare Tunnel

The existing `sund4y-tunnel` is managed from the Cloudflare dashboard
(not a local `config.yml`). Add an ingress rule there:

- Hostname: `market-digest.<your-domain>`
- Service: `http://localhost:8086`

Verify `cloudflared` is running:

```bash
systemctl --user status cloudflared  # or: ps -fp $(pgrep cloudflared)
```

## 3. First build

Static files are produced by `market_digest.run`. Trigger a build with
today's data, or rebuild from existing JSON only:

```bash
uv run python -c "from pathlib import Path; from market_digest.web import build; print(build(Path('/mnt/nas/market-digest')))"
```

## 4. Daily run

The existing cron / scheduler that invokes `python -m market_digest.run`
now also rebuilds the site as its last step.

## 5. FMP API key

1. Register free account at https://site.financialmodelingprep.com/developer/docs
2. Copy API key into `.env`:
   ```
   FMP_API_KEY=your_key_here
   ```
3. Free tier: 250 calls/day. Daily run uses ~10-30 calls (feed + profiles).
