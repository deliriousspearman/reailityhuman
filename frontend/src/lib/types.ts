// Shapes the panel works with. For now they're filled by src/lib/mock/; later the API returns the
// same shapes. Lab fields mirror the LMS lab frontmatter (lms/src/content.config.ts), plus what's
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
	lab: string;
	action: string;
	by: string;
	state: JobState;
	startedAt: number;
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
