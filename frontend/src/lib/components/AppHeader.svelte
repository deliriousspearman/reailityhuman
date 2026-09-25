<script lang="ts">
	import { goto } from '$app/navigation';
	import { store } from '$lib/mock/store.svelte';
	import { theme, type ThemeChoice } from '$lib/theme.svelte';
	import Icon from './Icon.svelte';

	let { menuOpen = $bindable(false) }: { menuOpen?: boolean } = $props();

	// Where the course site lives; set per deployment once the panel has config.
	const LMS_URL = 'https://learn.example/';

	let userMenu: HTMLDetailsElement | undefined = $state();

	function signOut() {
		userMenu?.removeAttribute('open');
		goto('/login');
	}
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

	<a class="site-title" href="/">Codex Labs</a>

	<div class="right">
		<a class="courses-link" href={LMS_URL}>Courses <Icon name="external" /></a>

		<label class="theme-select">
			<span class="visually-hidden">Theme</span>
			<Icon name={theme.choice === 'auto' ? 'auto' : theme.choice === 'dark' ? 'moon' : 'sun'} />
			<select value={theme.choice} onchange={(e) => theme.set(e.currentTarget.value as ThemeChoice)}>
				<option value="dark">Dark</option>
				<option value="light">Light</option>
				<option value="auto">Auto</option>
			</select>
		</label>

		<details class="user-menu" bind:this={userMenu}>
			<summary>
				<span class="avatar" aria-hidden="true">{store.user.username.slice(0, 1).toUpperCase()}</span>
				<span class="user-name">{store.user.username}</span>
			</summary>
			<div class="user-panel panel">
				<p class="user-line"><strong>{store.user.username}</strong> {store.user.role === 'admin' ? 'Admin' : 'Learner'}</p>
				<fieldset>
					<legend>Preview as</legend>
					<label><input type="radio" bind:group={store.user.role} value="admin" /> Admin</label>
					<label><input type="radio" bind:group={store.user.role} value="learner" /> Learner</label>
				</fieldset>
				<button class="btn btn-sm" type="button" onclick={signOut}>Sign out</button>
			</div>
		</details>
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

	/* Logo: a prompt in a lime tile, as the LMS. */
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
		border-radius: 6px;
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
	.courses-link {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.4rem 0.6rem;
		color: var(--lms-gray-2);
		font-size: 0.9rem;
		font-weight: 600;
		text-decoration: none;
	}
	.courses-link:hover {
		color: var(--lms-white);
	}
	.courses-link :global(svg) {
		width: 0.9rem;
		height: 0.9rem;
	}
	@media (max-width: 40rem) {
		.courses-link,
		.user-name {
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
		border-radius: var(--lab-radius-sm);
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

	.user-menu {
		position: relative;
	}
	.user-menu summary {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.25rem 0.5rem 0.25rem 0.25rem;
		border: 1px solid transparent;
		border-radius: 999px;
		color: var(--lms-gray-1);
		font-weight: 600;
		font-size: 0.9rem;
		list-style: none;
		cursor: pointer;
	}
	.user-menu summary::-webkit-details-marker {
		display: none;
	}
	.user-menu summary:hover,
	.user-menu[open] summary {
		border-color: var(--lms-gray-5);
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 1.9rem;
		height: 1.9rem;
		border-radius: 50%;
		background: var(--lms-panel-2);
		border: 1px solid var(--lms-gray-5);
		font: 700 0.85rem var(--lms-mono);
		color: var(--lms-lime-text);
	}
	.user-panel {
		position: absolute;
		right: 0;
		top: calc(100% + 0.5rem);
		display: grid;
		gap: 0.9rem;
		width: 14rem;
		padding: 1rem;
		box-shadow: 0 1rem 2rem -0.5rem rgb(0 0 0 / 0.45);
	}
	.user-line {
		display: flex;
		justify-content: space-between;
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}
	.user-line strong {
		color: var(--lms-white);
	}
	fieldset {
		display: grid;
		gap: 0.3rem;
		margin: 0;
		padding: 0.6rem 0.75rem 0.7rem;
		border: 1px dashed var(--lms-gray-5);
		border-radius: var(--lab-radius-sm);
		font-size: 0.875rem;
	}
	legend {
		padding-inline: 0.3rem;
		font-size: 0.75rem;
		color: var(--lms-gray-3);
	}
	fieldset label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--lms-gray-1);
		cursor: pointer;
	}
	input[type='radio'] {
		accent-color: var(--lms-lime);
	}
</style>
