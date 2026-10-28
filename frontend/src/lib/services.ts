// Services planned but not built yet: listed under "By service" as "Soon", like the catalogue's
// templates that aren't built (templates.ts). Each becomes an extra (backend/extras.yaml) on an OS
// template when it's made; then take it out of here, and the API lists it instead. Ports, options
// and which OS runs it are decided then, so none are claimed here.
import type { Service } from './types';

type Planned = Pick<Service, 'id' | 'name' | 'category' | 'description'>;

const planned: Planned[] = [
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
		id: 'pihole',
		name: 'Pi-hole',
		category: 'Network services',
		description: 'DNS server that blocks ads and trackers. Handy as the DNS server for your other machines.',
	},
	{
		id: 'wazuh',
		name: 'Wazuh',
		category: 'Security',
		description: 'Open-source SIEM and endpoint monitoring. Install its agent on your other machines to watch them.',
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
