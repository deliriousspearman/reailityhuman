<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import ActivityLog from '$lib/components/ActivityLog.svelte';
	import ConfirmDialog, { type ConfirmRequest } from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import OsLogo from '$lib/components/OsLogo.svelte';
	import Status from '$lib/components/Status.svelte';
	import { ago, clock, duration, inWords, isBusy, jobStates, singleMachineStates, tookLabel } from '$lib/format';
	import { api } from '$lib/api';
	import type { Job } from '$lib/types';
	import { store } from '$lib/store.svelte';
	import { flagNotes, templateFor } from '$lib/templates';

	const HOUR = 3_600_000;

	const m = $derived(store.machine(page.params.id ?? ''));
	const t = $derived(m && store.asDeployed(templateFor(m.template), m.version));
	const canControl = $derived(m ? store.canControlMachine(m) : false);
	const busy = $derived(m ? isBusy(m.state) : true);
	const keepBlocker = $derived(m ? store.keepBlocker(m) : null);
	const webUrl = $derived(m && t ? (t.webUrl ?? 'https://{ip}/').replace('{ip}', m.ip) : '');

	// Its log only comes with the machine on its own, so poll that while this page is open.
	$effect(() => {
		store.watch(page.params.id ?? null);
		return () => store.watch(null);
	});

	// This machine's jobs, with any errors in full. Fetched again whenever its state or log changes.
	let jobs = $state<Job[]>([]);
	$effect(() => {
		const id = m?.id;
		void m?.state;
		void m?.log?.length;
		if (!id) return;
		api<Job[]>(`/jobs?machine=${encodeURIComponent(id)}&limit=20`)
			.then((j) => (jobs = j))
			.catch(() => {}); // the layout reports the API being unreachable
	});

	let request = $state<ConfirmRequest>();
	let copied = $state('');
	let showPassword = $state(false);

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = text;
			setTimeout(() => (copied = ''), 1500);
		} catch {}
	}

	/** A warning for confirm dialogs when other machines point at this one (e.g. a server's agents). */
	const usedByWarning = $derived.by(() => {
		const names = (m?.usedBy ?? []).map((d) => d.name);
		if (!names.length) return '';
		const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
		return ` ${list} ${names.length === 1 ? 'uses' : 'use'} this machine and will lose ${names.length === 1 ? 'its' : 'their'} connection to it.`;
	});

	function stop() {
		if (!m) return;
		if (!usedByWarning) {
			void store.stopMachine(m);
			return;
		}
		request = {
			title: `Stop ${m.name}?`,
			body: `${m.name} shuts down.${usedByWarning}`,
			label: 'Stop',
			run: () => store.stopMachine(m),
		};
	}

	function reset() {
		if (!m) return;
		request = {
			title: `Reset ${m.name}?`,
			body: `${m.name} goes back to how it was when it was deployed. Everything you changed or installed on it is lost.${usedByWarning}`,
			label: 'Reset',
			danger: true,
			run: () => store.resetMachineToClean(m),
		};
	}

	function redeploy() {
		if (!m) return;
		request = {
			title: `Redeploy ${m.name}?`,
			body: `${m.name}'s VM is deleted and made again from ${m.template} ${m.version}, with the same name, password and extras. Everything on it is lost.${usedByWarning}`,
			label: 'Redeploy',
			danger: true,
			run: () => store.redeployMachine(m),
		};
	}

	function cancel() {
		if (!m) return;
		request = {
			title: `Cancel what ${m.name} is doing?`,
			body: `The job running on ${m.name} stops within a few seconds, and any waiting are dropped. ${m.name} is then marked as failed: if it was being deployed or reset, redeploy or destroy it.`,
			label: 'Cancel job',
			danger: true,
			run: () => store.cancelMachineJobs(m),
		};
	}

	function destroy() {
		if (!m) return;
		request = {
			title: `Destroy ${m.name}?`,
			body: `${m.name} and its disk are deleted now. This can't be undone.${usedByWarning}`,
			label: 'Destroy',
			danger: true,
			run: async () => {
				// Stay here if it was refused, so the reason shows next to the machine.
				if (await store.destroyMachine(m)) goto('/machines');
			},
		};
	}

	/** A Remote Desktop file for the machine, with its user filled in (the password is asked for). */
	function rdpFile(ip: string, username: string): string {
		const lines = [`full address:s:${ip}`, `username:s:${username}`, 'prompt for credentials:i:1', 'screen mode id:i:1'];
		return `data:application/x-rdp;charset=utf-8,${encodeURIComponent(lines.join('\r\n') + '\r\n')}`;
	}

	let more: HTMLDetailsElement | undefined = $state();
	function fromMenu(action: () => void) {
		more?.removeAttribute('open');
		action();
	}
