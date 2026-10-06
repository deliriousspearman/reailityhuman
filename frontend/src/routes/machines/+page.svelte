<script lang="ts">
	import MachineTable from '$lib/components/MachineTable.svelte';
	import { store } from '$lib/mock/store.svelte';
	import { categories, flagNotes, templates } from '$lib/mock/templates';

	let query = $state('');
	let category = $state<string>('All');

	const shown = $derived(
		templates.filter((t) => {
			if (category !== 'All' && t.category !== category) return false;
			const q = query.trim().toLowerCase();
			if (!q) return true;
			return [t.name, t.category, t.os, t.description, ...t.versions.map((v) => v.version)].join(' ').toLowerCase().includes(q);
		}),
	);

	// Grouped under category headings, in the catalogue's order; empty groups are left out.
	const groups = $derived(
		categories.map((c) => ({ category: c, items: shown.filter((t) => t.category === c) })).filter((g) => g.items.length),
	);

	function versionSummary(versions: { version: string }[]) {
		const names = versions.map((v) => v.version);
		return names.length > 3 ? `${names.slice(0, 3).join(', ')} and ${names.length - 3} more` : names.join(', ');
	}
</script>

<svelte:head><title>Machines · Codex Labs</title></svelte:head>

<h1>Machines</h1>
<p class="lead">
	Single machines to build and break things on, in your own network. They're deleted when their time runs out unless
	you extend them or keep them.
</p>

<div class="section-heading">
	<h2>Your machines</h2>
	<p>
		{store.myMachines.length} of {store.machineQuota}, {store.permanentCount} of {store.permanentQuota} kept permanently.
		Network <code>{store.network.cidr}</code>
	</p>
</div>
<MachineTable machines={store.myMachines} empty="No machines yet. Pick one below to deploy it." />

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
	{@const slug = `cat-${group.category.toLowerCase().replace(/\W+/g, '-')}`}
	<section class="group" aria-labelledby={slug}>
		<h3 id={slug}>{group.category} <span>{group.items.length}</span></h3>
		<div class="templates">
			{#each group.items as t (t.id)}
				<article class="template">
					<header>
						<h4><a href="/machines/new/{t.id}">{t.name}</a></h4>
						<span class="os" data-os={t.os.toLowerCase()}>{t.os}</span>
					</header>
					<p>{t.description}</p>
					<p class="versions">{versionSummary(t.versions)}</p>
					{#if t.flags?.length}
						<ul class="flags">
							{#each t.flags as f (f)}
								<li class="tag" title={flagNotes[f].note}>{flagNotes[f].label}</li>
							{/each}
						</ul>
					{/if}
					<footer>
						<span>{t.resources.cpu} vCPU, {t.resources.memoryGB} GB</span>
						<span class="deploy">Deploy</span>
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
	.section-heading code {
		color: var(--lms-lime-text);
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
	.template:hover {
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
