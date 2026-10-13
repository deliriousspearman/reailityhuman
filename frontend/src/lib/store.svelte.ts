// Single machines, jobs and capacity from the API, kept fresh by polling. Actions call the API and
// put the machine it returns straight into the list, so the page reacts before the next poll; the
// worker's progress (log lines, state changes) arrives with the polls.
// There's no sign-in yet, so every machine is everyone's.
import { api, ApiError, setActor } from './api';
import type { Capacity, ExtraChoice, Job, MachineTemplate, PanelConfig, SingleMachine } from './types';

const SEC = 1000;
const HOUR = 3600 * SEC;
/** How often to poll while the tab is visible, and while it's hidden. */
const POLL = 3 * SEC;
const POLL_HIDDEN = 15 * SEC;
/** Where the browser remembers who you are (no sign-in yet). */
const USER_KEY = 'lab-deploy:user';
/** The API's rule for owner names (backend/app/api.py). */
export const OWNER_RULE = /^[a-z][a-z0-9-]{0,19}$/;

export interface Notice {
	text: string;
	tone: 'error' | 'ok';
}

class PanelStore {
	machines = $state<SingleMachine[]>([]);
	jobs = $state<Job[]>([]);
	config = $state<PanelConfig | null>(null);
	capacity = $state<Capacity | null>(null);
	/** Why capacity couldn't be read (e.g. vCenter isn't configured). */
	capacityProblem = $state<string | null>(null);
	/** False until the first poll answers, so pages can say "loading" rather than "none". */
	loaded = $state(false);
	/** Set while the API can't be reached; cleared by the next poll that works. */
	offline = $state<string | null>(null);
	/** A message about the last action, shown by the layout. */
	notice = $state<Notice | null>(null);
	/** Ticks every second, for countdowns and uptimes. */
	now = $state(Date.now());
	/** Your name, as typed when you last deployed; '' until then. Stands in for signing in. */
	user = $state('');

	#lastPoll = 0;
	#noticeTimer: ReturnType<typeof setTimeout> | undefined;

