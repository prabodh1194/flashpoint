# Web

Vite + React 19 UI. No framework router, no component library. Milestone: Beacon.

## Files

| Path | Role |
|---|---|
| `src/App.jsx` | shell, view switch, theme, gateway health poll |
| `src/router.js` | zero-dep hash router (`#/worksheets`, `#/warehouses`, `#/history`, `#/history/:queryId`, `#/explorer`, `#/costs`) |
| `src/api.js` | REST client for the gateway; raises `GatewayOfflineError` when fetch dies |
| `src/views/` | Worksheet, Warehouses, History, QueryProfile, DataExplorer, Costs |
| `src/components/` | Sidebar, Topbar, QueryDag, OfflineBanner |
| `src/index.css` | theme CSS variables (dark/light via `data-theme`) |

All data flows through `src/api.js`. `VITE_GATEWAY_URL` overrides the gateway base URL
(default `http://localhost:8080`).

## Rules

- Styling is inline `styles` objects plus CSS variables from `index.css`. Tailwind is listed
  in `package.json` but unused — do not introduce `className` or Tailwind utilities.
- Every view has a URL and reloads safely. New views go into `VALID_VIEWS` and the hash
  router, not local state.
- `QueryDag.jsx` renders the gateway's `{nodes, edges}` profile: result-at-top tree, joins
  fanned out side-by-side, WholeStageCodegen nodes as slim stage chips. Card details are
  inline (scan location, filter predicate, join keys) — no hidden clicks.
- `DataExplorer.jsx` renders a fixed demo schema mirroring `scripts/e2e_demo.py`; it is not
  connected to a live catalog yet.
- When the gateway is unreachable the UI shows `OfflineBanner` — cost-saving behavior is
  intentional, not an error state.

## Commands

    npm run dev     # http://localhost:5173
    npm run build
    npm run lint