</script>

<svelte:head><title>{m?.name ?? 'Machine'} · Codex Labs</title></svelte:head>

{#if !store.loaded}
	<p class="loading">Loading…</p>
{:else if !m || !t}
	<div class="gone">
		<h1>This machine is gone</h1>
		<p>It was destroyed, or it expired and wasn't extended in time.</p>
		<a class="btn btn-primary" href="/machines">See your machines</a>
	</div>
{:else}
	<nav class="breadcrumbs" aria-label="Breadcrumbs">
		<a href="/machines">Machines</a> <span aria-hidden="true">›</span> <span aria-current="page">{m.name}</span>
	</nav>

	<header class="title-row">
		<div class="who">
			<OsLogo id={t.id} name={t.name} size="lg" />
			<div>
				<h1>{m.name}</h1>
				<p class="subtitle">
					<Status {...singleMachineStates[m.state]} />
					<span><span class="os" data-os={t.os.toLowerCase()}>{t.os}</span> {t.name} {m.version}</span>
				</p>
			</div>
		</div>

		{#if canControl}
			<div class="actions">
				{#if m.state === 'stopped' || m.state === 'error'}
					<button class="btn btn-primary" type="button" onclick={() => store.startMachine(m)}><Icon name="play" /> Start</button>
				{/if}
				{#if m.state === 'error'}
					<button class="btn" type="button" onclick={redeploy}><Icon name="rebuild" /> Redeploy</button>
				{/if}
				{#if m.state !== 'stopped' && m.state !== 'expired'}
					<button class="btn" type="button" disabled={busy} onclick={stop}><Icon name="stop" /> Stop</button>
				{/if}
				{#if busy}
					<button class="btn" type="button" onclick={cancel}><Icon name="stop" /> Cancel job</button>
				{/if}
				<button class="btn" type="button" disabled={m.state !== 'running'} onclick={() => store.rebootMachine(m)}>
					<Icon name="reboot" /> Reboot
				</button>
				<details class="more" bind:this={more}>
					<summary class="btn">More</summary>
					<div class="more-menu panel">
						<button type="button" disabled={busy || m.state === 'expired'} onclick={() => fromMenu(reset)}><Icon name="reset" /> Reset to clean</button>
						<button type="button" disabled={busy || m.state === 'expired'} onclick={() => fromMenu(redeploy)}><Icon name="rebuild" /> Redeploy</button>
						<a href="/machines/new/{m.template}?from={m.id}"><Icon name="plus" /> Deploy another like this</a>
						<button type="button" class="danger" disabled={busy} onclick={() => fromMenu(destroy)}><Icon name="trash" /> Destroy</button>
					</div>
				</details>
			</div>
		{/if}
	</header>

	<!-- Time left: the thing people most need to act on. -->
	{#if m.expiresAt === null}
		<div class="banner">
			<p><strong>Kept permanently.</strong> It won't expire.</p>
			{#if canControl}
				<button class="btn btn-sm" type="button" onclick={() => store.setMachineExpiry(m, 24)}>
					<Icon name="clock" /> Expire in 1 day instead
				</button>
			{/if}
		</div>
	{:else}
		{@const left = m.expiresAt - store.now}
		{@const expired = m.state === 'expired'}
		<div class="banner" class:banner-warn={expired || left < HOUR}>
			<p>
				{#if expired}
					<strong>Expired and powered off.</strong> It's deleted at {clock(m.expiresAt + store.grace, store.now)}, in
					{duration(m.expiresAt + store.grace - store.now)}, unless you extend it.
				{:else}
					Powered off at <strong>{clock(m.expiresAt, store.now)}</strong>, in {duration(left)}, then deleted {inWords(store.grace)} later.
				{/if}
			</p>
			{#if canControl}
				<div class="banner-actions">
					<button class="btn btn-sm" type="button" onclick={() => store.extendMachine(m, 2)}>
						<Icon name="clock" /> {expired ? 'Extend 2 h and start' : '+2 h'}
					</button>
					<button class="btn btn-sm" type="button" onclick={() => store.extendMachine(m, 24)}>+1 day</button>
					<button class="btn btn-sm" type="button" disabled={!!keepBlocker} title={keepBlocker ?? undefined} onclick={() => store.keepMachine(m)}>
						Keep permanently
					</button>
				</div>
			{/if}
		</div>
		{#if canControl && keepBlocker}<p class="keep-note">{keepBlocker}</p>{/if}
	{/if}

	<dl class="stats">
		<div>
			<dt>Address</dt>
			<dd>
				{#if m.ip}<code>{m.ip}</code>{:else}<span class="waiting">Waiting for one…</span>{/if}
				<span class="stat-note">on the LAN, from DHCP</span>
			</dd>
		</div>
		{#if t.resources.cpu}
			<div>
				<dt>Uses</dt>
				<dd>{m.cpu ?? t.resources.cpu} vCPU, {m.memoryGB ?? t.resources.memoryGB} GB<span class="stat-note">{t.resources.diskGB} GB disk</span></dd>
			</div>
		{/if}
		<div>
			<dt>Deployed</dt>
			<dd>{duration(store.now - m.createdAt)} ago<span class="stat-note">{clock(m.createdAt, store.now)}</span></dd>
		</div>
		<div>
			<dt>Owner</dt>
			<dd>{m.owner}<span class="stat-note">in vCenter: {m.vmName}</span></dd>
		</div>
		<div>
			<dt>Template</dt>
			<dd><code>{t.id}/{m.version}</code></dd>
		</div>
		{#if m.instanceId}
			<div>
				<dt>Lab</dt>
				<dd>
					<a href="/instances/{m.instanceId}">{store.lab(m.lab ?? '')?.title ?? m.lab}</a>
					<span class="stat-note">{m.pending ? 'waiting for the machines before it' : `its ${m.role}`}</span>
				</dd>
			</div>
		{/if}
		{#if m.usedBy?.length}
			<div>
				<dt>Used by</dt>
				<dd>
					{#each m.usedBy as d, i (d.id)}{i ? ', ' : ''}<a href="/machines/{d.id}">{d.name}</a>{/each}
					<span class="stat-note">they point at this machine's address</span>
				</dd>
			</div>
		{/if}
		{#if m.extras.length}
			<div>
				<dt>Extras</dt>
				<dd>
					{m.extras.map((x) => x.name).join(', ')}
					{#each m.extras as x (x.id)}
						{#each Object.entries(x.options).filter(([, v]) => v) as [k, v] (k)}
							<span class="stat-note">{k === 'domain' ? 'for' : `${k}:`} <code>{v}</code></span>
						{/each}
					{/each}
				</dd>
			</div>
		{/if}
	</dl>

	<div class="section-heading">
		<h2>Sign in</h2>
	</div>
	<ul class="ways">
		<li>
			<span class="way">Account</span>
			<span class="cmd">
				{m.username} /
				{#if showPassword}{m.password}{:else}<span aria-label="password hidden">••••••••••••</span>{/if}
			</span>
			<button class="btn btn-quiet btn-sm" type="button" onclick={() => (showPassword = !showPassword)}>
				<Icon name="eye" />{showPassword ? 'Hide' : 'Show'}
			</button>
			<!-- The password comes with the machine's own poll, a moment after the list. -->
			<button class="btn btn-quiet btn-sm" type="button" disabled={!m.password} onclick={() => copy(m.password ?? '')}>
				<Icon name="copy" />{copied === m.password ? 'Copied' : 'Copy password'}
			</button>
		</li>
		{#if t.access.includes('web') && m.ip}
			<li>
				<span class="way">Web interface</span>
				<a class="cmd" href={webUrl} target="_blank" rel="noreferrer">{webUrl}</a>
			</li>
		{/if}
		{#each m.extras.filter((x) => x.links.length || x.notes.length) as x (x.id)}
			<li class="extra-way">
				<span class="way">{x.name}</span>
				<div class="extra-details">
					{#each x.links as url (url)}
						<a class="cmd" href={url} target="_blank" rel="noreferrer">{url}</a>
					{/each}
					{#if x.links.some((url) => url.startsWith('https'))}
						<span class="cmd muted">Self-signed certificate: your browser will warn first</span>
					{/if}
					{#each x.notes as note (note)}
						<span class="note">{note}</span>
					{/each}
				</div>
			</li>
		{/each}
		{#if t.access.includes('ssh') && m.ip}
			{@const cmd = `ssh ${m.username}@${m.ip}`}
			<li>
				<span class="way">SSH</span>
				<code class="cmd">{cmd}</code>
				<button class="btn btn-quiet btn-sm" type="button" onclick={() => copy(cmd)}><Icon name="copy" />{copied === cmd ? 'Copied' : 'Copy'}</button>
			</li>
		{/if}
		{#if t.access.includes('rdp') && m.ip}
			{@const cmd = `mstsc /v:${m.ip}`}
			<li>
				<span class="way">Remote Desktop</span>
				<code class="cmd">{cmd}</code>
				<button class="btn btn-quiet btn-sm" type="button" onclick={() => copy(cmd)}><Icon name="copy" />{copied === cmd ? 'Copied' : 'Copy'}</button>
				<a class="btn btn-quiet btn-sm" href={rdpFile(m.ip, m.username)} download="{m.name}.rdp"><Icon name="download" />.rdp file</a>
			</li>
		{/if}
		{#if t.access.includes('console')}
			<li>
				<span class="way">Console</span>
				<span class="cmd muted">In the browser, for first-time setup and when the network is down</span>
				{#if m.state === 'stopped' || m.state === 'expired'}
					<button class="btn btn-sm" type="button" disabled title="Start the machine first"><Icon name="console" /> Open console</button>
				{:else}
					<a class="btn btn-sm" href="/machines/{m.id}/console"><Icon name="console" /> Open console</a>
					<a class="btn btn-quiet btn-sm" href="/machines/{m.id}/console?view=tab" target="_blank" rel="noopener" title="Just the screen, full size, in a new browser tab">
						<Icon name="external" /> New tab
					</a>
				{/if}
			</li>
		{/if}
	</ul>
	{#if t.flags?.length}
		<ul class="flag-notes">
			{#each t.flags as f (f)}
				<li><span class="tag">{flagNotes[f].label}</span> {flagNotes[f].note}</li>
			{/each}
		</ul>
	{/if}

	<div class="lower">
		<section class="vpn" aria-labelledby="vpn-title">
			<div class="section-heading">
				<h2 id="vpn-title">Your network <span class="soon-tag">Soon</span></h2>
			</div>
			<div class="vpn-panel panel">
				<p>
					Later, your machines will share a private network of their own, reached over a VPN. For now they sit on the LAN:
					connect to the address above directly.
				</p>
				<button class="btn btn-sm" type="button" disabled><Icon name="download" /> Download VPN config</button>
			</div>
		</section>
		<section aria-labelledby="activity-title">
			<div class="section-heading">
				<h2 id="activity-title">Activity</h2>
			</div>
			<ActivityLog lines={m.log ?? []} title="machines/{m.name}" />
			{#if jobs.length}
				<div class="section-heading">
					<h2>Jobs</h2>
				</div>
				<ul class="jobs">
					{#each jobs as job (job.id)}
						<li>
							<Status size="sm" {...jobStates[job.state]} />
							<span class="job-action">{job.action}</span>
							<span class="job-meta">by {job.by}, {ago(job.queuedAt, store.now)}, {tookLabel(job, store.now)}</span>
							{#if job.detail}<pre class="job-error">{job.detail}</pre>{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	</div>
{/if}

<ConfirmDialog bind:request />

<style>
	.who {
		display: flex;
		align-items: center;
		gap: 1rem;
		min-width: 0;
	}
	.breadcrumbs {
		margin-bottom: 1.25rem;
		font-size: 0.875rem;
		color: var(--lms-gray-4);
	}
	.breadcrumbs a {
		color: var(--lms-gray-2);
		text-decoration: none;
	}
	.breadcrumbs a:hover {
		color: var(--lms-white);
		text-decoration: underline;
	}
	.breadcrumbs span {
		margin-inline: 0.35rem;
	}
	.breadcrumbs [aria-current='page'] {
		margin: 0;
		color: var(--lms-white);
		font-weight: 600;
	}

	.title-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 1rem 1.5rem;
		margin-bottom: 1.5rem;
	}
	h1 {
		font-family: var(--lms-mono);
	}
	.subtitle {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem 1rem;
		margin-top: 0.4rem;
		color: var(--lms-gray-2);
	}
	.subtitle .os {
		margin-inline-end: 0.3rem;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.more {
		position: relative;
	}
	.more summary {
		list-style: none;
	}
	.more summary::-webkit-details-marker {
		display: none;
	}
	.more-menu {
		position: absolute;
		right: 0;
		top: calc(100% + 0.4rem);
		z-index: 5;
		display: grid;
		min-width: 12rem;
		padding: 0.35rem;
		box-shadow: 0 1rem 2rem -0.5rem rgb(0 0 0 / 0.45);
	}
	.more-menu button,
	.more-menu a {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.55rem 0.7rem;
		border: 0;
		border-radius: var(--lms-radius-xs);
		background: none;
		color: var(--lms-gray-1);
		font: 600 0.9rem var(--lms-font);
		text-align: start;
		text-decoration: none;
		cursor: pointer;
	}
	.more-menu a:hover,
	.more-menu button:hover:not(:disabled) {
		background: var(--lms-panel-2);
	}
	.more-menu button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.more-menu .danger {
		color: var(--lms-hard);
	}

	.banner {
		margin-bottom: 0.5rem;
	}
	.banner-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.keep-note {
		margin-bottom: 0.5rem;
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
	.stats {
		margin-top: 1.25rem;
	}

	.ways {
		display: grid;
		margin: 0;
		padding: 0;
		list-style: none;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-md);
	}
	.ways li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1rem;
		padding: 0.6rem 0.85rem;
		border-bottom: 1px solid var(--lms-gray-5);
	}
	.ways li:last-child {
		border-bottom: none;
	}
	.way {
		width: 9rem;
		font-weight: 600;
		color: var(--lms-white);
	}
	/* At least 12rem, so on phones it wraps to its own line rather than being squeezed by the buttons. */
	.cmd {
		flex: 1 1 12rem;
		min-width: 0;
		font: 0.85rem var(--lms-mono);
		color: var(--lms-lime-text);
		overflow-wrap: anywhere;
	}
	.cmd.muted {
		font-family: var(--lms-font);
		color: var(--lms-gray-3);
	}
	.extra-way {
		align-items: flex-start;
	}
	.extra-details {
		display: grid;
		gap: 0.3rem;
		flex: 1 1 12rem;
		min-width: 0;
	}
	.extra-details .note {
		font-size: 0.85rem;
		color: var(--lms-gray-2);
	}
	.flag-notes {
		display: grid;
		gap: 0.4rem;
		margin: 0.9rem 0 0;
		padding: 0;
		list-style: none;
		font-size: 0.85rem;
	}
	.flag-notes .tag {
		margin-inline-end: 0.3rem;
	}

	.lower {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 0 2rem;
		margin-top: 1rem;
	}
	.lower > :global(*) {
		margin-top: 1.25rem;
	}
	.lower .section-heading {
		margin-top: 0;
	}
	@media (min-width: 64rem) {
		.lower {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		}
	}
	.loading {
		padding-block: 3rem;
		color: var(--lms-gray-3);
	}
	.waiting {
		color: var(--lms-gray-3);
		font-size: 0.9rem;
	}
	.vpn-panel {
		display: grid;
		gap: 0.9rem;
		justify-items: start;
		padding: 1rem 1.1rem;
		border-style: dashed;
		color: var(--lms-gray-3);
		font-size: 0.9rem;
	}
	.vpn h2 .soon-tag {
		vertical-align: middle;
	}
	.jobs {
		display: grid;
		margin: 0;
		padding: 0;
		list-style: none;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-md);
	}
	.jobs li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem 0.75rem;
		padding: 0.5rem 0.85rem;
		border-bottom: 1px solid var(--lms-gray-5);
		font-size: 0.875rem;
	}
	.jobs li:last-child {
		border-bottom: none;
	}
	.job-action {
		font-weight: 600;
		color: var(--lms-white);
	}
	.job-meta {
		font: 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.job-error {
		flex-basis: 100%;
		max-height: 10rem;
		margin: 0.25rem 0 0;
		overflow: auto;
		font: 0.8rem/1.6 var(--lms-mono);
		color: var(--lab-error);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.gone {
		display: grid;
		gap: 1rem;
		justify-items: start;
		max-width: 32rem;
		padding-block: 3rem;
	}
</style>
