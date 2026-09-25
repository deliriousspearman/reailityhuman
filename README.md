# lab-deploy

A web panel that deploys, resets and tears down Pro Labs (HackTheBox-style networks of vulnerable
machines) on VMware vSphere, for a LAN without internet access. The labs are advertised on the LMS;
lab slugs match its `labs/<slug>.md` pages.

- [`frontend/`](frontend/): the panel UI (SvelteKit, static build). Currently a design prototype on mock data.
- [`docs/plan.md`](docs/plan.md): the plan: stack, vSphere architecture, features, limitations and phases.

The back end (FastAPI + pyVmomi + PostgreSQL, see the plan) comes next.

## Conventions

- Example addresses use documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and
  `.example` domains. Real hostnames, IPs and keys stay out of the repository.
- Every change is committed and pushed to `main`.
