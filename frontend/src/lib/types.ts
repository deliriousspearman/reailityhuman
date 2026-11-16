// Shapes the panel works with. Single machines, lab instances and jobs come from the API
// (backend/app/api.py) in these shapes. `Lab` is the design of an LMS lab not built yet: its fields
// mirror the LMS lab frontmatter (lms/src/content.config.ts), plus what's needed to deploy: networks,
// IPs, boot order and resources.

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

export interface LogLine {
	/** Increasing: GET /machines/{id}?after=<id> sends only the lines after one. */
	id: number;
	at: number;
	text: string;
	tone?: 'ok' | 'warn' | 'error' | 'muted';
}

/** A Pro Lab that can be deployed, or is planned (backend/labs.yaml, via GET /api/config). */
export interface DeployableLab {
	slug: string;
	title: string;
	description: string;
	level: Level;
	/** The AD domain, for a domain lab; empty for standalone hosts. */
	domain: string;
	/** `lab`: the whole instance resets together. */
	resetScope: 'lab' | 'machine';
	/** Its templates aren't built yet, so it can't be deployed. */
	planned: boolean;
	/** What an instance needs; 0 while planned. */
	memoryGB: number;
	/** In boot order. */
	machines: { name: string; template: string; version: string; role: string; bootOrder: number }[];
	/** Planted per instance, for learners to find. */
	flags: { id: string; where: string }[];
}

/** A deployed copy of a lab: its machines, set up together in the lab's boot order (GET /api/instances). */
export interface Instance {
	id: string;
	lab: string;
	title: string;
	owner: string;
	/** Busy while any machine is (its state), then error, expired, stopped or running. */
	state: SingleMachineState;
	createdAt: number;
	/** null: kept permanently. */
	expiresAt: number | null;
	/** In boot order, without their logs. */
	machines: SingleMachine[];
	/** The flags to find, each with its value this instance and whether it's planted yet. */
	flags: { id: string; where: string; value?: string; planted: boolean }[];
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
	/** Who cancelled it, while it's still stopping. */
	cancelledBy?: string;
	/** The job that retried this one. */
	retriedAs?: string;
	/** A template build's template version, "<template>/<version>" (then machineId is unset). */
	template?: string;
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
	| 'BSD'
	| 'Windows'
	| 'Windows Server'
	| 'Hypervisors'
	| 'Mail'
	| 'Storage'
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
	/** Account made on first boot, and its generated password (only from GET /machines/{id}: the
	 * lists leave it out). */
	username: string;
	password?: string;
	/** Its memory: the template's, or more where an extra needed it (e.g. a Wazuh server's 4 GB). */
	memoryGB?: number | null;
	/** Its vCPUs: the template's, or more where an extra needed them. */
	cpu?: number | null;
	/**
	 * Extras chosen at deploy, with every option as applied (defaults filled in), and the addresses
	 * they serve and notes on them (e.g. how to sign in); those are empty until it has an address.
	 */
	/**
	 * docker: runs in a Docker container. download: a file it made to download (e.g. a VPN client's
	 * config), from GET /api/machines/{id}/downloads/{extra id}; absent until it's ready.
	 */
	extras: {
		id: string;
		name: string;
		options: Record<string, string>;
		docker?: boolean;
		links: string[];
		notes: string[];
		download?: { label: string; filename: string };
	}[];
	/** Machines whose extras point at this one, e.g. the agents of a Wazuh server. */
	usedBy?: { id: string; name: string }[];
	/** Pro Labs: the instance it's part of, its lab and its role there; empty for a machine on its own. */
	instanceId?: string;
	lab?: string;
	role?: string;
	/** What it waits to do (deploy, reset or start) until the machines before it in the lab's boot order are ready. */
	pending?: string;
	/** Only from GET /machines/{id}: the list leaves it out. */
	log?: LogLine[];
	/** With GET /machines/{id}?after=<id>: `log` is only the lines after that one. */
	logAfter?: number;
}

/** GET /state: what every open page polls, in one request. */
export interface PanelState {
	machines: SingleMachine[];
	instances: Instance[];
	/** Only when asked for (?jobs=1). */
	jobs?: Job[];
}

/** A setting on an extra, e.g. the domain name a certificate is for. */
export interface ExtraOption {
	id: string;
	label: string;
	help: string;
	/**
	 * `hostname`: a DNS name, optionally "*."-prefixed. `text`: checked by the API. `choice`: one of
	 * `choices`. `boolean`: "yes" or "no". `machine`: the id of a running machine with `extra`.
	 */
	type: 'hostname' | 'text' | 'choice' | 'boolean' | 'machine';
	required: boolean;
	/** Used when left blank. {hostname} is the machine's name; {fqdn} adds PanelConfig.machineDomain. */
	default: string;
	/** For `text`: what the whole value must match. */
	pattern?: string;
	/** For `choice`. */
	choices?: { value: string; label: string }[];
	/** Shown only when other options of the extra have one of these values. */
	when?: Record<string, string[]>;
	/** For `machine`: the extra the chosen machine must have, e.g. domain-controller. */
	extra?: string;
}

/** An optional service set up on a machine's first boot (backend/extras.yaml). */
export interface Extra {
	id: string;
	name: string;
	description: string;
	/** Extras that can't be chosen with this one (they use the same port). */
	conflicts: string[];
	/** Heading it's listed under, e.g. "Web servers". */
	category: string;
	/** Least memory a machine needs for it; 0: any. */
	minMemoryGB: number;
	/** Least vCPUs a machine needs for it: a machine with it gets at least as many. */
	minCPU?: number;
	/** About how much disk it writes beyond a plain clone (GB); 0: nothing much. */
	diskGB?: number;
	/** Ports it means the machine listens on. */
	ports: number[];
	/** Runs in a Docker container (its image comes on a CD at deploy); the panel says so. */
	docker?: boolean;
	/** That container's image, e.g. grafana/grafana:13.2.4. */
	image?: string;
	options: ExtraOption[];
}

