<script lang="ts">
	// A planned lab: the LMS lab card, greyed out until Pro Labs can be deployed.
	import type { Lab } from '$lib/types';

	let { lab }: { lab: Lab } = $props();

	const osCounts = $derived(
		Object.entries(
			lab.machines.reduce<Record<string, number>>((acc, m) => ((acc[m.os] = (acc[m.os] ?? 0) + 1), acc), {}),
		),
	);
</script>

<article class="lab-card soon">
	<header>
		<div class="card-title">
			<img class="picture" src={lab.image} alt="" width="56" height="56" />
			<h2>{lab.title}</h2>
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
		<div class="footer-row"><span class="soon-tag">Soon</span> <span>Not available to deploy yet</span></div>
	</footer>
</article>

<style>
	.lab-card {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1.25rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-lg);
		background: var(--lms-panel);
	}
	/* Not deployable yet: dimmed, and it doesn't lift on hover the way live cards do. */
	.lab-card.soon {
		border-style: dashed;
	}
	.lab-card.soon > :not(footer) {
		opacity: 0.55;
		filter: grayscale(0.6);
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
		border-radius: var(--lms-radius-md);
		border: var(--lms-border-width) solid var(--lms-gray-5);
		background: #0d1420;
	}
	h2 {
		font-size: 1.3rem;
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
		gap: 0.75rem;
	}
</style>
