<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import ConfirmDialog, { type ConfirmRequest } from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import OsLogo from '$lib/components/OsLogo.svelte';
	import Status from '$lib/components/Status.svelte';
	import { clock, duration, inWords, isBusy, singleMachineStates } from '$lib/format';
	import { store } from '$lib/store.svelte';
	import { templateFor } from '$lib/templates';

	const HOUR = 3_600_000;

	const i = $derived(store.instance(page.params.id ?? ''));
	const lab = $derived(i ? store.lab(i.lab) : undefined);
	const busy = $derived(i ? i.machines.some((m) => isBusy(m.state)) : true);
	const expired = $derived(i?.state === 'expired');

	let request = $state<ConfirmRequest>();
	let showFlags = $state(false);

	function reset() {
		if (!i) return;
		request = {
			title: `Reset ${i.title}?`,
			body: `Every machine goes back to how it was when the lab was deployed, in order: ${i.machines.map((m) => m.role).join(', then ')}. Everything changed on them is lost.`,
			label: 'Reset lab',
			danger: true,
			run: () => store.resetInstance(i),
		};
	}

	function cancel() {
		if (!i) return;
		request = {
			title: `Cancel what ${i.title} is doing?`,
			body: 'Running jobs stop within a few seconds, and machines waiting their turn are dropped. They are then marked as failed: reset or destroy the lab.',
			label: 'Cancel jobs',
			danger: true,
			run: () => store.cancelInstance(i),
		};
	}

	function destroy() {
		if (!i) return;
		request = {
			title: `Destroy ${i.title}?`,
			body: `All ${i.machines.length} machines and their disks are deleted now. This can't be undone.`,
			label: 'Destroy lab',
			danger: true,
			run: async () => {
				if (await store.destroyInstance(i)) goto('/instances');
			},
		};
	}
</script>

<svelte:head><title>{i?.title ?? 'Instance'} · Codex Labs</title></svelte:head>