/** An extra, with the template versions it runs on: `ready` ones can be deployed with it now; the
 * rest are planned (the template isn't built, or not yet rebuilt with it). */
export interface Service extends Extra {
	offeredBy: { template: string; version: string; ready: boolean }[];
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
		/** debian, rhel, windows, legacy, vyos or image (backend/templates.yaml). */
		family: string;
		/** Extras this version's template offers. */
		extras: Extra[];
		/** Set in templates.yaml; otherwise the catalogue's (templates.ts). */
		access?: Access[];
		webUrl?: string;
		/** A complete image's own password (family image): every machine signs in with it. */
		fixedPassword?: string;
		/** False when it's been deleted to save space: deploying builds it first, about buildMinutes more. */
		built?: false;
		buildMinutes?: number;
	}[];
	/** Every extra, and where it runs, for choosing a service first. */
	services: Service[];
	/** Pro Labs, deployable and planned. */
	labs?: DeployableLab[];
	/** Domain for default names ({fqdn} in option defaults); empty: just the machine's name. */
	machineDomain: string;
	/** How long an expired machine is kept before it's deleted. */
	graceMs: number;
	/** What a new machine writes on its own (GB); extras add their diskGB. */
	cloneDiskGB?: number;
	maxMachines: number;
	maxPermanent: number;
	vcenterConfigured: boolean;
	/** Packet captures (backend/app/capture.py): whether the capture appliance is set up, and the limits. */
	capture?: CaptureLimits;
	/** The API's checks on deploys (backend/app/api.py), so the form can show problems while typing. */
	rules: {
		name: { pattern: string; problem: string };
		owner: { pattern: string; problem: string };
		passwordMin: number;
		/** A DNS name, for `hostname` extra options. */
		hostname: string;
		/** Windows' default password policy (backend/app/cloudinit.py, windows_password_problem). */
		windowsPassword: { kinds: number; kindsProblem: string; userProblem: string };
	};
}

export interface Capacity {
	total: { cpu: number; memoryGB: number; diskGB: number };
	used: { cpu: number; memoryGB: number; diskGB: number };
	/** Datastore space deploys never use (GB). */
	reserveGB?: number;
}

/** A person's own network, shared by all their single machines and reached over one WireGuard tunnel. */
export interface PersonalNetwork {
	cidr: string;
	endpoint: string;
}

/** A template version on the admin page (GET /api/templates): templates on demand, docs/plan.md section 11. */
export interface TemplateStatus {
	template: string;
	version: string;
	state: 'built' | 'deleted' | 'building' | 'failed';
	/** Its inventory path in vCenter, while built. */
	vsphere: string;
	/** Its size on the datastore, or null when vCenter doesn't have it (not built). */
	sizeGB: number | null;
	/** The panel's machines from it: while there are any, it can't be deleted. */
	machines: string[];
	lastDeployedAt: number | null;
	builtAt: number | null;
	/** Whether templates.yaml has a recipe for building it again. */
	rebuildable: boolean;
	build?: {
		minutes: number;
		sizeGB: number;
		rolling: boolean;
		/** present is missing when vCenter couldn't list the ISO folder. */
		isos: { name: string; present?: boolean }[];
	};
	/** Its build job, while queued or running. */
	job?: Job;
	/** Why the last build failed. */
	detail?: string;
	/** Something's wrong with it as it is, e.g. missing from vCenter. */
	problem?: string;
	deletable: boolean;
	/** Why it can't be deleted now. */
	cantDelete?: string;
}

// Packet captures (backend/app/capture.py) -------------------------------------------------------------

export interface CaptureLimits {
	configured: boolean;
	maxSeconds: number;
	maxMB: number;
	perOwner: number;
	keepDays: number;
}

/** A machine a capture was limited to, as it was when the capture started. */
export interface CaptureMachine {
	id: string;
	name: string;
	ip: string;
	macs: string[];
}

/** Who talked to whom: addresses are IPs, or MACs for traffic without one (ARP). */
export interface Conversation {
	a: string;
	b: string;
	packets: number;
	bytes: number;
}

export type CaptureState = 'running' | 'stopped' | 'failed';

export interface Capture {
	id: string;
	owner: string;
	machines: CaptureMachine[];
	/** As typed (may be empty); effectiveFilter is what tcpdump ran, limited to the machines' MACs. */
	filter: string;
	effectiveFilter: string;
	seconds: number;
	state: CaptureState;
	startedAt: number;
	endsAt: number;
	stoppedAt?: number;
	packets: number;
	bytes: number;
	conversations: Conversation[];
	/** Why it stopped. */
	detail?: string;
}

/** A packet's line in the table. */
export interface PacketLine {
	n: number;
	/** Seconds since the epoch. */
	t: number;
	src: string;
	dst: string;
	proto: string;
	len: number;
	info: string;
}

/** What a running capture's WebSocket sends, every half second. */
export interface CaptureLive {
	packets: PacketLine[];
	count?: number;
	bytes?: number;
	conversations?: Conversation[];
	done: boolean;
}

/** GET /capture-appliance, for the Admin page. */
export interface CaptureAppliance {
	vm: string;
	host: string;
	publicKey: string | null;
	running: number;
	ok: boolean;
	problem?: string;
}
