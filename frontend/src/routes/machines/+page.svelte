<script lang="ts">
	import MachineTable from '$lib/components/MachineTable.svelte';
	import { store } from '$lib/store.svelte';
	import { categories, flagNotes, templates } from '$lib/templates';
	import { categorySlug } from '$lib/nav';

	let query = $state('');
	let category = $state<string>('All');
	/** Just your machines, or everyone's (the limits are shared). */
	let whose = $state<'mine' | 'all'>('mine');
	const listed = $derived(whose === 'mine' && store.user ? store.myMachines : store.machines);

	const shown = $derived(
		templates.filter((t) => {
			if (category !== 'All' && t.category !== category) return false;
			const q = query.trim().toLowerCase();
			if (!q) return true;
			return [t.name, t.category, t.os, t.description, ...t.versions.map((v) => v.version)].join(' ').toLowerCase().includes(q);
		}),
	);

	// Grouped under category headings, in the catalogue's order; empty groups are left out. Templates
	// that can be deployed come first in their group; the rest are greyed out as "soon".
	// Unfiltered, what can be deployed today is also listed first, so it isn't lost among the "soon" cards.
	const groups = $derived([
		...(category === 'All' && !query.trim()
			? [{ category: 'Available now', items: templates.filter((t) => store.isLive(t.id)) }]
			: []),
		...categories.map((c) => ({
			category: c as string,
			items: shown
				.filter((t) => t.category === c)
				.sort((a, b) => Number(store.isLive(b.id)) - Number(store.isLive(a.id))),
		})),
	].filter((g) => g.items.length));

	function versionSummary(versions: { version: string }[]) {
		const names = versions.map((v) => v.version);
		return names.length > 3 ? `${names.slice(0, 3).join(', ')} and ${names.length - 3} more` : names.join(', ');
	}
</script>

<svelte:head><title>Machines · Codex Labs</title></svelte:head>

<h1>Machines</h1>
<p class="lead">
	Single machines to build and break things on, on the LAN. They're deleted when their time runs out unless you extend
	them or keep them.
</p>

