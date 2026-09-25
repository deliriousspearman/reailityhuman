<script lang="ts">
	// A lab in the catalogue: the LMS lab card, plus a footer with the live state of the shared
	// instance and of this person's own copy.
	import { duration, instanceStates } from '$lib/format';
	import { store } from '$lib/mock/store.svelte';
	import type { Lab } from '$lib/types';
	import Status from './Status.svelte';

	let { lab }: { lab: Lab } = $props();

	const shared = $derived(store.shared(lab.slug));
	const own = $derived(store.dedicated(lab.slug));
	const osCounts = $derived(
		Object.entries(
			lab.machines.reduce<Record<string, number>>((acc, m) => ((acc[m.os] = (acc[m.os] ?? 0) + 1), acc), {}),
		),
	);
</script>

<article class="lab-card">
	<header>
		<div class="card-title">
			<img class="picture" src={lab.image} alt="" width="56" height="56" />
			<h2><a href="/labs/{lab.slug}">{lab.title}</a></h2>
		</div>
		<span class="level-chip" data-level={lab.level.toLowerCase()}>{lab.level}</span>
	</header>
	<p>{lab.description}</p>
	<ul class="lab-tags">
		<li class="tag tag-accent">{lab.environment === 'domain' ? 'Active Directory' : 'Standalone hosts'}</li>
		<li class="tag">{lab.machines.length} machines</li>
		{#each osCounts as [os, n] (os)}
			<li class="tag">{n} {os}</li>
		{/each}
	</ul>
	<footer>
		{#if own}
			<div class="footer-row">
				<Status size="sm" {...instanceStates[own.state]} />
				<span>
					Your copy{#if own.expiresAt}, {duration(own.expiresAt - store.now)} left{/if}
				</span>
			</div>
		{/if}
		{#if shared}
			<div class="footer-row">
				<Status size="sm" {...instanceStates[shared.state]} />
				<span>Shared, {shared.connected} connected</span>
			</div>
		{/if}
	</footer>
</article>

<style>
	.lab-card {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1.25rem;
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lab-radius);
		background: var(--lms-panel);
	}
	.lab-card:hover {
		border-color: var(--lms-lime);
		box-shadow: 0 0 0 1px var(--lms-lime);
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.card-title {
		display: flex;
		align-items: center;
		gap: 0.875rem;
		min-width: 0;
	}
	.picture {
		flex-shrink: 0;
		width: 3.5rem;
		height: 3.5rem;
		border-radius: 8px;
		border: 1px solid var(--lms-gray-5);
		background: #0d1420;
	}
	h2 {
		font-size: 1.3rem;
	}
	h2 a {
		color: var(--lms-white);
		text-decoration: none;
	}
	/* The whole card is clickable through the title link. */
	h2 a::after {
		content: '';
		position: absolute;
		inset: 0;
	}
	.lab-card > p {
		flex: 1;
		color: var(--lms-gray-2);
	}
	.lab-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	footer {
		display: grid;
		gap: 0.4rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--lms-gray-5);
		font: 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.footer-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}
</style>
