// Mock back end for the design prototype: lab instances, single machines, jobs and the signed-in
// user, held in Svelte state. Actions (deploy, reset, reboot…) play out on timers with log lines, the way the real job
// worker will report progress, so the layout can be judged with things changing. Replace with API
// calls and server-sent events once the back end exists.
import type {
	Instance,
	InstanceState,
	Job,
	Lab,
	LogLine,
	MachineState,
	MachineTemplate,
	PersonalNetwork,
	SingleMachine,
	User,
} from '../types';
import { findLab, labs } from './labs';
import { findTemplate } from './templates';

const SEC = 1000;
const MIN = 60 * SEC;
const HOUR = 60 * MIN;
/** How long an expired single machine is kept (powered off) before it's deleted. */
export const GRACE = 24 * HOUR;

/** The next 02:00 local time, when shared labs reset. */
function nextNightly(from = Date.now()): number {
	const d = new Date(from);
	d.setHours(2, 0, 0, 0);
	if (d.getTime() <= from) d.setDate(d.getDate() + 1);
	return d.getTime();
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function machinesIn(lab: Lab, state: MachineState): Record<string, MachineState> {
	return Object.fromEntries(lab.machines.map((m) => [m.name, state]));
}

/** Machines grouped by boot order, lowest first: [[DC01], [CA01, SQL01, FS01], …]. */
function bootGroups(lab: Lab): string[][] {
	const orders = [...new Set(lab.machines.map((m) => m.bootOrder))].sort((a, b) => a - b);
	return orders.map((order) => lab.machines.filter((m) => m.bootOrder === order).map((m) => m.name));
}

function randomId(): string {
	return Math.random().toString(16).slice(2, 6);
}

function seedInstances(): Instance[] {
	const now = Date.now();
	const lastNightly = nextNightly() - 24 * HOUR;
	const meridian = findLab('meridian')!;
	const harbourside = findLab('harbourside')!;
	const at = (offset: number, text: string, tone?: LogLine['tone']): LogLine => ({ at: now + offset, text, tone });
	const resetLog = (lab: Lab): LogLine[] => [
		{ at: lastNightly, text: 'Scheduled reset started', tone: 'muted' },
		{ at: lastNightly + 4 * SEC, text: `Reverted ${lab.machines.length} machines to snapshot 'clean'` },
		...bootGroups(lab).map((group, i) => ({ at: lastNightly + (20 + i * 25) * SEC, text: `Up: ${group.join(', ')}` })),
		{ at: lastNightly + 95 * SEC, text: 'Reset complete. All machines are running.', tone: 'ok' as const },
	];

	return [
		{
			id: 'mer-shared',
			lab: 'meridian',
			kind: 'shared',
			state: 'running',
			startedAt: now - 3 * 24 * HOUR - 4 * HOUR,
			lastResetAt: lastNightly,
			nextResetAt: nextNightly(),
			connected: 7,
			endpoint: '192.0.2.41:51820',
			machines: machinesIn(meridian, 'running'),
			log: resetLog(meridian),
		},
		{
			id: 'hbr-shared',
			lab: 'harbourside',
			kind: 'shared',
			state: 'running',
			startedAt: now - 9 * 24 * HOUR,
			lastResetAt: lastNightly,
			nextResetAt: nextNightly(),
			connected: 3,
			endpoint: '192.0.2.42:51820',
			machines: { ...machinesIn(harbourside, 'running'), NVR: 'error' },
			log: [...resetLog(harbourside), at(-38 * MIN, 'NVR stopped responding to health checks', 'warn')],
		},
		{
			id: 'hbr-7f3a',
			lab: 'harbourside',
			kind: 'dedicated',
			owner: 'demo',
			state: 'running',
			startedAt: now - 80 * MIN,
			expiresAt: now + 2 * HOUR + 40 * MIN,
			lastResetAt: now - 80 * MIN,
			connected: 1,
			endpoint: '192.0.2.43:51820',
			machines: machinesIn(harbourside, 'running'),
			log: [
				at(-80 * MIN, 'Deploy requested by demo (4 h)', 'muted'),
				at(-80 * MIN + 6 * SEC, `Cloned ${harbourside.machines.length} machines from harbourside/v5`),
				at(-80 * MIN + 70 * SEC, 'Instance ready. Download your VPN config to connect.', 'ok'),
				at(-52 * MIN, 'demo connected over WireGuard'),
			],
		},
		{
			id: 'mer-c21e',
			lab: 'meridian',
			kind: 'dedicated',
			owner: 'learner12',
			state: 'stopped',
			startedAt: now - 5 * HOUR,
			expiresAt: now + 19 * HOUR,
			connected: 0,
			endpoint: '192.0.2.44:51820',
			machines: machinesIn(meridian, 'stopped'),
			log: [at(-5 * HOUR, 'Deploy requested by learner12 (24 h)', 'muted'), at(-2 * HOUR, 'Stopped by learner12')],
		},
	];
}

function seedJobs(): Job[] {
	const now = Date.now();
	const lastNightly = nextNightly() - 24 * HOUR;
	return [
		{ id: 'j-1041', instanceId: 'hbr-7f3a', lab: 'harbourside', action: 'Deploy', by: 'demo', state: 'done', startedAt: now - 80 * MIN, finishedAt: now - 79 * MIN },
		{ id: 'j-1040', instanceId: 'mer-c21e', lab: 'meridian', action: 'Stop', by: 'learner12', state: 'done', startedAt: now - 2 * HOUR, finishedAt: now - 2 * HOUR + 40 * SEC },
		{ id: 'j-1039', instanceId: 'mer-shared', lab: 'meridian', action: 'Reset lab', by: 'schedule', state: 'done', startedAt: lastNightly, finishedAt: lastNightly + 95 * SEC },
		{ id: 'j-1038', instanceId: 'hbr-shared', lab: 'harbourside', action: 'Reset lab', by: 'schedule', state: 'done', startedAt: lastNightly, finishedAt: lastNightly + 80 * SEC },
		{
			id: 'j-1037',
			instanceId: '—',
			lab: 'meridian',
			action: 'Deploy',
			by: 'learner07',
			state: 'failed',
			startedAt: now - 26 * HOUR,
			finishedAt: now - 26 * HOUR + 5 * SEC,
			detail: 'Not enough memory in resource pool ProLabs: needs 40 GB, 31 GB free.',
		},
	];
}

function seedMachines(): SingleMachine[] {
	const now = Date.now();
	const at = (offset: number, text: string, tone?: LogLine['tone']): LogLine => ({ at: now + offset, text, tone });
	return [
		{
			id: 'm-4b1c',
			name: 'fw01',
			template: 'pfsense',
			version: '2.8.0',
			owner: 'demo',
			state: 'running',
			createdAt: now - 3 * HOUR - 10 * MIN,
			expiresAt: now + 50 * MIN,
			ip: '10.99.7.10',
			log: [at(-3 * HOUR - 10 * MIN, 'Deploy requested by demo (4 h)', 'muted'), at(-3 * HOUR - 9 * MIN, 'Ready at 10.99.7.10', 'ok')],
		},
		{
			id: 'm-9e2a',
			name: 'dc01',
			template: 'windows-server',
			version: '2022',
			owner: 'demo',
			state: 'running',
			createdAt: now - 6 * 24 * HOUR,
			expiresAt: null,
			ip: '10.99.7.20',
			log: [
				at(-6 * 24 * HOUR, 'Deploy requested by demo (1 day)', 'muted'),
				at(-6 * 24 * HOUR + 3 * MIN, 'Ready at 10.99.7.20', 'ok'),
				at(-5 * 24 * HOUR, 'Kept permanently by demo'),
			],
		},
		{
			id: 'm-77d0',
			name: 'web-dev',
			template: 'ubuntu',
			version: '24.04',
			owner: 'demo',
			state: 'expired',
			createdAt: now - 11 * HOUR,
			expiresAt: now - 3 * HOUR,
			ip: '10.99.7.30',
			log: [
				at(-11 * HOUR, 'Deploy requested by demo (8 h)', 'muted'),
				at(-11 * HOUR + MIN, 'Ready at 10.99.7.30', 'ok'),
				at(-3 * HOUR, 'Time ran out: powered off. Extend it within a day to keep it.', 'warn'),
			],
		},
		{
			id: 'm-c3f8',
			name: 'kali-07',
			template: 'kali',
			version: '2026.2',
			owner: 'learner07',
			state: 'running',
			createdAt: now - 2 * HOUR,
			expiresAt: now + 6 * HOUR,
			ip: '10.99.12.10',
			log: [at(-2 * HOUR, 'Deploy requested by learner07 (8 h)', 'muted')],
		},
	];
}

class LabStore {
	user = $state<User>({ username: 'demo', role: 'admin' });
	instances = $state<Instance[]>(seedInstances());
	jobs = $state<Job[]>(seedJobs());
	machines = $state<SingleMachine[]>(seedMachines());
	/** The signed-in person's own network for single machines. */
	network: PersonalNetwork = { cidr: '10.99.7.0/24', endpoint: '192.0.2.60:51820' };
	/** The ProLabs resource pool. */
	capacity = { cpu: 64, memoryGB: 160, diskGB: 2000 };
	/** Ticks every second, for countdowns and uptimes. */
	now = $state(Date.now());
	#nextJob = 1042;

	constructor() {
		if (typeof window === 'undefined') return;
		setInterval(() => {
			this.now = Date.now();
			this.#checkExpiry();
		}, SEC);
	}

	get isAdmin() {
		return this.user.role === 'admin';
	}

	/** How many dedicated instances one person may run at a time. */
	get quota() {
		return this.isAdmin ? 3 : 1;
	}

	get mine(): Instance[] {
		return this.instances.filter((i) => i.owner === this.user.username);
	}

	/** Reserved resources: disk for everything that exists, CPU and memory for what's powered on. */
	get used() {
		let cpu = 0;
		let memoryGB = 0;
		let diskGB = 0;
		const add = (r: { cpu: number; memoryGB: number; diskGB: number }, on: boolean) => {
			diskGB += r.diskGB;
			if (on) {
				cpu += r.cpu;
				memoryGB += r.memoryGB;
			}
		};
		for (const inst of this.instances) add(findLab(inst.lab)!.resources, inst.state !== 'stopped');
		for (const m of this.machines) add(findTemplate(m.template)!.resources, m.state !== 'stopped' && m.state !== 'expired');
		return { cpu, memoryGB, diskGB };
	}

	/** Why these resources can't be reserved right now, or null if they can. */
	#capacityBlocker(needs: { cpu: number; memoryGB: number }, what: string): string | null {
		const free = { cpu: this.capacity.cpu - this.used.cpu, memoryGB: this.capacity.memoryGB - this.used.memoryGB };
		if (needs.memoryGB > free.memoryGB) {
			return `Not enough memory free right now: ${what} needs ${needs.memoryGB} GB and ${free.memoryGB} GB is free. Try again later.`;
		}
		if (needs.cpu > free.cpu) {
			return `Not enough CPU free right now: ${what} needs ${needs.cpu} vCPU and ${free.cpu} are free. Try again later.`;
		}
		return null;
	}

	instance(id: string): Instance | undefined {
		return this.instances.find((i) => i.id === id);
	}

	shared(slug: string): Instance | undefined {
		return this.instances.find((i) => i.lab === slug && i.kind === 'shared');
	}

	dedicated(slug: string): Instance | undefined {
		return this.mine.find((i) => i.lab === slug);
	}

	/** Why a dedicated copy of this lab can't be deployed right now, or null if it can. */
	deployBlocker(lab: Lab): string | null {
		if (this.mine.length >= this.quota) {
			return `You can run ${this.quota === 1 ? 'one instance' : `${this.quota} instances`} at a time. Destroy one to deploy another.`;
		}
		return this.#capacityBlocker(lab.resources, 'this lab');
	}

	// Single machines ------------------------------------------------------------------------------

	/** How many single machines one person may have (running, stopped or expired). */
	get machineQuota() {
		return this.isAdmin ? 10 : 3;
	}

	/** How many of those may be kept permanently. */
	get permanentQuota() {
		return this.isAdmin ? 5 : 1;
	}

	get myMachines(): SingleMachine[] {
		return this.machines.filter((m) => m.owner === this.user.username);
	}

	get permanentCount() {
		return this.myMachines.filter((m) => m.expiresAt === null).length;
	}

	machine(id: string): SingleMachine | undefined {
		return this.machines.find((m) => m.id === id);
	}

	/** Why this template can't be deployed right now, or null if it can. */
	machineBlocker(template: MachineTemplate): string | null {
		if (this.myMachines.length >= this.machineQuota) {
			return `You can have ${this.machineQuota} machines at a time. Destroy one to deploy another.`;
		}
		return this.#capacityBlocker(template.resources, template.name);
	}

	/** Why this machine can't be kept permanently, or null if it can. */
	keepBlocker(m: SingleMachine): string | null {
		if (m.expiresAt === null) return null;
		if (this.permanentCount >= this.permanentQuota) {
			return `You can keep ${this.permanentQuota === 1 ? 'one machine' : `${this.permanentQuota} machines`} permanently. Set an expiry on another one first.`;
		}
		return null;
	}

	canControlMachine(m: SingleMachine): boolean {
		return this.isAdmin || m.owner === this.user.username;
	}

	/** Whether the signed-in user may reset, stop or destroy this instance. */
	canControl(inst: Instance): boolean {
		return this.isAdmin || inst.owner === this.user.username;
	}

	// Actions ---------------------------------------------------------------------------------------

	#log(inst: Instance, text: string, tone?: LogLine['tone']) {
		inst.log.push({ at: Date.now(), text, tone });
	}

	#startJob(inst: Instance, action: string): Job {
		this.jobs.unshift({
			id: `j-${this.#nextJob++}`,
			instanceId: inst.id,
			lab: inst.lab,
			action,
			by: this.user.username,
			state: 'running',
			startedAt: Date.now(),
		});
		return this.jobs[0];
	}

	#finishJob(job: Job, state: 'done' | 'failed' = 'done') {
		job.state = state;
		job.finishedAt = Date.now();
	}

	async #boot(inst: Instance, lab: Lab) {
		for (const group of bootGroups(lab)) {
			this.#log(inst, `Powering on ${group.join(', ')}`, 'muted');
			for (const name of group) inst.machines[name] = 'booting';
			await sleep(1800);
			for (const name of group) inst.machines[name] = 'running';
			this.#log(inst, `Up: ${group.join(', ')}`);
		}
	}

	#setState(inst: Instance, state: InstanceState) {
		inst.state = state;
	}

	deploy(lab: Lab, hours: number, owner = this.user.username): Instance {
		const inst: Instance = {
			id: `${lab.slug.slice(0, 3)}-${randomId()}`,
			lab: lab.slug,
			kind: 'dedicated',
			owner,
			state: 'deploying',
			startedAt: Date.now(),
			expiresAt: Date.now() + hours * HOUR,
			connected: 0,
			endpoint: `192.0.2.${45 + this.instances.length}:51820`,
			machines: machinesIn(lab, 'stopped'),
			log: [],
		};
		this.instances.push(inst);
		const proxy = this.instances[this.instances.length - 1];
		void this.#runDeploy(proxy, lab, `Deploy requested by ${this.user.username}${owner === this.user.username ? '' : ` for ${owner}`} (${hours} h)`);
		return proxy;
	}

	async #runDeploy(inst: Instance, lab: Lab, first: string) {
		const job = this.#startJob(inst, inst.log.length ? 'Rebuild' : 'Deploy');
		this.#log(inst, first, 'muted');
		await sleep(700);
		this.#log(inst, `Reserved network slot lab-slot-0${this.instances.length} (${lab.networks.length} VLANs)`);
		for (const m of lab.machines) {
			await sleep(350);
			this.#log(inst, `Cloned ${m.name} from ${lab.slug}/${lab.templateVersion}`);
		}
		await sleep(500);
		this.#log(inst, `Gateway configured, WireGuard listening on ${inst.endpoint}`);
		await this.#boot(inst, lab);
		await sleep(500);
		this.#log(inst, "Took baseline snapshot 'clean'");
		inst.lastResetAt = Date.now();
		this.#setState(inst, 'running');
		this.#log(inst, 'Instance ready. Download your VPN config to connect.', 'ok');
		this.#finishJob(job);
	}

	async resetLab(inst: Instance) {
		const lab = findLab(inst.lab)!;
		const job = this.#startJob(inst, 'Reset lab');
		this.#setState(inst, 'resetting');
		this.#log(inst, `Reset requested by ${this.user.username}`, 'muted');
		for (const name of Object.keys(inst.machines)) inst.machines[name] = 'resetting';
		await sleep(1500);
		this.#log(inst, `Reverted ${lab.machines.length} machines to snapshot 'clean'`);
		for (const name of Object.keys(inst.machines)) inst.machines[name] = 'stopped';
		await this.#boot(inst, lab);
		inst.lastResetAt = Date.now();
		this.#setState(inst, 'running');
		this.#log(inst, 'Reset complete. All machines are running.', 'ok');
		this.#finishJob(job);
	}

	async resetMachine(inst: Instance, name: string) {
		const job = this.#startJob(inst, `Reset ${name}`);
		this.#log(inst, `Reset of ${name} requested by ${this.user.username}`, 'muted');
		inst.machines[name] = 'resetting';
		await sleep(1500);
		this.#log(inst, `Reverted ${name} to snapshot 'clean'`);
		inst.machines[name] = 'booting';
		await sleep(1800);
		inst.machines[name] = 'running';
		this.#log(inst, `${name} is up`, 'ok');
		this.#finishJob(job);
	}

	async reboot(inst: Instance, name: string) {
		const job = this.#startJob(inst, `Reboot ${name}`);
		this.#log(inst, `Rebooting ${name}`, 'muted');
		inst.machines[name] = 'booting';
		await sleep(2200);
		inst.machines[name] = 'running';
		this.#log(inst, `${name} is up`, 'ok');
		this.#finishJob(job);
	}

	async power(inst: Instance, name: string, on: boolean) {
		const job = this.#startJob(inst, `Power ${on ? 'on' : 'off'} ${name}`);
		if (on) {
			inst.machines[name] = 'booting';
			await sleep(1800);
			inst.machines[name] = 'running';
			this.#log(inst, `${name} is up`, 'ok');
		} else {
			await sleep(800);
			inst.machines[name] = 'stopped';
			this.#log(inst, `${name} powered off`);
		}
		this.#finishJob(job);
	}

	async stop(inst: Instance) {
		const lab = findLab(inst.lab)!;
		const job = this.#startJob(inst, 'Stop');
		this.#setState(inst, 'stopping');
		this.#log(inst, `Stop requested by ${this.user.username}`, 'muted');
		for (const group of bootGroups(lab).reverse()) {
			await sleep(700);
			for (const name of group) inst.machines[name] = 'stopped';
		}
		this.#setState(inst, 'stopped');
		inst.connected = 0;
		this.#log(inst, 'All machines are off. Start the instance to continue where you left off.');
		this.#finishJob(job);
	}

	async start(inst: Instance) {
		const lab = findLab(inst.lab)!;
		const job = this.#startJob(inst, 'Start');
		this.#setState(inst, 'deploying');
		await this.#boot(inst, lab);
		this.#setState(inst, 'running');
		this.#log(inst, 'All machines are running.', 'ok');
		this.#finishJob(job);
	}

	async rebuild(inst: Instance) {
		const lab = findLab(inst.lab)!;
		this.#setState(inst, 'deploying');
		for (const name of Object.keys(inst.machines)) inst.machines[name] = 'stopped';
		await this.#runDeploy(inst, lab, `Rebuild requested by ${this.user.username}: deleting machines and cloning again`);
	}

	async destroy(inst: Instance) {
		const job = this.#startJob(inst, 'Destroy');
		this.#setState(inst, 'destroying');
		this.#log(inst, `Destroy requested by ${this.user.username}`, 'muted');
		await sleep(2500);
		this.instances = this.instances.filter((i) => i.id !== inst.id);
		this.#finishJob(job);
	}

	extend(inst: Instance, hours: number) {
		if (!inst.expiresAt) return;
		inst.expiresAt += hours * HOUR;
		this.#log(inst, `Extended by ${hours} h by ${this.user.username}`);
	}

	// Single-machine actions ------------------------------------------------------------------------

	#machineLog(m: SingleMachine, text: string, tone?: LogLine['tone']) {
		m.log.push({ at: Date.now(), text, tone });
	}

	#machineJob(m: SingleMachine, action: string): Job {
		this.jobs.unshift({
			id: `j-${this.#nextJob++}`,
			instanceId: '',
			machineId: m.id,
			lab: '',
			action: `${action} ${m.name}`,
			by: this.user.username,
			state: 'running',
			startedAt: Date.now(),
		});
		return this.jobs[0];
	}

	deployMachine(template: MachineTemplate, version: string, name: string, hours: number | null): SingleMachine {
		const used = new Set(this.myMachines.map((m) => m.ip));
		let host = 10;
		while (used.has(`10.99.7.${host}`)) host += 10;
		this.machines.push({
			id: `m-${randomId()}`,
			name,
			template: template.id,
			version,
			owner: this.user.username,
			state: 'deploying',
			createdAt: Date.now(),
			expiresAt: hours === null ? null : Date.now() + hours * HOUR,
			ip: `10.99.7.${host}`,
			log: [],
		});
		const m = this.machines[this.machines.length - 1];
		void this.#runMachineDeploy(m, template, hours);
		return m;
	}

	async #runMachineDeploy(m: SingleMachine, template: MachineTemplate, hours: number | null) {
		const job = this.#machineJob(m, 'Deploy');
		this.#machineLog(m, `Deploy requested by ${this.user.username} (${hours === null ? 'kept permanently' : hours < 24 ? `${hours} h` : `${hours / 24} d`})`, 'muted');
		await sleep(800);
		this.#machineLog(m, `Cloned from ${template.id}/${m.version}`);
		if (template.flags?.includes('domain')) {
			await sleep(600);
			this.#machineLog(m, 'Cloned the domain controller that comes with it');
		}
		await sleep(600);
		this.#machineLog(m, `Joined your network at ${m.ip}`);
		await sleep(2000);
		m.state = 'running';
		this.#machineLog(m, `Ready. ${template.credentials ? `Sign in as ${template.credentials}.` : ''}`, 'ok');
		this.#finishJob(job);
	}

	extendMachine(m: SingleMachine, hours: number) {
		if (m.expiresAt === null) return;
		const wasExpired = m.state === 'expired';
		m.expiresAt = Math.max(m.expiresAt, Date.now()) + hours * HOUR;
		this.#machineLog(m, `Extended by ${hours < 24 ? `${hours} h` : `${hours / 24} d`} by ${this.user.username}`);
		if (wasExpired) {
			m.state = 'stopped';
			void this.startMachine(m);
		}
	}

	keepMachine(m: SingleMachine) {
		if (this.keepBlocker(m)) return;
		m.expiresAt = null;
		if (m.state === 'expired') {
			m.state = 'stopped';
			void this.startMachine(m);
		}
		this.#machineLog(m, `Kept permanently by ${this.user.username}`);
	}

	/** Puts a permanent machine back on the clock. */
	setMachineExpiry(m: SingleMachine, hours: number) {
		m.expiresAt = Date.now() + hours * HOUR;
		this.#machineLog(m, `Expiry set by ${this.user.username}: deleted in ${hours < 24 ? `${hours} h` : `${hours / 24} d`} unless extended`);
	}

	async stopMachine(m: SingleMachine) {
		const job = this.#machineJob(m, 'Stop');
		m.state = 'stopping';
		await sleep(1200);
		m.state = 'stopped';
		this.#machineLog(m, `Stopped by ${this.user.username}`);
		this.#finishJob(job);
	}

	async startMachine(m: SingleMachine) {
		const job = this.#machineJob(m, 'Start');
		m.state = 'deploying';
		await sleep(2000);
		m.state = 'running';
		this.#machineLog(m, 'Running', 'ok');
		this.#finishJob(job);
	}

	async rebootMachine(m: SingleMachine) {
		const job = this.#machineJob(m, 'Reboot');
		m.state = 'deploying';
		this.#machineLog(m, `Rebooting (${this.user.username})`, 'muted');
		await sleep(2200);
		m.state = 'running';
		this.#machineLog(m, 'Running', 'ok');
		this.#finishJob(job);
	}

	async resetMachineToClean(m: SingleMachine) {
		const job = this.#machineJob(m, 'Reset');
		m.state = 'resetting';
		this.#machineLog(m, `Reset requested by ${this.user.username}`, 'muted');
		await sleep(1500);
		this.#machineLog(m, "Reverted to snapshot 'clean'");
		await sleep(1800);
		m.state = 'running';
		this.#machineLog(m, 'Running', 'ok');
		this.#finishJob(job);
	}

	async destroyMachine(m: SingleMachine) {
		const job = this.#machineJob(m, 'Destroy');
		m.state = 'destroying';
		await sleep(2000);
		this.machines = this.machines.filter((x) => x.id !== m.id);
		this.#finishJob(job);
	}

	/** Powers off machines whose time ran out, and deletes them once the grace period passes. */
	#checkExpiry() {
		const now = Date.now();
		for (const m of this.machines) {
			if (m.expiresAt === null || m.expiresAt > now) continue;
			if (m.state === 'running' || m.state === 'stopped') {
				m.state = 'expired';
				this.#machineLog(m, 'Time ran out: powered off. Extend it within a day to keep it.', 'warn');
			}
		}
		const gone = this.machines.filter((m) => m.state === 'expired' && m.expiresAt !== null && m.expiresAt + GRACE <= now);
		if (gone.length) this.machines = this.machines.filter((m) => !gone.includes(m));
	}

	/** Runs a failed deploy again for the person who asked for it. */
	retry(job: Job) {
		const inst = this.deploy(findLab(job.lab)!, 4, job.by);
		job.retriedAs = this.jobs[0].id;
		this.#log(inst, `Retry of ${job.id}`, 'muted');
	}
}

export const store = new LabStore();
export { labs };