{#if !store.loaded}
	<p class="loading">Loading…</p>
{:else if !i}
	<div class="gone">
		<h1>This lab is gone</h1>
		<p>It was destroyed, or it expired and wasn't extended in time.</p>
		<a class="btn btn-primary" href="/labs">See the labs</a>
	</div>
{:else}
	<nav class="breadcrumbs" aria-label="Breadcrumbs">
		<a href="/instances">Instances</a> <span aria-hidden="true">›</span> <span aria-current="page">{i.id}</span>
	</nav>

	<header class="title-row">
		<div>
			<h1>{i.title} <span class="instance-id">{i.id}</span></h1>
			<p class="subtitle">
				<Status {...singleMachineStates[i.state]} />
				<span>{i.machines.length} machines{lab?.domain ? `, domain ${lab.domain}` : ''}</span>
			</p>
		</div>
		<div class="actions">
			{#if busy}
				<button class="btn" type="button" onclick={cancel}><Icon name="stop" /> Cancel jobs</button>
			{/if}
			<button class="btn" type="button" disabled={busy || expired} onclick={reset}><Icon name="reset" /> Reset lab</button>
			<button class="btn btn-danger" type="button" disabled={busy} onclick={destroy}><Icon name="trash" /> Destroy lab</button>
		</div>
	</header>

	{#if i.expiresAt === null}
		<div class="banner"><p><strong>Kept permanently.</strong> It won't expire.</p></div>
	{:else}
		{@const left = i.expiresAt - store.now}
		<div class="banner" class:banner-warn={expired || left < HOUR}>
			<p>
				{#if expired}
					<strong>Expired and powered off.</strong> It's deleted at {clock(i.expiresAt + store.grace, store.now)}, in
					{duration(i.expiresAt + store.grace - store.now)}, unless you extend it.
				{:else}
					Powered off at <strong>{clock(i.expiresAt, store.now)}</strong>, in {duration(left)}, then deleted {inWords(store.grace)} later.
				{/if}
			</p>
			<div class="banner-actions">
				<button class="btn btn-sm" type="button" disabled={busy} onclick={() => store.extendInstance(i, 2)}>
					<Icon name="clock" /> {expired ? 'Extend 2 h and start' : '+2 h'}
				</button>
				<button class="btn btn-sm" type="button" disabled={busy} onclick={() => store.extendInstance(i, 24)}>+1 day</button>
			</div>
		</div>
	{/if}

	<div class="section-heading"><h2>Machines</h2></div>
	<div class="table-wrap">
		<table class="table">
			<thead>
				<tr>
					<th scope="col">Name</th>
					<th scope="col">Role</th>
					<th scope="col">Runs</th>
					<th scope="col">Address</th>
					<th scope="col">State</th>
				</tr>
			</thead>
			<tbody>
				{#each i.machines as m (m.id)}
					{@const t = templateFor(m.template)}
					{@const role = lab?.machines.find((lm) => lm.name === m.role)}
					<tr>
						<th scope="row"><a class="mono" href="/machines/{m.id}">{m.name}</a></th>
						<td>{role?.role || m.role}</td>
						<td><span class="runs"><OsLogo id={t.id} name={t.name} size="sm" /> {t.name} {m.version}</span></td>
						<td class="mono">{m.ip || '–'}</td>
						<td>
							{#if m.pending}
								<Status size="sm" tone="down" label="Waiting its turn" />
							{:else}
								<Status size="sm" {...singleMachineStates[m.state]} />
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<p class="hint">Each machine's page has its sign-in, console and activity.</p>

	{#if i.flags.length}
		<div class="section-heading">
			<h2>Flags</h2>
			<button class="btn btn-quiet btn-sm" type="button" onclick={() => (showFlags = !showFlags)}>
				<Icon name="eye" />{showFlags ? 'Hide values' : 'Show values'}
			</button>
		</div>
		<p class="hint">{i.flags.filter((f) => f.planted).length} of {i.flags.length} planted; new values each deploy and reset.</p>
		<ul class="flags">
			{#each i.flags as f (f.id)}
				<li>
					<span class="flag-dot" data-tone={f.planted ? 'up' : 'down'} title={f.planted ? 'Planted' : 'Not planted yet'}></span>
					<span class="tag">{f.id}</span>
					<span class="flag-where">{f.where}</span>
					{#if showFlags && f.value}<code class="flag-value">{f.value}</code>{/if}
				</li>
			{/each}
		</ul>
	{/if}
{/if}

<ConfirmDialog bind:request />

<style>
	.loading {
		padding-block: 3rem;
		color: var(--lms-gray-3);
	}
	.gone {
		display: grid;
		gap: 1rem;
		justify-items: start;
		padding-block: 3rem;
	}
	.title-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 1rem 1.5rem;
		margin-bottom: 1.5rem;
	}
	.instance-id {
		font: 600 1rem var(--lms-mono);
		color: var(--lms-gray-3);
		vertical-align: middle;
		white-space: nowrap;
	}
	.subtitle {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem 1rem;
		margin-top: 0.4rem;
		color: var(--lms-gray-2);
	}
	.actions,
	.banner-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.banner {
		margin-bottom: 1.25rem;
	}
	.runs {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
	}
	.hint {
		margin-top: 0.5rem;
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}
	.section-heading {
		margin-top: 1.5rem;
	}
	.section-heading {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	.flags {
		display: grid;
		gap: 0.5rem;
		margin: 0.5rem 0 0;
		padding: 0;
		list-style: none;
	}
	.flags li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
	}
	.flag-dot {
		flex-shrink: 0;
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 50%;
		background: var(--lab-up);
	}
	.flag-dot[data-tone='down'] {
		background: transparent;
		box-shadow: inset 0 0 0 2px var(--lms-gray-4);
	}
	.flag-where {
		color: var(--lms-gray-2);
	}
	.flag-value {
		font: 0.85rem var(--lms-mono);
		color: var(--lms-lime-text);
	}
</style>