	constructor() {
		if (typeof window === 'undefined') return;
		try {
			this.setUser(localStorage.getItem(USER_KEY) ?? '', false);
		} catch {}
		void this.loadConfig();
		void this.refresh();
		setInterval(() => {
			this.now = Date.now();
			const every = document.visibilityState === 'visible' ? POLL : POLL_HIDDEN;
			if (this.now - this.#lastPoll >= every) void this.refresh();
		}, SEC);
		document.addEventListener('visibilitychange', () => {
			if (document.visibilityState === 'visible') void this.refresh();
		});
	}

	async loadConfig() {
		try {
			this.config = await api<PanelConfig>('/config');
		} catch {
			// refresh() reports the API being unreachable.
		}
	}

	async refresh() {
		this.#lastPoll = Date.now();
		try {
			const [machines, jobs] = await Promise.all([api<SingleMachine[]>('/machines'), api<Job[]>('/jobs?limit=50')]);
			this.machines = machines;
			this.jobs = jobs;
			this.offline = null;
			this.loaded = true;
			if (!this.config) void this.loadConfig();
		} catch (e) {
			this.offline = e instanceof Error ? e.message : String(e);
		}
	}

	async refreshCapacity() {
		try {
			this.capacity = await api<Capacity>('/capacity');
			this.capacityProblem = null;
		} catch (e) {
			this.capacityProblem = e instanceof Error ? e.message : String(e);
		}
	}

	/** Remembers who you are in this browser. */
	setUser(name: string, remember = true) {
		const clean = name.trim().toLowerCase();
		if (clean && !OWNER_RULE.test(clean)) return;
		this.user = clean;
		setActor(clean);
		if (!remember) return;
		try {
			if (clean) localStorage.setItem(USER_KEY, clean);
			else localStorage.removeItem(USER_KEY);
		} catch {}
	}

	say(text: string, tone: Notice['tone'] = 'error') {
		this.notice = { text, tone };
		clearTimeout(this.#noticeTimer);
		this.#noticeTimer = setTimeout(() => (this.notice = null), 8 * SEC);
	}

	// Reading -----------------------------------------------------------------------------------------

	/** How long an expired machine is kept, powered off, before it's deleted. */
	get grace() {
		return this.config?.graceMs ?? 24 * HOUR;
	}

	/** Machines deployed under your name; everyone's until you've given one. */
	get myMachines(): SingleMachine[] {
		return this.user ? this.machines.filter((m) => m.owner === this.user) : this.machines;
	}

	get machineQuota() {
		return this.config?.maxMachines ?? 0;
	}

	get permanentQuota() {
		return this.config?.maxPermanent ?? 0;
	}

	get permanentCount() {
		return this.machines.filter((m) => m.expiresAt === null).length;
	}

	machine(id: string): SingleMachine | undefined {
		return this.machines.find((m) => m.id === id);
	}

	canControlMachine(_m: SingleMachine): boolean {
		return true;
	}

	/** Whether this template (or this version of it) can be deployed yet. */
	isLive(templateId: string, version?: string): boolean {
		return !!this.config?.templates.some((t) => t.template === templateId && (version === undefined || t.version === version));
	}

	/** Extras this version of a template offers. */
	extrasFor(templateId: string, version: string) {
		return this.config?.templates.find((t) => t.template === templateId && t.version === version)?.extras ?? [];
	}

	/** An option's default for a machine of this name, as the API will fill it in. */
	optionDefault(def: string, name: string): string {
		const domain = this.config?.machineDomain;
		return def.replace('{fqdn}', domain ? `${name}.${domain}` : name).replace('{hostname}', name);
	}

	/** Why this template can't be deployed right now, or null if it can. */
	machineBlocker(template: MachineTemplate): string | null {
		if (!this.config) return 'Loading…';
		if (!this.isLive(template.id)) return `${template.name} isn't available yet.`;
		if (!this.config.vcenterConfigured) return "vCenter isn't set up yet, so nothing can be deployed. An admin needs to configure it.";
		if (this.machines.length >= this.machineQuota) {
			return `There can be ${this.machineQuota} machines at a time. Destroy one to deploy another.`;
		}
		return null;
	}

	/** Why this machine can't be kept permanently, or null if it can. */
	keepBlocker(m: SingleMachine): string | null {
		if (m.expiresAt === null) return null;
		if (this.permanentCount >= this.permanentQuota) {
			return `${this.permanentQuota === 1 ? 'One machine' : `${this.permanentQuota} machines`} can be kept permanently. Set an expiry on another one first.`;
		}
		return null;
	}

	// Actions -----------------------------------------------------------------------------------------

	#put(m: SingleMachine) {
		const i = this.machines.findIndex((x) => x.id === m.id);
		if (i === -1) this.machines.push(m);
		else this.machines[i] = m;
	}

	/** Runs an action on a machine; failures are shown as a notice rather than thrown. */
	async #act(m: SingleMachine, path: string, init: { method?: string; body?: unknown } = { method: 'POST' }) {
		try {
			this.#put(await api<SingleMachine>(`/machines/${m.id}${path}`, init));
		} catch (e) {
			this.say(e instanceof ApiError ? e.message : String(e));
		}
		void this.refresh();
	}

	/** Deploys a machine. Throws ApiError with a message to show if the API refuses. */
	async deployMachine(
		template: MachineTemplate,
		version: string,
		name: string,
		hours: number | null,
		sshKey: string | undefined,
		extras: ExtraChoice[],
		owner: string,
	): Promise<SingleMachine> {
		this.setUser(owner);
		const m = await api<SingleMachine>('/machines', {
			method: 'POST',
			body: { template: template.id, version, name, hours, sshKey: sshKey?.trim() || null, extras, owner: this.user },
		});
		this.#put(m);
		void this.refresh();
		return m;
	}

	extendMachine(m: SingleMachine, hours: number) {
		return this.#act(m, '/extend', { method: 'POST', body: { hours } });
	}

	keepMachine(m: SingleMachine) {
		return this.#act(m, '/keep');
	}

	/** Puts a permanent machine back on the clock. */
	setMachineExpiry(m: SingleMachine, hours: number) {
		return this.#act(m, '/expiry', { method: 'POST', body: { hours } });
	}

	stopMachine(m: SingleMachine) {
		return this.#act(m, '/stop');
	}

	startMachine(m: SingleMachine) {
		return this.#act(m, '/start');
	}

	rebootMachine(m: SingleMachine) {
		return this.#act(m, '/reboot');
	}

	resetMachineToClean(m: SingleMachine) {
		return this.#act(m, '/reset');
	}

	destroyMachine(m: SingleMachine) {
		return this.#act(m, '', { method: 'DELETE' });
	}
}

export const store = new PanelStore();
