# lab-deploy

A web panel that deploys, resets and tears down Pro Labs (HackTheBox-style networks of vulnerable
machines) on VMware vSphere, for a LAN without internet access. The labs are advertised on the LMS;
lab slugs match its `labs/<slug>.md` pages.

What works so far is **single machines**: deploy one VM from a template (Ubuntu 26.04 for now) onto
the LAN, then start, stop, reboot, reset, extend and destroy it. Pro Labs, the VPN and sign-in come
later; the panel shows them greyed out.

- [`frontend/`](frontend/): the panel UI (SvelteKit, static build).
- [`backend/`](backend/): the API and job worker (FastAPI, pyVmomi, PostgreSQL with Procrastinate).
  [`backend/templates.yaml`](backend/templates.yaml) lists what can be deployed.
- [`deploy/`](deploy/): server setup and deployment (Docker Compose, Caddy).
- [`scripts/setup_vcenter.py`](scripts/setup_vcenter.py): prepares vCenter (folders, roles, permissions).
- [`scripts/template/`](scripts/template/): `prepare.sh` and `clean.sh` turn a fresh Linux VM (Ubuntu, Debian,
  CentOS Stream, Rocky, Alma) into a template.
- [`docs/setup-vsphere.md`](docs/setup-vsphere.md): the one-off vCenter setup and how to build the
  Ubuntu template.
- [`docs/plan.md`](docs/plan.md): the plan: stack, vSphere architecture, features, limitations and phases.

**No sign-in yet:** anyone who can reach the panel can deploy and destroy machines and read their
passwords. Keep it on a trusted network until accounts exist.

## Developing

```sh
# Backend tests, against PostgreSQL and vcsim (VMware's vCenter simulator), in Docker:
docker compose -f backend/compose.test.yaml run --rm --build tests

# Frontend, with /api proxied to an API on localhost:8000:
cd frontend && npm install && npm run dev
```

## Deploying

Once per server, on the server (Ubuntu 22.04/24.04):

```sh
sudo bash deploy/setup-server.sh   # Docker, full-size root volume, /srv/lab-deploy, docker group
```

After that, every push to `main` deploys itself: the GitLab pipeline ([`.gitlab-ci.yml`](.gitlab-ci.yml))
checks and builds the panel and tests the backend, then runs `deploy/deploy.sh` against the server.
The CI/CD variables it needs are listed at the top of that file.

The first deploy creates `/srv/lab-deploy/lab-deploy.env` on the server, with a generated database
password. Fill in its vCenter settings ([`docs/setup-vsphere.md`](docs/setup-vsphere.md)) before
deploying machines.

To deploy by hand from a development machine instead:

```sh
DEPLOY_HOST=192.0.2.10 SSH_KEY=~/.ssh/lab-deploy deploy/deploy.sh
```

The panel is served over HTTPS by Caddy with its own internal CA, the same as the LMS. Browsers warn
until they trust its root certificate, which you can export with:

```sh
docker compose -f /srv/lab-deploy/compose.yaml exec caddy cat /data/caddy/pki/authorities/local/root.crt
```

### Backups

The `backup` service dumps the database when it starts and then once a day, to
`/srv/lab-deploy/backups/labdeploy-<date>-<time>.sql.gz`, and deletes dumps older than 14 days. The
database holds every machine's password and settings; without it, the panel no longer knows the VMs
in vCenter. Copy the folder somewhere else as well, if you can.

To restore one (it replaces what's in the database), with the worker stopped so no job runs:

```sh
cd /srv/lab-deploy
docker compose stop worker
gunzip -c backups/labdeploy-<date>-<time>.sql.gz | docker compose exec -T postgres psql -q -U labdeploy labdeploy
docker compose start worker
```

## Conventions

- Example addresses use documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and
  `.example` domains. Real hostnames, IPs and keys stay out of the repository.
- Every change is committed and pushed to `main`, which deploys it.
