<script lang="ts">
	import '@fontsource/chakra-petch/500.css';
	import '@fontsource/chakra-petch/700.css';
	import '@fontsource-variable/figtree';
	import '@fontsource-variable/jetbrains-mono';
	import '$lib/styles/app.css';

	import { page } from '$app/state';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import AppSidebar from '$lib/components/AppSidebar.svelte';

	let { children } = $props();
	let menuOpen = $state(false);

	// The sign-in page has no header or sidebar.
	const bare = $derived(page.url.pathname === '/login');
</script>

{#if bare}
	{@render children()}
{:else}
	<div class="shell">
		<AppHeader bind:menuOpen />
		<div class="body">
			<AppSidebar open={menuOpen} onnavigate={() => (menuOpen = false)} />
			{#if menuOpen}
				<button class="scrim" type="button" aria-label="Close menu" onclick={() => (menuOpen = false)}></button>
			{/if}
			<main>
				{@render children()}
			</main>
		</div>
	</div>
{/if}

<style>
	.body {
		display: grid;
		/* minmax(0, …) so wide content (tables) scrolls inside its own box instead of widening the page. */
		grid-template-columns: minmax(0, 1fr);
		min-height: calc(100dvh - var(--lab-header-height));
	}
	@media (min-width: 60rem) {
		.body {
			grid-template-columns: var(--lab-sidebar-width) minmax(0, 1fr);
		}
		.body > :global(.sidebar) {
			position: sticky;
			top: var(--lab-header-height);
			height: calc(100dvh - var(--lab-header-height));
		}
	}
	main {
		width: 100%;
		max-width: 80rem;
		padding: 1.5rem 1rem 4rem;
	}
	@media (min-width: 40rem) {
		main {
			padding: 2rem 2rem 4rem;
		}
	}
	@media (min-width: 60rem) {
		main {
			padding-inline: 2.5rem;
		}
	}
	.scrim {
		position: fixed;
		inset: var(--lab-header-height) 0 0;
		z-index: 14;
		border: 0;
		background: rgb(0 0 0 / 0.45);
	}
	@media (min-width: 60rem) {
		.scrim {
			display: none;
		}
	}
</style>
