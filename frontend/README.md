# Lab panel (frontend)

The web panel for deploying and controlling machines on vSphere. SvelteKit, built as static files
that Caddy serves; everything it shows comes from the API (`../backend`) under `/api`.

```sh
npm install
npm run dev      # http://localhost:5173, with /api proxied to an API on localhost:8000
npm run check    # type check
npm run build    # static site in build/
```

## Pages

| Path | What it's for |
|---|---|
| `/` | Redirects to `/machines` |
| `/machines` | Your machines (or everyone's), and the templates to deploy more |
| `/machines/new/<template>` | Deploy a machine: version, extras, name, owner, how long to keep it, password, SSH key. `?from=<machine id>` starts from that machine's settings |
| `/machines/<id>` | A machine: controls, time left (extend or keep), sign-in details, activity log and jobs |
| `/admin` | Capacity, every machine, leftover VMs in vCenter, the job queue |
| `/labs`, `/labs/<slug>`, `/instances` | Pro Labs, shown as coming soon |

## How it fits together

- `src/lib/api.ts` calls the API, sending the name people typed at deploy (`X-Lab-User`) so jobs
  record who did what. There's no sign-in yet.
- `src/lib/store.svelte.ts` holds machines, jobs and the API's config, and polls every 3 s while
  the tab is visible (15 s when hidden). The machine list comes without logs; the machine whose
  page is open is fetched in full.
- `src/lib/templates.ts` is the catalogue: every template's name, description, category and
  versions. Only versions in `../backend/templates.yaml` can be deployed (a backend test checks
  they're all in the catalogue); for those, sizes, access and web address come from the API.
- The deploy form checks names, passwords and extra options with the API's own rules, which it
  sends in `/api/config`.

## Design

Matches the course site's Hardline Classic theme (docu-codex): the colour tokens in
`src/lib/styles/tokens.css`, self-hosted fonts (Chakra Petch, Figtree, JetBrains Mono), square
corners and 2px outlines. No CDN requests, so it works offline.

Lab slugs, titles, descriptions and pictures match the LMS lab pages. Example addresses use
documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and `.example` domains.
