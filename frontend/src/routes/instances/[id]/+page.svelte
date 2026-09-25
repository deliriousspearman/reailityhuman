<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import AccessPanel from '$lib/components/AccessPanel.svelte';
	import ActivityLog from '$lib/components/ActivityLog.svelte';
	import ConfirmDialog, { type ConfirmRequest } from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import MachinePanel from '$lib/components/MachinePanel.svelte';
	import NetworkMap from '$lib/components/NetworkMap.svelte';
	import Status from '$lib/components/Status.svelte';
	import { ago, clock, duration, instanceStates } from '$lib/format';
	import { findLab } from '$lib/mock/labs';
	import { store } from '$lib/mock/store.svelte';

	const instance = $derived(store.instance(page.params.id ?? ''));
	const lab = $derived(instance && findLab(instance.lab));

	let selected = $state<string>();
	let request = $state<ConfirmRequest>();

	const HOUR = 3_600_000;
	const whose = $derived(
		!instance
			? ''
			: instance.kind === 'shared'
				? 'Shared instance'
				: instance.owner === store.user.username
					? 'Your copy'
					: `${instance.owner}'s copy`,
	);
	const busy = $derived(instance ? instance.state !== 'running' && instance.state !== 'stopped' : true);
	const canControl = $derived(instance ? store.canControl(instance) : false);
	const othersConnected = $derived(
		instance && instance.kind === 'shared' && instance.connected > 0
			? ` ${instance.connected} learners are connected and lose their progress on every machine.`
			: '',
	);

	function resetLab() {
		if (!instance || !lab) return;
		request = {
			title: `Reset ${lab.title}?`,
			body: `All ${lab.machines.length} machines go back to their clean snapshots and start again in boot order. This takes a couple of minutes.${othersConnected}`,
			label: 'Reset lab',
			danger: true,
			run: () => store.resetLab(instance),
		};
	}

	function stop() {
		if (!instance || !lab) return;
		request = {
			title: `Stop ${lab.title}?`,
			body: `Every machine is shut down. Nothing is lost: start the instance again to carry on where you left off.${othersConnected}`,
			label: 'Stop',
			run: () => store.stop(instance),
		};
	}

	function rebuild() {
		if (!instance || !lab) return;
		request = {
			title: `Rebuild ${lab.title}?`,
			body: `The machines are deleted and cloned again from template ${lab.slug}/${lab.templateVersion}. Use this when a reset doesn't fix a problem.${othersConnected}`,
			label: 'Rebuild',
			danger: true,
			run: () => store.rebuild(instance),
		};
	}

	function destroy() {
		if (!instance || !lab) return;
		request = {
			title: `Destroy ${lab.title}?`,
			body: `The machines and their network are deleted and connection files stop working. This can't be undone.${othersConnected}`,
			label: 'Destroy',
			danger: true,
			run: async () => {
				await store.destroy(instance);
				goto('/');
			},
		};
	}

	let more: HTMLDetailsElement | undefined = $state();
	function fromMenu(action: () => void) {
		more?.removeAttribute('open');
		action();
	}
</script>

<svelte:head><title>{lab ? `${lab.title} · ${whose}` : 'Instance'} · Codex Labs</title></svelte:head>

