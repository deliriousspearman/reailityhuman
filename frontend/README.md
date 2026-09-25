# Lab panel (frontend)

The web panel for deploying and controlling Pro Labs. SvelteKit, built as static files for Caddy.

**Status: design prototype.** Data comes from a mock store (`src/lib/mock/`) that simulates deploys,
resets and power actions on timers. Nothing talks to vSphere yet.

```sh
npm install
npm run dev      # http://localhost:5173
npm run check    # type check
npm run build    # static site in build/
```

Use the account menu (top right) to preview the panel as an admin or a learner.

## Pages

| Path | What it's for |
|---|---|
| `/` | Pro Labs catalogue, with a live status terminal |
| `/labs/<slug>` | A lab: join the shared copy or deploy your own |
| `/instances/<id>` | A running instance: network map, machine controls, VPN file, activity |
| `/instances` | Instances you can see |
| `/admin` | Capacity, every instance, the job queue |
| `/login` | Sign in |

## Design

Matches the LMS (`../lms`) "Hacklab" theme: the same colour tokens (`src/lib/styles/tokens.css`,
ported from `lms/src/styles/custom.css`), self-hosted fonts (Chakra Petch, Figtree, JetBrains Mono),
cards, stat tiles, lime-railed headings and terminal windows. No CDN requests, so it works offline.

Lab slugs, titles, descriptions and pictures match the LMS lab pages. Example addresses use
documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and `.example` domains.
