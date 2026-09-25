<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import AccessPanel from '$lib/components/AccessPanel.svelte';
	import ActivityLog from '$lib/components/ActivityLog.svelte';
	import ConfirmDialog, { type ConfirmRequest } from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import Status from '$lib/components/Status.svelte';
	import { clock, duration, singleMachineStates } from '$lib/format';
	import { GRACE, store } from '$lib/mock/store.svelte';
	import { findTemplate, flagNotes } from '$lib/mock/templates';

	const HOUR = 3_600_000;

	const m = $derived(store.machine(page.params.id ?? ''));
	const t = $derived(m && findTemplate(m.template));
	const canControl = $derived(m ? store.canControlMachine(m) : false);
	const busy = $derived(m ? !['running', 'stopped', 'expired'].includes(m.state) : true);
	const keepBlocker = $derived(m ? store.keepBlocker(m) : null);
	/** The SSH user: the template's, or the user in credentials like "admin / pfsense". */
	const user = $derived(t?.sshUser ?? t?.credentials?.split(' / ')[0].replace(/^.*\\/, '') ?? 'root');
	const webUrl = $derived(m && t ? (t.webUrl ?? 'https://{ip}/').replace('{ip}', m.ip) : '');

	let request = $state<ConfirmRequest>();
	let copied = $state('');

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = text;
			setTimeout(() => (copied = ''), 1500);
		} catch {}
	}

	function reset() {
		if (!m) return;
		request = {
			title: `Reset ${m.name}?`,
			body: `${m.name} goes back to how it was when it was deployed. Everything you changed or installed on it is lost.`,
			label: 'Reset',
			danger: true,
			run: () => store.resetMachineToClean(m),
		};
	}

	function destroy() {
		if (!m) return;
		request = {
			title: `Destroy ${m.name}?`,
			body: `${m.name} and its disk are deleted now. This can't be undone.`,
			label: 'Destroy',
			danger: true,
			run: async () => {
				await store.destroyMachine(m);
				goto('/machines');
			},
		};
	}

	let more: HTMLDetailsElement | undefined = $state();
	function fromMenu(action: () => void) {
		more?.removeAttribute('open');
		action();
	}
</script>

<svelte:head><title>{m?.name ?? 'Machine'} · Codex Labs</title></svelte:head>

{#if !m || !t}
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
		<div>
			<h1>{m.name}</h1>
			<p class="subtitle">
				<Status {...singleMachineStates[m.state]} />
				<span><span class="os" data-os={t.os.toLowerCase()}>{t.os}</span> {t.name} {m.version}</span>
				{#if m.owner !== store.user.username}<span>Owned by {m.owner}</span>{/if}
			</p>
		</div>

		{#if canControl}
			<div class="actions">
				{#if m.state === 'stopped'}
					<button class="btn btn-primary" type="button" onclick={() => store.startMachine(m)}><Icon name="play" /> Start</button>
				{:else if m.state !== 'expired'}
					<button class="btn" type="button" disabled={busy} onclick={() => store.stopMachine(m)}><Icon name="stop" /> Stop</button>
				{/if}
				<button class="btn" type="button" disabled={m.state !== 'running'} onclick={() => store.rebootMachine(m)}>
					<Icon name="reboot" /> Reboot
				</button>
				<details class="more" bind:this={more}>
					<summary class="btn">More</summary>
					<div class="more-menu panel">
						<button type="button" disabled={m.state !== 'running'} onclick={() => fromMenu(reset)}><Icon name="reset" /> Reset to clean</button>
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
					<strong>Expired and powered off.</strong> It's deleted at {clock(m.expiresAt + GRACE, store.now)}, in
					{duration(m.expiresAt + GRACE - store.now)}, unless you extend it.
				{:else}
					Powered off at <strong>{clock(m.expiresAt, store.now)}</strong>, in {duration(left)}, then deleted a day later.
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
			<dd><code>{m.ip}</code><span class="stat-note">your network {store.network.cidr}</span></dd>
		</div>
		<div>
			<dt>Uses</dt>
			<dd>{t.resources.cpu} vCPU, {t.resources.memoryGB} GB<span class="stat-note">{t.resources.diskGB} GB disk</span></dd>
		</div>
		<div>
			<dt>Deployed</dt>
			<dd>{duration(store.now - m.createdAt)} ago<span class="stat-note">{clock(m.createdAt, store.now)}</span></dd>
		</div>
		<div>
			<dt>Template</dt>
			<dd><code>{t.id}/{m.version}</code></dd>
		</div>
	</dl>

	<div class="section-heading">
		<h2>Sign in</h2>
		{#if t.credentials}<p>First sign-in: <code>{t.credentials}</code></p>{/if}
	</div>
	<ul class="ways">
		{#if t.access.includes('web')}
			<li>
				<span class="way">Web interface</span>
				<a class="cmd" href={webUrl} target="_blank" rel="noreferrer">{webUrl}</a>
			</li>
		{/if}
		{#if t.access.includes('ssh')}
			{@const cmd = `ssh ${user}@${m.ip}`}
			<li>
				<span class="way">SSH</span>
				<code class="cmd">{cmd}</code>
				<button class="btn btn-quiet btn-sm" type="button" onclick={() => copy(cmd)}><Icon name="copy" />{copied === cmd ? 'Copied' : 'Copy'}</button>
			</li>
		{/if}
		{#if t.access.includes('rdp')}
			{@const cmd = `mstsc /v:${m.ip}`}
			<li>
				<span class="way">Remote Desktop</span>
				<code class="cmd">{cmd}</code>
				<button class="btn btn-quiet btn-sm" type="button" onclick={() => copy(cmd)}><Icon name="copy" />{copied === cmd ? 'Copied' : 'Copy'}</button>
			</li>
		{/if}
		{#if t.access.includes('console')}
			<li>
				<span class="way">Console</span>
				<span class="cmd muted">In the browser, for first-time setup and when the network is down</span>
				<button class="btn btn-sm" type="button" disabled title="Planned"><Icon name="console" /> Open console</button>
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
		<AccessPanel
			fileName="{store.user.username}-network.conf"
			label="personal network"
			endpoint={store.network.endpoint}
			cidr={store.network.cidr}
			ready={true}
			lab={false}
		/>
		<section aria-labelledby="activity-title">
			<div class="section-heading">
				<h2 id="activity-title">Activity</h2>
			</div>
			<ActivityLog lines={m.log} title="machines/{m.name}" />
		</section>
	</div>
{/if}

<ConfirmDialog bind:request />

<style>
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
	.more-menu button {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.55rem 0.7rem;
		border: 0;
		border-radius: 4px;
		background: none;
		color: var(--lms-gray-1);
		font: 600 0.9rem var(--lms-font);
		text-align: start;
		cursor: pointer;
	}
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

	.section-heading code {
		color: var(--lms-lime-text);
	}
	.ways {
		display: grid;
		margin: 0;
		padding: 0;
		list-style: none;
		border: 1px solid var(--lms-gray-5);
		border-radius: 8px;
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
	.cmd {
		flex: 1;
		min-width: 0;
		font: 0.85rem var(--lms-mono);
		color: var(--lms-lime-text);
		overflow-wrap: anywhere;
	}
	.cmd.muted {
		font-family: var(--lms-font);
		color: var(--lms-gray-3);
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
	.gone {
		display: grid;
		gap: 1rem;
		justify-items: start;
		max-width: 32rem;
		padding-block: 3rem;
	}
</style>