{#if !instance || !lab}
	<div class="gone">
		<h1>This instance is gone</h1>
		<p>It was destroyed or it expired. Start a new one from its lab page.</p>
		<a class="btn btn-primary" href="/">Browse Pro Labs</a>
	</div>
{:else}
	<nav class="breadcrumbs" aria-label="Breadcrumbs">
		<ol>
			<li><a href="/">Pro Labs</a></li>
			<li><a href="/labs/{lab.slug}">{lab.title}</a></li>
			<li aria-current="page">{whose}</li>
		</ol>
	</nav>

	<header class="title-row">
		<div class="title-with-picture">
			<img class="picture" src={lab.image} alt="" width="72" height="72" />
			<div>
				<h1>{lab.title}</h1>
				<p class="subtitle">
					<Status {...instanceStates[instance.state]} />
					<span>{whose}</span>
				</p>
			</div>
		</div>

		{#if canControl}
			<div class="actions">
				<button class="btn btn-danger" type="button" disabled={instance.state !== 'running'} onclick={resetLab}>
					<Icon name="reset" /> Reset lab
				</button>
				{#if instance.state === 'stopped'}
					<button class="btn btn-primary" type="button" onclick={() => store.start(instance)}>
						<Icon name="play" /> Start
					</button>
				{:else}
					<button class="btn" type="button" disabled={busy} onclick={stop}><Icon name="stop" /> Stop</button>
				{/if}
				<details class="more" bind:this={more}>
					<summary class="btn">More</summary>
					<div class="more-menu panel">
						<button type="button" disabled={busy} onclick={() => fromMenu(rebuild)}><Icon name="rebuild" /> Rebuild from template</button>
						<button type="button" class="danger" disabled={busy} onclick={() => fromMenu(destroy)}><Icon name="trash" /> Destroy</button>
					</div>
				</details>
			</div>
		{/if}
	</header>

	{#if instance.expiresAt}
		{@const left = instance.expiresAt - store.now}
		<div class="banner" class:banner-warn={left < HOUR}>
			<p>
				{#if instance.owner === store.user.username}Your copy{:else}This copy{/if} is deleted at
				<strong>{clock(instance.expiresAt, store.now)}</strong>, in {duration(left)}.
				{#if left < HOUR}Extend it to keep working.{/if}
			</p>
			{#if canControl}
				<button class="btn btn-sm" type="button" onclick={() => store.extend(instance, 2)}>
					<Icon name="clock" /> Extend by 2 h
				</button>
			{/if}
		</div>
	{:else if instance.nextResetAt && instance.nextResetAt - store.now < HOUR}
		<div class="banner banner-warn">
			<p>
				Scheduled reset at <strong>{clock(instance.nextResetAt, store.now)}</strong>, in
				{duration(instance.nextResetAt - store.now)}. Save anything you need before then.
			</p>
		</div>
	{/if}

	<dl class="stats">
		<div>
			<dt>Connected</dt>
			<dd>{instance.connected}<span class="stat-note">{instance.connected === 1 ? 'learner' : 'learners'}</span></dd>
		</div>
		<div>
			<dt>Up for</dt>
			<dd>{duration(store.now - instance.startedAt)}<span class="stat-note">since {clock(instance.startedAt, store.now)}</span></dd>
		</div>
		<div>
			<dt>Last reset</dt>
			<dd>
				{instance.lastResetAt ? ago(instance.lastResetAt, store.now) : 'Never'}
				{#if lab.resetSchedule && instance.kind === 'shared'}<span class="stat-note">{lab.resetSchedule}</span>{/if}
			</dd>
		</div>
		<div>
			<dt>Template</dt>
			<dd><code>{lab.slug}/{lab.templateVersion}</code><span class="stat-note">{lab.machines.length} machines</span></dd>
		</div>
	</dl>

	<div class="section-heading">
		<h2>Network</h2>
		<p>{canControl ? 'Select a machine to reset or reboot it' : 'Select a machine for its details'}</p>
	</div>
	<div class="map-row">
		<NetworkMap {lab} {instance} bind:selected />
		{#if selected}
			<MachinePanel {lab} {instance} name={selected} confirm={(r) => (request = r)} onclose={() => (selected = undefined)} />
		{/if}
	</div>

	<div class="lower">
		<AccessPanel {lab} {instance} />
		<section aria-labelledby="activity-title">
			<div class="section-heading">
				<h2 id="activity-title">Activity</h2>
			</div>
			<ActivityLog lines={instance.log} title="{lab.slug}/{instance.id}" />
		</section>
	</div>
{/if}

<ConfirmDialog bind:request />

<style>
	.breadcrumbs ol {
		display: flex;
		flex-wrap: wrap;
		margin: 0 0 1.25rem;
		padding: 0;
		list-style: none;
		font-size: 0.875rem;
	}
	.breadcrumbs li {
		color: var(--lms-gray-3);
	}
	.breadcrumbs li + li::before {
		content: '›';
		margin-inline: 0.5rem;
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
	.breadcrumbs [aria-current='page'] {
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
	.title-with-picture {
		display: flex;
		align-items: center;
		gap: 1.25rem;
	}
	.picture {
		width: 4.5rem;
		height: 4.5rem;
		border-radius: 10px;
		border: 1px solid var(--lms-gray-5);
		background: #0d1420;
	}
	.subtitle {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem 1rem;
		margin-top: 0.4rem;
		color: var(--lms-gray-2);
	}
	@media (max-width: 40rem) {
		.picture {
			width: 3.5rem;
			height: 3.5rem;
		}
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
		min-width: 14rem;
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
		margin-bottom: 1.25rem;
	}

	.map-row {
		display: grid;
		gap: 1rem;
		align-items: start;
	}
	@media (min-width: 75rem) {
		.map-row:has(> :global(.machine-panel)) {
			grid-template-columns: minmax(0, 1fr) 19rem;
		}
		.map-row > :global(.machine-panel) {
			position: sticky;
			top: calc(var(--lab-header-height) + 1rem);
		}
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