<div class="section-heading">
	<h2>Machines</h2>
	{#if store.config}
		<p>{store.machines.length} of {store.machineQuota}, {store.permanentCount} of {store.permanentQuota} kept permanently</p>
	{/if}
</div>
{#if store.user}
	<div class="chips whose" role="group" aria-label="Whose machines">
		<button type="button" class="chip" aria-pressed={whose === 'mine'} onclick={() => (whose = 'mine')}>
			Mine ({store.myMachines.length})
		</button>
		<button type="button" class="chip" aria-pressed={whose === 'all'} onclick={() => (whose = 'all')}>
			Everyone ({store.machines.length})
		</button>
	</div>
{/if}
<MachineTable
	machines={listed}
	owners
	empty={!store.loaded
		? 'Loading…'
		: whose === 'mine' && store.user
			? `No machines for ${store.user}. Pick one below to deploy it.`
			: 'No machines yet. Pick one below to deploy it.'}
/>

<div class="section-heading">
	<h2>Deploy a machine</h2>
</div>

<div class="filters">
	<label class="search">
		<span class="visually-hidden">Search machines</span>
		<input class="input" type="search" placeholder="Search, e.g. ubuntu 22.04 or firewall" bind:value={query} />
	</label>
	<div class="chips" role="group" aria-label="Category">
		{#each ['All', ...categories] as c (c)}
			<button type="button" class="chip" aria-pressed={category === c} onclick={() => (category = c)}>{c}</button>
		{/each}
	</div>
</div>

{#each groups as group (group.category)}
	{@const slug = categorySlug(group.category)}
	<section class="group" aria-labelledby={slug}>
		<h3 id={slug}>{group.category} <span>{group.items.length}</span></h3>
		<div class="templates">
			{#each group.items as t (t.id)}
				{@const live = store.isLive(t.id)}
				<article class="template" class:soon={!live}>
					<header>
						<h4>{#if live}<a href="/machines/new/{t.id}">{t.name}</a>{:else}{t.name}{/if}</h4>
						<span class="os" data-os={t.os.toLowerCase()}>{t.os}</span>
					</header>
					<p>{t.description}</p>
					<p class="versions">
						{live ? versionSummary(t.versions.filter((v) => store.isLive(t.id, v.version))) : versionSummary(t.versions)}
					</p>
					{#if t.flags?.length}
						<ul class="flags">
							{#each t.flags as f (f)}
								<li class="tag" title={flagNotes[f].note}>{flagNotes[f].label}</li>
							{/each}
						</ul>
					{/if}
					<footer>
						<span>{t.resources.cpu} vCPU, {t.resources.memoryGB} GB</span>
						{#if live}<span class="deploy">Deploy</span>{:else}<span class="soon-tag">Soon</span>{/if}
					</footer>
				</article>
			{/each}
		</div>
	</section>
{:else}
	<p class="none">Nothing matches “{query}”. Try a shorter search or another category.</p>
{/each}

<style>
	.lead {
		max-width: 44rem;
		margin: 0.75rem 0 0;
	}

	.filters {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem 1rem;
		margin-bottom: 1rem;
	}
	.search {
		flex: 1 1 16rem;
		max-width: 24rem;
	}
	.whose {
		margin-bottom: 0.75rem;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.chip {
		padding: 0.3rem 0.75rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-pill);
		background: var(--lms-panel);
		color: var(--lms-gray-2);
		font: 600 0.8rem var(--lms-font);
		cursor: pointer;
	}
	.chip:hover {
		color: var(--lms-white);
		border-color: var(--lms-gray-3);
	}
	.chip[aria-pressed='true'] {
		border-color: var(--lms-lime);
		background: var(--lms-accent-low);
		color: var(--lms-lime-text);
	}

	.templates {
		display: grid;
		gap: 0.9rem;
		grid-template-columns: repeat(auto-fill, minmax(min(17rem, 100%), 1fr));
	}
	.template {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 1rem 1.1rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-lg);
		background: var(--lms-panel);
	}
	/* Hardline: the card lifts onto a solid lime shadow. */
	.template:not(.soon):hover {
		border-color: var(--lms-lime);
		box-shadow: var(--lms-hover-shadow);
		translate: -2px -2px;
	}
	@media (prefers-reduced-motion: no-preference) {
		.template {
			transition:
				translate 0.12s,
				box-shadow 0.12s;
		}
	}
	/* Not deployable yet: dimmed, dashed, and it doesn't lift. */
	.template.soon {
		border-style: dashed;
	}
	.template.soon > :not(footer) {
		opacity: 0.5;
		filter: grayscale(0.6);
	}
	.template header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.group + .group {
		margin-top: 1.75rem;
	}
	.group h3 {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
		font-size: 1.1rem;
	}
	.group h3 span {
		font: 600 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.template h4 {
		margin: 0;
		font: 700 1.1rem var(--lms-display);
		color: var(--lms-white);
	}
	.template h4 a {
		color: var(--lms-white);
		text-decoration: none;
	}
	/* The whole card is clickable through the title link. */
	.template h4 a::after {
		content: '';
		position: absolute;
		inset: 0;
	}
	.template > p {
		font-size: 0.9rem;
		color: var(--lms-gray-2);
	}
	.template > p:first-of-type {
		flex: 1;
	}
	.versions {
		font: 0.78rem var(--lms-mono);
	}
	.template > p.versions {
		color: var(--lms-gray-3);
	}
	.flags {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.template footer {
		display: flex;
		justify-content: space-between;
		padding-top: 0.6rem;
		border-top: 1px solid var(--lms-gray-5);
		font: 0.78rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.deploy {
		font-weight: 700;
		color: var(--lms-lime-text);
	}
	.template:hover .deploy {
		text-decoration: underline;
	}
	.none {
		color: var(--lms-gray-3);
	}
</style>
