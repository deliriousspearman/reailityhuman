<script lang="ts">
	import { page } from '$app/state';
	import { duration, instanceStates, singleMachineStates } from '$lib/format';
	import { labs, store } from '$lib/mock/store.svelte';
	import { findLab } from '$lib/mock/labs';
	import { categories } from '$lib/mock/templates';
	import { adminSections, categorySlug, sectionFor, sections } from '$lib/nav';
	import Icon from './Icon.svelte';

	let { open = false, onnavigate }: { open?: boolean; onnavigate?: () => void } = $props();

	const current = (href: string) => (page.url.pathname + page.url.hash === href ? 'page' : undefined);

	// Only the section you're in is listed; the header links to the others.
	const section = $derived(sectionFor(page.url.pathname));
	const head = $derived(sections.find((s) => s.id === section)!);
	const visibleSections = $derived(sections.filter((s) => !s.adminOnly || store.isAdmin));

	// Learners see their own copies first, then the shared labs; admins see everything, as on /instances.
	const instances = $derived(
		store.isAdmin ? store.instances : [...store.mine, ...store.instances.filter((i) => i.kind === 'shared')],
	);
</script>

<nav id="app-sidebar" class="sidebar" class:open aria-label="{head.label} menu">
	<!-- On phones the header has no room for the section links, so the drawer carries them. -->
	<ul class="section-links">
		{#each visibleSections as s (s.id)}
			<li>
				<a href={s.href} aria-current={s.id === section ? 'true' : undefined} onclick={onnavigate}>
					<Icon name={s.icon} /> {s.label}
				</a>
			</li>
		{/each}
	</ul>

	<div class="group">
		<a class="group-link" href={head.href} aria-current={current(head.href)} onclick={onnavigate}>
			<Icon name={head.icon} /> {head.label}
		</a>

		{#if section === 'machines'}
			<p class="sub">Your machines</p>
			<ul>
				{#each store.myMachines as m (m.id)}
					{@const state = singleMachineStates[m.state]}
					<li>
						<a href="/machines/{m.id}" aria-current={current(`/machines/${m.id}`)} onclick={onnavigate}>
							<span class="dot" data-tone={state.tone} title={state.label}></span>
							<span class="visually-hidden">{state.label}:</span>
							<span class="machine-name">{m.name}</span>
							<span class="kind">{m.expiresAt === null ? 'kept' : m.state === 'expired' ? 'expired' : duration(m.expiresAt - store.now, true)}</span>
						</a>
					</li>
				{:else}
					<li class="none">None yet</li>
				{/each}
			</ul>
			<p class="sub">Deploy</p>
			<ul>
				{#each categories as c (c)}
					{@const href = `/machines#${categorySlug(c)}`}
					<li><a {href} aria-current={current(href)} onclick={onnavigate}>{c}</a></li>
				{/each}
			</ul>
		{:else if section === 'labs'}
			<ul>
				{#each labs as lab (lab.slug)}
					<li><a href="/labs/{lab.slug}" aria-current={current(`/labs/${lab.slug}`)} onclick={onnavigate}>{lab.title}</a></li>
				{/each}
			</ul>
		{:else if section === 'instances'}
			<ul>
				{#each instances as inst (inst.id)}
					{@const state = instanceStates[inst.state]}
					<li>
						<a href="/instances/{inst.id}" aria-current={current(`/instances/${inst.id}`)} onclick={onnavigate}>
							<span class="dot" data-tone={state.tone} title={state.label}></span>
							<span class="visually-hidden">{state.label}:</span>
							{findLab(inst.lab)?.title}
							<span class="kind">{inst.kind === 'shared' ? 'shared' : inst.owner === store.user.username ? 'yours' : inst.owner}</span>
						</a>
					</li>
				{:else}
					<li class="none">None running</li>
				{/each}
			</ul>
		{:else if section === 'admin' && store.isAdmin}
			<ul>
				{#each adminSections as a (a.id)}
					<li><a href="/admin#{a.id}" aria-current={current(`/admin#${a.id}`)} onclick={onnavigate}>{a.label}</a></li>
				{/each}
			</ul>
		{/if}
	</div>
</nav>

<style>
	.sidebar {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		padding: 1.25rem 0.75rem;
		background: var(--lms-bg-sidebar);
		border-right: 1px solid var(--lms-gray-5);
		overflow-y: auto;
	}
	.group-link {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.4rem 0.6rem;
		border-radius: var(--lms-radius-xs);
		font: 700 1rem var(--lms-display);
		color: var(--lms-white);
		text-decoration: none;
	}
	.group-link :global(svg) {
		color: var(--lms-gray-3);
	}
	ul {
		margin: 0.25rem 0 0;
		padding: 0 0 0 0.9rem;
		list-style: none;
		border-left: 1px solid var(--lms-gray-5);
		margin-inline-start: 1.15rem;
	}
	ul a {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.3rem 0.6rem;
		border-radius: var(--lms-radius-xs);
		color: var(--lms-gray-2);
		font-size: 0.9rem;
		text-decoration: none;
	}
	a:hover {
		color: var(--lms-white);
	}
	/* A lime rail on the current page, as in the LMS sidebar. */
	a[aria-current='page'],
	a[aria-current='page']:hover {
		background: var(--lms-accent-low);
		color: var(--lms-lime-text);
		box-shadow: inset 3px 0 0 var(--lms-lime);
	}
	a[aria-current='page'] :global(svg) {
		color: inherit;
	}
	.sub {
		margin: 0.9rem 0 0;
		padding-inline-start: 2.2rem;
		font: 600 0.7rem var(--lms-mono);
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--lms-gray-3);
	}
	.none {
		padding: 0.3rem 0.6rem;
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}

	/* Section links: drawer-only, below the width where the header shows them. */
	.section-links {
		display: none;
		margin: 0;
		padding: 0 0 1rem;
		border-left: 0;
		border-bottom: 1px solid var(--lms-gray-5);
	}
	.section-links a {
		gap: 0.6rem;
		font: 700 0.95rem var(--lms-display);
	}
	.section-links a[aria-current='true'] {
		color: var(--lms-lime-text);
	}
	@media (max-width: 39.99rem) {
		.section-links {
			display: grid;
		}
	}

	.kind {
		margin-inline-start: auto;
		font: 500 0.7rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.dot {
		flex-shrink: 0;
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 50%;
		background: var(--lab-up);
	}
	.dot[data-tone='busy'] {
		background: var(--lab-busy);
	}
	.dot[data-tone='down'] {
		background: transparent;
		box-shadow: inset 0 0 0 1.5px var(--lab-down);
	}
	.dot[data-tone='error'] {
		background: var(--lab-error);
	}
	.dot[data-tone='warn'] {
		background: var(--lab-warn);
	}
	.machine-name {
		font-family: var(--lms-mono);
		font-size: 0.85rem;
	}

	/* Mobile: a drawer under the header. */
	@media (max-width: 59.99rem) {
		.sidebar {
			position: fixed;
			z-index: 15;
			top: var(--lab-header-height);
			bottom: 0;
			left: 0;
			width: min(20rem, 85vw);
			translate: -100% 0;
			visibility: hidden;
			transition:
				translate 0.2s ease,
				visibility 0.2s;
		}
		.sidebar.open {
			translate: 0 0;
			visibility: visible;
			box-shadow: 1rem 0 2rem rgb(0 0 0 / 0.4);
		}
	}
</style>
