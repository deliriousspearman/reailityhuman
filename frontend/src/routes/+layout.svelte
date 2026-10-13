<script lang="ts">
	import '@fontsource/chakra-petch/500.css';
	import '@fontsource/chakra-petch/700.css';
	import '@fontsource-variable/figtree';
	import '@fontsource-variable/jetbrains-mono';
	import '$lib/styles/app.css';

	import { page } from '$app/state';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import AppSidebar from '$lib/components/AppSidebar.svelte';
	import ExpiryWarning from '$lib/components/ExpiryWarning.svelte';
	import { store } from '$lib/store.svelte';

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
				{#if store.offline}
					<p class="banner banner-warn" role="alert"><span><strong>Not connected.</strong> {store.offline}</span></p>
				{:else if store.config && !store.config.vcenterConfigured}
					<p class="banner banner-warn">
						<span><strong>vCenter isn't set up yet.</strong> Machines can't be deployed until an admin configures it.</span>
					</p>
				{/if}
				<ExpiryWarning />
				{@render children()}
			</main>
			{#if store.notice}
				<p class="notice" data-tone={store.notice.tone} role="status">
					{store.notice.text}
					<button class="btn btn-quiet btn-sm" type="button" onclick={() => (store.notice = null)}>Dismiss</button>
				</p>
			{/if}
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
	/* Centred in the space beside the sidebar, so wide screens don't leave an empty strip on one side. */
	main {
		width: 100%;
		max-width: 96rem;
		margin-inline: auto;
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
	main > .banner {
		margin-bottom: 1.5rem;
	}
	/* The result of the last action, when it failed: bottom right, above everything. */
	.notice {
		position: fixed;
		right: 1rem;
		bottom: 1rem;
		z-index: 30;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		max-width: min(28rem, calc(100vw - 2rem));
		padding: 0.75rem 0.75rem 0.75rem 1rem;
		border: var(--lms-border-width) solid var(--lab-error);
		border-radius: var(--lms-radius-md);
		background: var(--lms-panel);
		box-shadow: 0 1rem 2rem -0.5rem rgb(0 0 0 / 0.45);
		font-size: 0.9rem;
		color: var(--lms-white);
	}
	.notice[data-tone='ok'] {
		border-color: var(--lms-lime);
	}
	.scrim {
		position: fixed;
		inset: var(--lab-header-height) 0 0;
		z-index: 14;
		border: 0;
		background: rgb(0 0 0 / 0.45);
	}
	@media (min-width: 60rem) {
		main > .banner {
		margin-bottom: 1.5rem;
	}
	/* The result of the last action, when it failed: bottom right, above everything. */
	.notice {
		position: fixed;
		right: 1rem;
		bottom: 1rem;
		z-index: 30;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		max-width: min(28rem, calc(100vw - 2rem));
		padding: 0.75rem 0.75rem 0.75rem 1rem;
		border: var(--lms-border-width) solid var(--lab-error);
		border-radius: var(--lms-radius-md);
		background: var(--lms-panel);
		box-shadow: 0 1rem 2rem -0.5rem rgb(0 0 0 / 0.45);
		font-size: 0.9rem;
		color: var(--lms-white);
	}
	.notice[data-tone='ok'] {
		border-color: var(--lms-lime);
	}
	.scrim {
			display: none;
		}
	}
</style>
