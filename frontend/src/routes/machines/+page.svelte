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

<div class="templates">
	{#each shown as t (t.id)}
		<article class="template">
			<header>
				<h3><a href="/machines/new/{t.id}">{t.name}</a></h3>
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
	{:else}
		<p class="none">Nothing matches “{query}”. Try a shorter search or another category.</p>
	{/each}
</div>

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
		border: 1px solid var(--lms-gray-5);
		border-radius: 999px;
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
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lab-radius);
		background: var(--lms-panel);
	}
	.template:hover {
		border-color: var(--lms-lime);
		box-shadow: 0 0 0 1px var(--lms-lime);
	}
	.template header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.template h3 {
		font-size: 1.1rem;
	}
	.template h3 a {
		color: var(--lms-white);
		text-decoration: none;
	}
	/* The whole card is clickable through the title link. */
	.template h3 a::after {
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
		grid-column: 1 / -1;
		color: var(--lms-gray-3);
	}
</style>
