# NovaGuard Website

Editorial landing page and administration dashboard built with Astro 7 and a
React 19 dashboard island. The site exports to static files and is served by a
Cloudflare Worker that handles the automatic public launch, maintenance state,
security headers and static routing.

## Develop

```bash
npm install
npm run dev               # http://localhost:4321
```

Set `PUBLIC_API_BASE` to the public NovaGuard bot API origin for local work.
Production builds already use `https://api.novaguard.fun` from `.env.production`.

The `/status` page reads `GET /api/v1/health` and `GET /api/v1/stats` from this
origin. For production, use an HTTPS hostname published through Cloudflare
Tunnel, not `localhost` or the Pi's private address.

## Test and build

```bash
npm test                  # API client and configuration-form tests
npm run build             # static Astro export into dist/
```

`npm run build` reads the single launch instant in `launch-config.js`. Before
that instant it copies the preserved Coming Soon page onto `dist/index.html`;
afterwards it keeps the permanent root redirect to `/home/`. The Coming Soon
artifact also redirects an already-open browser tab as soon as the countdown
reaches zero.

To verify the permanent public-root artifact without the pre-launch overlay:

```bash
npm run build:launch
```

## Deploy to Cloudflare

The Worker serves `dist/` and uses the same timestamp as the build. Before the
launch it validates the temporary signed password cookie. At the launch instant
it redirects `/`, `/login/` and `/coming-soon/` to `/home/`, retires the password
API, clears old gate cookies and opens the marketing pages. The dashboard still
uses its separate Discord OAuth session, and maintenance mode stays available.
Pre-launch password submissions are capped by the `LOGIN_RATE_LIMITER` binding.

Keep `AUTH_PASSWORD` configured as an internal signing secret for maintenance
preview cookies (and for the temporary gate until launch), then deploy:

```bash
npx wrangler secret put AUTH_PASSWORD
npm run deploy
```

Production deploys persist a 25% sample of Worker logs and a 5% sample of
automatic traces. Upstream/API failures are emitted as structured JSON without
request bodies, cookies, passwords, preview codes or secret environment values.
Inspect them from Cloudflare Workers → NovaGuard → Observability, or locally:

```bash
npx wrangler tail novaguard --status error
```

Site routes can be temporarily replaced with the maintenance page by setting
the Worker variable `MAINTENANCE_MODE`.

```bash
npx wrangler secret put MAINTENANCE_MODE
# type: protected
```

Turn it back off with:

```bash
npx wrangler secret put MAINTENANCE_MODE
# type: off
```

Accepted enabled values are `1`, `true`, `on`, `enabled`, `protected` and
`private`. When enabled, site routes serve `/maintenance/` before the launch
redirect or former password gate. The privacy policy, terms and server-admin
notice remain available.

Cloudflare Access applications must remain disabled for the public hostname or
they would reintroduce a site-wide sign-in after the automatic launch.

Bot-side requirements:

- `WEB_ENABLED=true`, `DISCORD_CLIENT_ID`, and `DISCORD_CLIENT_SECRET`
- `WEB_CORS_ORIGIN` includes this website origin
- `WEB_AFTER_LOGIN` points to `https://<site>/dashboard/`

## Structure

```text
src/pages/              Astro landing, login, legal, status and dashboard shell
src/components/         Astro landing components and React visual islands
src/app/                existing dashboard application and TanStack Router
src/lib/api/            typed API client and Zod schemas
public/coming-soon/     preserved legacy page; do not edit
launch-config.js        one public-launch timestamp and destination
worker/                 Cloudflare launch, maintenance and static asset handler
scripts/soft-launch.mjs date-aware Coming Soon overlay
```
