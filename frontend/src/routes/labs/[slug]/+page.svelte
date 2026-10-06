<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from '$lib/components/Icon.svelte';
	import Status from '$lib/components/Status.svelte';
	import { clock, duration, instanceStates } from '$lib/format';
	import { findLab } from '$lib/mock/labs';
	import { store } from '$lib/mock/store.svelte';

	const lab = $derived(findLab(page.params.slug ?? ''));
	const shared = $derived(lab && store.shared(lab.slug));
	const own = $derived(lab && store.dedicated(lab.slug));
	const blocker = $derived(lab && !own ? store.deployBlocker(lab) : null);
	const entry = $derived(lab && (lab.networks.find((n) => n.entry) ?? lab.networks[0]));
	const osCounts = $derived(
		lab
			? Object.entries(
					lab.machines.reduce<Record<string, number>>((acc, m) => ((acc[m.os] = (acc[m.os] ?? 0) + 1), acc), {}),
				)
			: [],
	);

	let hours = $state(4);

	function deploy() {
		if (!lab) return;
		const inst = store.deploy(lab, hours);
		goto(`/instances/${inst.id}`);
	}
</script>

<svelte:head><title>{lab?.title ?? 'Lab not found'} · Codex Labs</title></svelte:head>

{#if !lab}
	<h1>Lab not found</h1>
	<p class="lead">There's no Pro Lab at this address. <a href="/">Browse Pro Labs</a>.</p>
{:else}
	<nav class="breadcrumbs" aria-label="Breadcrumbs">
		<a href="/">Pro Labs</a> <span aria-hidden="true">›</span> <span aria-current="page">{lab.title}</span>
	</nav>

	<header class="title-with-picture">
		<img class="picture" src={lab.image} alt="" width="72" height="72" />
		<h1>{lab.title}</h1>
	</header>
	<p class="lead">{lab.description}</p>

	<dl class="stats">
		<div>
			<dt>Level</dt>
			<dd><span class="level-chip" data-level={lab.level.toLowerCase()}>{lab.level}</span></dd>
		</div>
		<div>
			<dt>Environment</dt>
			<dd>
				{lab.environment === 'domain' ? 'Active Directory' : 'Standalone hosts'}
				{#if lab.domain}<span class="stat-note">{lab.domain}</span>{/if}
			</dd>
		</div>
		<div>
			<dt>Machines</dt>
			<dd>{lab.machines.length}<span class="stat-note">{osCounts.map(([os, n]) => `${n} ${os}`).join(', ')}</span></dd>
		</div>
		<div>
			<dt>Entry point</dt>
			<dd><code>{entry?.cidr}</code></dd>
		</div>
	</dl>

	<div class="section-heading">
		<h2>Get access</h2>
	</div>

	<div class="access-options">
		<section class="option panel" aria-labelledby="shared-title">
			<h3 id="shared-title">Shared lab</h3>
			<p>One copy for everyone. Other learners work in it at the same time, and instructors reset it.</p>
			{#if shared}
				<ul class="facts">
					<li><Status {...instanceStates[shared.state]} /></li>
					<li>{shared.connected} connected now</li>
					{#if shared.nextResetAt}
						<li>Next reset {clock(shared.nextResetAt, store.now)}, in {duration(shared.nextResetAt - store.now)}</li>
					{/if}
				</ul>
				<a class="btn btn-primary" href="/instances/{shared.id}">Open shared lab</a>
			{:else}
				<p class="note">There's no shared copy of this lab running.</p>
			{/if}
		</section>

		<section class="option panel" aria-labelledby="own-title">
			<h3 id="own-title">Your own copy</h3>
			<p>A private copy only you can reach. Reset any machine whenever you like; it's deleted when time runs out.</p>
			{#if own}
				<ul class="facts">
					<li><Status {...instanceStates[own.state]} /></li>
					{#if own.expiresAt}<li>Deleted in {duration(own.expiresAt - store.now)}</li>{/if}
				</ul>
				<a class="btn btn-primary" href="/instances/{own.id}">Open your copy</a>
			{:else}
				<ul class="facts">
					<li>Uses {lab.resources.cpu} vCPU and {lab.resources.memoryGB} GB memory</li>
					<li>Ready in about 5 minutes</li>
				</ul>
				<div class="deploy-row">
					<div class="field">
						<label for="hours">Keep it for</label>
						<select id="hours" class="select" bind:value={hours}>
							<option value={2}>2 hours</option>
							<option value={4}>4 hours</option>
							<option value={8}>8 hours</option>
							<option value={24}>24 hours</option>
						</select>
					</div>
					<button class="btn btn-primary" type="button" disabled={!!blocker} onclick={deploy}>
						<Icon name="plus" /> Deploy my copy
					</button>
				</div>
				{#if blocker}<p class="blocker" role="status"><Icon name="alert" /> {blocker}</p>{/if}
			{/if}
		</section>
	</div>

	<div class="section-heading">
		<h2>Machines</h2>
	</div>
	<div class="table-wrap">
		<table class="table">
			<thead>
				<tr>
					<th scope="col">Name</th>
					<th scope="col">OS</th>
					<th scope="col">Role</th>
					<th scope="col">Network</th>
					<th scope="col">Address</th>
				</tr>
			</thead>
			<tbody>
				{#each lab.machines as m (m.name)}
					<tr>
						<th scope="row">{m.name}</th>
						<td><span class="tag">{m.os}</span></td>
						<td>{m.role}</td>
						<td>{m.nics.map((n) => n.network).join(', ')}</td>
						<td class="mono">{m.nics.map((n) => n.ip).join(', ')}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

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
	.title-with-picture {
		display: flex;
		align-items: center;
		gap: 1.25rem;
	}
	.picture {
		width: 4.5rem;
		height: 4.5rem;
		border-radius: var(--lms-radius-lg);
		border: var(--lms-border-width) solid var(--lms-gray-5);
		background: #0d1420;
	}
	.lead {
		max-width: 44rem;
		margin: 1rem 0 1.75rem;
		font-size: 1.1rem;
	}

	.access-options {
		display: grid;
		gap: 1rem;
	}
	@media (min-width: 52rem) {
		.access-options {
			grid-template-columns: 1fr 1fr;
		}
	}
	.option {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.9rem;
		padding: 1.25rem;
	}
	.option h3 {
		font-size: 1.25rem;
	}
	.option > p {
		color: var(--lms-gray-2);
	}
	.facts {
		display: grid;
		gap: 0.35rem;
		margin: 0;
		padding: 0.75rem 0 0;
		width: 100%;
		border-top: 1px solid var(--lms-gray-5);
		list-style: none;
		font: 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.option .btn {
		margin-top: auto;
	}
	.deploy-row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 0.75rem;
		margin-top: auto;
	}
	.deploy-row .field {
		width: 9rem;
	}
	.deploy-row .btn {
		margin-top: 0;
	}
	.blocker {
		display: flex;
		gap: 0.5rem;
		font-size: 0.85rem;
		color: var(--lms-medium);
	}
	.note {
		font-size: 0.875rem;
		color: var(--lms-gray-3);
	}
</style>
