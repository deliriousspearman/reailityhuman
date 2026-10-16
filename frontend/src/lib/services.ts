// Services planned but not built yet: listed under "By service" as "Soon", like the catalogue's
// templates that aren't built (templates.ts). Each becomes an extra (backend/extras.yaml) on an OS
// template when it's made; then take it out of here, and the API lists it instead. Ports, options
// and which OS runs it are decided then, so none are claimed here.
import type { Service } from './types';

type Planned = Pick<Service, 'id' | 'name' | 'category' | 'description'>;

const planned: Planned[] = [
	{
		id: 'vaultwarden',
		name: 'Vaultwarden',
		category: 'Web apps',
		description: 'Password manager server that works with the Bitwarden apps and browser extensions.',
	},
	{
		id: 'keycloak',
		name: 'Keycloak',
		category: 'Web apps',
		description: 'Single sign-on and identity server (OpenID Connect and SAML) to connect your other apps to.',
	},
	{
		id: 'mattermost',
		name: 'Mattermost',
		category: 'Web apps',
		description: 'Team chat, similar to Slack, with PostgreSQL.',
	},
	{
		id: 'grafana',
		name: 'Grafana and Prometheus',
		category: 'Monitoring',
		description: 'Metrics collection and dashboards. Point node exporters on your other machines at it.',
	},
	{
		id: 'uptime-kuma',
		name: 'Uptime Kuma',
		category: 'Monitoring',
		description: 'Uptime monitoring with a status page. Watch your other machines and services.',
	},
	{
		id: 'minio',
		name: 'MinIO',
		category: 'Storage',
		description: 'S3-compatible object storage, with a web console for buckets, users and access keys.',
	},
	{
		id: 'pihole',
		name: 'Pi-hole',
		category: 'Network services',
		description: 'DNS server that blocks ads and trackers. Handy as the DNS server for your other machines.',
	},
];

/** Planned services, shaped like the API's (no template offers them yet). */
export const plannedServices: Service[] = planned.map((x) => ({
	...x,
	conflicts: [],
	minMemoryGB: 0,
	ports: [],
	options: [],
	offeredBy: [],
}));

/** The API's services, then the planned ones it doesn't list yet. */
export function withPlanned(services: Service[]): Service[] {
	const known = new Set(services.map((x) => x.id));
	return [...services, ...plannedServices.filter((x) => !known.has(x.id))];
}
