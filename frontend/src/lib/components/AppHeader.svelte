<script lang="ts">
	import { page } from '$app/state';
	import { store } from '$lib/store.svelte';
	import { sectionFor, sections } from '$lib/nav';
	import { PALETTES } from '$lib/palettes';
	import { theme, type ThemeChoice } from '$lib/theme.svelte';
	import Icon from './Icon.svelte';

	let { menuOpen = $bindable(false) }: { menuOpen?: boolean } = $props();

	// Where the course site lives; set per deployment once the panel has config.
	const LMS_URL = 'https://learn.example/';

	const section = $derived(sectionFor(page.url.pathname));

	// A count of what's running beside Machines, now the sidebar only lists the current section.
	const running = $derived({
		machines: store.machines.filter((m) => m.state === 'running').length,
	} as Partial<Record<string, number>>);
</script>

<header class="header">
	<button
		class="menu-toggle btn btn-quiet"
		type="button"
		aria-expanded={menuOpen}
		aria-controls="app-sidebar"
		onclick={() => (menuOpen = !menuOpen)}
	>
		<Icon name={menuOpen ? 'close' : 'menu'} label={menuOpen ? 'Close menu' : 'Open menu'} />
	</button>

	<a class="site-title" href="/machines">Codex Labs</a>

	<nav class="sections" aria-label="Sections">
		{#each sections as s (s.id)}
			<a class="nav-link" class:soon={s.soon} href={s.href} aria-current={s.id === section ? 'true' : undefined}>
				{s.label}
				{#if s.soon}<span class="soon-tag">Soon</span>{/if}
				{#if running[s.id]}<span class="count" title="{running[s.id]} running">{running[s.id]}</span>{/if}
			</a>
		{/each}
	</nav>

	<div class="right">
		<a class="nav-link" href={LMS_URL}>Courses <Icon name="external" /></a>

		<label class="theme-select">
			<span class="visually-hidden">Theme</span>
			<Icon name={theme.choice === 'auto' ? 'auto' : theme.base === 'dark' ? 'moon' : 'sun'} />
			<select value={theme.choice} onchange={(e) => theme.set(e.currentTarget.value as ThemeChoice)}>
				<option value="auto">System</option>
				{#each PALETTES.slice(0, 2) as palette (palette.id)}
					<option value={palette.id}>{palette.label}</option>
				{/each}
				{#each [['dark', 'Dark'], ['light', 'Light']] as [base, label] (base)}
					<optgroup {label}>
						{#each PALETTES.slice(2).filter((palette) => palette.base === base) as palette (palette.id)}
							<option value={palette.id}>{palette.label}</option>
						{/each}
					</optgroup>
				{/each}
			</select>
		</label>

	</div>
</header>

<style>
	.header {
		position: sticky;
		top: 0;
		z-index: 20;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		height: var(--lab-header-height);
		padding-inline: 1rem;
		border-bottom: 1px solid var(--lms-gray-5);
		background: var(--lms-bg-nav);
	}
	.menu-toggle {
		padding: 0.4rem;
		min-height: 2.25rem;
	}
	@media (min-width: 60rem) {
		.menu-toggle {
			display: none;
		}
		.header {
			padding-inline: 1.5rem;
		}
	}

	/* Logo: a prompt in a lime tile, as the course site. */
	.site-title {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font: 700 1.4rem var(--lms-display);
		color: var(--lms-white);
		text-decoration: none;
		white-space: nowrap;
	}
	.site-title::before {
		content: '>_';
		display: grid;
		place-items: center;
		width: 1.9rem;
		height: 1.9rem;
		border-radius: var(--lms-radius-sm);
		background: var(--lms-lime);
		color: var(--lms-on-lime);
		font: 700 0.8rem var(--lms-mono);
	}

	.right {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-inline-start: auto;
	}
	.sections {
		display: flex;
		gap: 0.25rem;
		margin-inline-start: 1rem;
	}
	@media (max-width: 39.99rem) {
		.sections {
			display: none;
		}
	}
	/* As the course site's section links. */
	.nav-link {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.75rem;
		border-radius: var(--lms-radius-sm);
		color: var(--lms-gray-2);
		font: 700 1rem var(--lms-display);
		text-decoration: none;
		white-space: nowrap;
	}
	.nav-link:hover {
		color: var(--lms-white);
		background: var(--lms-panel-2);
	}
	.nav-link :global(svg) {
		width: 0.9rem;
		height: 0.9rem;
	}
	.nav-link[aria-current='true'] {
		color: var(--lms-lime-text);
		background: var(--lms-accent-low);
	}
	.count {
		min-width: 1.2rem;
		padding: 0 0.3rem;
		border-radius: var(--lms-radius-pill);
		background: var(--lms-panel-2);
		border: 1px solid var(--lms-gray-5);
		font: 600 0.7rem/1.1rem var(--lms-mono);
		text-align: center;
		color: var(--lms-gray-2);
	}
	@media (max-width: 40rem) {
		.right > .nav-link {
			display: none;
		}
	}

	.theme-select {
		position: relative;
		display: inline-flex;
		align-items: center;
		color: var(--lms-gray-2);
	}
	.theme-select :global(svg) {
		position: absolute;
		left: 0.6rem;
		pointer-events: none;
	}
	.theme-select select {
		appearance: none;
		min-height: 2.25rem;
		padding: 0.3rem 0.7rem 0.3rem 2.1rem;
		border: 1px solid transparent;
		border-radius: var(--lms-radius-sm);
		background: transparent;
		color: inherit;
		font: 600 0.875rem var(--lms-font);
		cursor: pointer;
	}
	.theme-select select:hover {
		border-color: var(--lms-gray-5);
		color: var(--lms-white);
	}
	@media (max-width: 40rem) {
		.theme-select select {
			width: 2.4rem;
			padding: 0;
			color: transparent;
		}
	}

	/* Sections that aren't built yet: dimmed, with a tag. */
	.nav-link.soon {
		color: var(--lms-gray-4);
	}
</style>
