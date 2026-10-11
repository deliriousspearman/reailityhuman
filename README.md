# lab-deploy

A web panel that deploys, resets and tears down Pro Labs (HackTheBox-style networks of vulnerable
machines) on VMware vSphere, for a LAN without internet access. The labs are advertised on the LMS;
lab slugs match its `labs/<slug>.md` pages.

- [`frontend/`](frontend/): the panel UI (SvelteKit, static build). Currently a design prototype on mock data.
- [`docs/plan.md`](docs/plan.md): the plan: stack, vSphere architecture, features, limitations and phases.

- [`deploy/`](deploy/): server setup and deployment (Docker Compose, Caddy).

The back end (FastAPI + pyVmomi + PostgreSQL, see the plan) comes next.

## Deploying

Once per server, on the server (Ubuntu 22.04/24.04):

```sh
sudo bash deploy/setup-server.sh   # Docker, full-size root volume, /srv/lab-deploy, docker group
```

After that, every push to `main` deploys itself: the GitLab pipeline ([`.gitlab-ci.yml`](.gitlab-ci.yml))
checks and builds the panel, then runs `deploy/deploy.sh` against the server. The CI/CD variables it
needs are listed at the top of that file.

To deploy by hand from a development machine instead:

```sh
DEPLOY_HOST=192.0.2.10 SSH_KEY=~/.ssh/lab-deploy deploy/deploy.sh
```

The panel is served over HTTPS by Caddy with its own internal CA, the same as the LMS. Browsers warn
until they trust its root certificate, which you can export with:

```sh
docker compose -f /srv/lab-deploy/compose.yaml exec caddy cat /data/caddy/pki/authorities/local/root.crt
```

## Conventions

- Example addresses use documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and
  `.example` domains. Real hostnames, IPs and keys stay out of the repository.
- Every change is committed and pushed to `main`, which deploys it.
