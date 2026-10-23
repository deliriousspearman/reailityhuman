<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import MachineTable from '$lib/components/MachineTable.svelte';
	import { store } from '$lib/store.svelte';
	import { categories, findTemplate, flagNotes, templates } from '$lib/templates';
	import OsLogo from '$lib/components/OsLogo.svelte';
	import { categorySlug } from '$lib/nav';
	import { withPlanned } from '$lib/services';
	import type { Service } from '$lib/types';

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

	// Choosing a service first (?by=service), then where to run it ----------------------------------------
	const byService = $derived(page.url.searchParams.get('by') === 'service');
	function showBy(service: boolean) {
		if (service === byService) return;
		category = 'All';
		goto(service ? '?by=service' : page.url.pathname, { keepFocus: true, noScroll: true });
	}

	/** The API's services, then those planned but not built (lib/services.ts), greyed out as "soon". */
	const services = $derived(store.config ? withPlanned(store.config.services) : []);
	/** Service categories, in the order extras.yaml first uses them, then the planned ones'. */
	const serviceCategories = $derived([...new Set(services.map((x) => x.category))]);
	/** "Ubuntu Server 26.04": a template version as people know it. */
	const osName = (template: string, version: string) => `${findTemplate(template)?.name ?? template} ${version}`;
	const ready = (x: Service) => x.offeredBy.some((o) => o.ready);
	const serviceGroups = $derived.by(() => {
		const q = query.trim().toLowerCase();
		const shown = services.filter((x) => {
			if (category !== 'All' && x.category !== category) return false;
			if (!q) return true;
			const oses = x.offeredBy.map((o) => osName(o.template, o.version));
			return [x.name, x.category, x.description, ...oses].join(' ').toLowerCase().includes(q);
		});
		return serviceCategories
			.map((c) => ({
				category: c,
				items: shown.filter((x) => x.category === c).sort((a, b) => Number(ready(b)) - Number(ready(a))),
			}))
			.filter((g) => g.items.length);
	});
	/** "port 21", "ports 80, 443", or "8 ports" for a mail server's many. */
	const portSummary = (ports: number[]) =>
		ports.length > 3 ? `${ports.length} ports` : `${ports.length > 1 ? 'ports' : 'port'} ${ports.join(', ')}`;
	/** Deploy form for a template version, with the service already ticked. */
	const deployHref = (x: Service, o: Service['offeredBy'][number]) =>
		`/machines/new/${o.template}?version=${encodeURIComponent(o.version)}&extra=${encodeURIComponent(x.id)}`;

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
		<p>{store.machineCount} of {store.machineQuota}, {store.permanentCount} of {store.permanentQuota} kept permanently</p>
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

<div class="chips by" role="group" aria-label="Choose by">
	<button type="button" class="chip" aria-pressed={!byService} onclick={() => showBy(false)}>By OS</button>
	<button type="button" class="chip" aria-pressed={byService} onclick={() => showBy(true)}>By service</button>
</div>

<div class="filters">
	<label class="search">
		<span class="visually-hidden">{byService ? 'Search services' : 'Search machines'}</span>
		<input
			class="input"
			type="search"
			placeholder={byService ? 'Search, e.g. postgresql or web server' : 'Search, e.g. ubuntu 22.04 or firewall'}
			bind:value={query}
		/>
	</label>
	<div class="chips" role="group" aria-label="Category">
		{#each ['All', ...(byService ? serviceCategories : categories)] as c (c)}
			<button type="button" class="chip" aria-pressed={category === c} onclick={() => (category = c)}>{c}</button>
		{/each}
	</div>
</div>

{#if byService}
	{#each serviceGroups as group (group.category)}
		{@const slug = `svc-${categorySlug(group.category)}`}
		<section class="group" aria-labelledby={slug}>
			<h3 id={slug}>{group.category} <span>{group.items.length}</span></h3>
			<div class="templates">
				{#each group.items as x (x.id)}
					<article class="template service" class:soon={!ready(x)}>
						<header>
							<h4>{x.name}</h4>
							{#if x.ports.length}<span class="ports">{portSummary(x.ports)}</span>{/if}
						</header>
						<p>{x.description}</p>
						<ul class="oses" aria-label="Runs on">
							{#each x.offeredBy as o (`${o.template} ${o.version}`)}
								<li>
									{#if o.ready}
										<a href={deployHref(x, o)}>{osName(o.template, o.version)}</a>
										<span class="deploy">Deploy</span>
									{:else}
										<span class="planned">{osName(o.template, o.version)}</span>
										<span class="soon-tag">Soon</span>
									{/if}
								</li>
							{:else}
								<li><span class="planned">Planned</span> <span class="soon-tag">Soon</span></li>
							{/each}
						</ul>
						{#if x.minMemoryGB}<footer><span>Needs {x.minMemoryGB} GB of memory</span></footer>{/if}
					</article>
				{/each}
			</div>
		</section>
	{:else}
		<p class="none">{store.config ? `Nothing matches “${query}”. Try a shorter search or another category.` : 'Loading…'}</p>
	{/each}
{:else}
	{#each groups as group (group.category)}
		{@const slug = categorySlug(group.category)}
		<section class="group" aria-labelledby={slug}>
			<h3 id={slug}>{group.category} <span>{group.items.length}</span></h3>
			<div class="templates">
				{#each group.items as t (t.id)}
					{@const live = store.isLive(t.id)}
					{@const r = store.asDeployed(t).resources}
					<article class="template" class:soon={!live}>
						<header>
							<div class="title">
								<OsLogo id={t.id} name={t.name} />
								<h4>{#if live}<a href="/machines/new/{t.id}">{t.name}</a>{:else}{t.name}{/if}</h4>
							</div>
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
							<span>{r.cpu} vCPU, {r.memoryGB} GB</span>
							{#if live}<span class="deploy">Deploy</span>{:else}<span class="soon-tag">Soon</span>{/if}
						</footer>
					</article>
				{/each}
			</div>
		</section>
	{:else}
		<p class="none">Nothing matches “{query}”. Try a shorter search or another category.</p>
	{/each}
{/if}

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
	.template .title {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		min-width: 0;
	}
	.template.soon .title :global(.logo) {
		filter: grayscale(1);
		opacity: 0.6;
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

	.by {
		margin-bottom: 0.75rem;
	}
	/* A service's card: the OSes it runs on, each its own link (so the card itself isn't one). */
	.oses {
		display: grid;
		gap: 0.3rem;
		margin: 0;
		padding: 0.6rem 0 0;
		border-top: 1px solid var(--lms-gray-5);
		list-style: none;
		font: 0.8rem var(--lms-mono);
	}
	.oses li {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.oses a {
		color: var(--lms-white);
		font-weight: 600;
	}
	.template.service:hover .deploy {
		text-decoration: none;
	}
	.template.service li:has(a:hover) .deploy {
		text-decoration: underline;
	}
	.template.service:hover {
		border-color: var(--lms-gray-5);
		box-shadow: none;
		translate: none;
	}
	/* Planned OSes stay readable, even on a card with nothing ready. */
	.template.service.soon > .oses {
		opacity: 1;
		filter: none;
	}
	.planned {
		color: var(--lms-gray-3);
	}
	.ports {
		font: 0.75rem var(--lms-mono);
		color: var(--lms-gray-3);
		white-space: nowrap;
	}
</style>
