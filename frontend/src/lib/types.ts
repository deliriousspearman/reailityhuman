// Shapes the panel works with. Single machines and jobs come from the API (backend/app/api.py) in
// these shapes; labs and instances are still only designs. Lab fields mirror the LMS lab frontmatter (lms/src/content.config.ts), plus what's
// needed to deploy: networks, IPs, boot order and resources.

export type OS = 'Windows' | 'Linux' | 'FreeBSD' | 'Other';
export type Level = 'Beginner' | 'Intermediate' | 'Advanced';

export interface Network {
	name: string;
	cidr: string;
	/** The network learners reach over the VPN. Other networks are reached by pivoting. */
	entry?: boolean;
}

export interface Nic {
	network: string;
	ip: string;
}

export interface LabMachine {
	name: string;
	os: OS;
	role: string;
	nics: Nic[];
	domainJoined?: boolean;
	/** Lower boots first (e.g. the domain controller before members). */
	bootOrder: number;
}

export interface Lab {
	slug: string;
	title: string;
	description: string;
	image: string;
	level: Level;
	environment: 'domain' | 'standalone';
	domain?: string;
	networks: Network[];
	machines: LabMachine[];
	resources: { cpu: number; memoryGB: number; diskGB: number };
	templateVersion: string;
	/** `lab`: machines are reset together (domain labs, so trusts and tickets stay valid). */
	resetScope: 'lab' | 'machine';
	/** Shared instance reset schedule, shown to learners. */
	resetSchedule?: string;
}

export type MachineState = 'running' | 'booting' | 'resetting' | 'stopped' | 'error';
export type InstanceState = 'running' | 'deploying' | 'resetting' | 'stopping' | 'stopped' | 'destroying' | 'error';

export interface LogLine {
	at: number;
	text: string;
	tone?: 'ok' | 'warn' | 'error' | 'muted';
}

export interface Instance {
	id: string;
	lab: string;
	kind: 'shared' | 'dedicated';
	owner?: string;
	state: InstanceState;
	startedAt: number;
	expiresAt?: number;
	nextResetAt?: number;
	lastResetAt?: number;
	connected: number;
	/** WireGuard endpoint on the lab-access network. */
	endpoint: string;
	machines: Record<string, MachineState>;
	log: LogLine[];
}

export type JobState = 'queued' | 'running' | 'done' | 'failed';

export interface Job {
	id: string;
	instanceId: string;
	/** Set for single-machine jobs (then instanceId and lab are empty). */
	machineId?: string;
	lab: string;
	action: string;
	by: string;
	state: JobState;
	queuedAt: number;
	/** Null while it waits in the queue. */
	startedAt: number | null;
	finishedAt?: number;
	detail?: string;
	/** The job that retried this one. */
	retriedAs?: string;
}

export type Role = 'admin' | 'learner';

export interface User {
	username: string;
	role: Role;
}

// Single machines ------------------------------------------------------------------------------------
// One VM from a template (an OS or appliance), in its owner's personal network. Temporary by default:
// it expires, is powered off, and is deleted a day later unless extended or kept permanently.

export type Access = 'ssh' | 'rdp' | 'web' | 'console';

/**
 * Things that affect whether or how a template can be deployed:
 * `nested`: runs VMs itself, so needs hardware virtualisation exposed to the guest;
 * `licence`: needs a licence or activation (KMS/volume keys) on an offline network;
 * `vtpm`: needs a virtual TPM, which needs a key provider in vCenter;
 * `domain`: needs Active Directory, so it's deployed with a domain controller.
 */
export type TemplateFlag = 'nested' | 'licence' | 'vtpm' | 'domain';

export type TemplateCategory =
	| 'Firewalls and routers'
	| 'Linux'
	| 'Windows'
	| 'Windows Server'
	| 'Hypervisors'
	| 'Mail'
	| 'Storage'
	| 'Self-hosted apps'
	| 'Developer tools'
	| 'Security'
	| 'Practice targets';

export interface TemplateVersion {
	version: string;
	/** No longer receives updates from its vendor. Still useful for practising on old systems. */
	eol?: boolean;
}

export interface MachineTemplate {
	id: string;
	name: string;
	category: TemplateCategory;
	os: OS;
	description: string;
	/** Newest first; the first is the default. */
	versions: TemplateVersion[];
	resources: { cpu: number; memoryGB: number; diskGB: number };
	access: Access[];
	/** Web interface address, with {ip} for the machine's address. Default: https://{ip}/ */
	webUrl?: string;
	/** Default sign-in to the machine or app, shown on the machine's page. */
	credentials?: string;
	/** SSH user, when it isn't the user in `credentials` (e.g. an app whose sign-in is its own). */
	sshUser?: string;
	flags?: TemplateFlag[];
}

export type SingleMachineState =
	| 'deploying'
	| 'rebooting'
	| 'running'
	| 'stopping'
	| 'stopped'
	| 'resetting'
	| 'expired'
	| 'destroying'
	/** The last job failed; the log says why. */
	| 'error';

export interface SingleMachine {
	id: string;
	/** Hostname, chosen by the owner. */
	name: string;
	template: string;
	version: string;
	owner: string;
	state: SingleMachineState;
	createdAt: number;
	/** null: kept permanently. */
	expiresAt: number | null;
	/** Address on the LAN, from DHCP; empty until VMware Tools reports it. */
	ip: string;
	/** The VM's name in vCenter. */
	vmName: string;
	/** Account made on first boot, and its generated password. */
	username: string;
	password: string;
	/** Extras chosen at deploy, with every option as applied (defaults filled in). */
	extras: { id: string; name: string; options: Record<string, string> }[];
	/** Addresses the extras serve, e.g. http://<ip>/; empty until the machine has an address. */
	links: string[];
	/** Only from GET /machines/{id}: the list leaves it out. */
	log?: LogLine[];
}

/** A setting on an extra, e.g. the domain name a certificate is for. */
export interface ExtraOption {
	id: string;
	label: string;
	help: string;
	/** `hostname`: a DNS name, optionally "*."-prefixed. `text`: checked by the API. */
	type: 'hostname' | 'text';
	required: boolean;
	/** Used when left blank. {hostname} is the machine's name; {fqdn} adds PanelConfig.machineDomain. */
	default: string;
	/** For `text`: what the whole value must match. */
	pattern?: string;
}

/** An optional service set up on a machine's first boot (backend/extras.yaml). */
export interface Extra {
	id: string;
	name: string;
	description: string;
	/** Extras that can't be chosen with this one (they use the same port). */
	conflicts: string[];
	options: ExtraOption[];
}

/** An extra chosen in a deploy request; blank options get their defaults. */
export interface ExtraChoice {
	id: string;
	options: Record<string, string>;
}

/** What the API can deploy, and its limits (GET /api/config). */
export interface PanelConfig {
	templates: {
		template: string;
		version: string;
		resources: { cpu: number; memoryGB: number; diskGB: number };
		username: string;
		/** debian, rhel or windows (backend/templates.yaml). */
		family: string;
		/** Extras this version's template offers. */
		extras: Extra[];
		/** Set in templates.yaml; otherwise the catalogue's (templates.ts). */
		access?: Access[];
		webUrl?: string;
	}[];
	/** Domain for default names ({fqdn} in option defaults); empty: just the machine's name. */
	machineDomain: string;
	/** How long an expired machine is kept before it's deleted. */
	graceMs: number;
	maxMachines: number;
	maxPermanent: number;
	vcenterConfigured: boolean;
	/** The API's checks on deploys (backend/app/api.py), so the form can show problems while typing. */
	rules: {
		name: { pattern: string; problem: string };
		owner: { pattern: string; problem: string };
		passwordMin: number;
		/** A DNS name, for `hostname` extra options. */
		hostname: string;
	};
}

export interface Capacity {
	total: { cpu: number; memoryGB: number; diskGB: number };
	used: { cpu: number; memoryGB: number; diskGB: number };
}

/** A person's own network, shared by all their single machines and reached over one WireGuard tunnel. */
export interface PersonalNetwork {
	cidr: string;
	endpoint: string;
}
