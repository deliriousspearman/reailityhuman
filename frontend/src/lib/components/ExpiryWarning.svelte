<script lang="ts">
	// On every page: your machines that power off within the hour, with a quick way to extend them.
	// The machine's own page has its own banner, so it's left out there.
	import { page } from '$app/state';
	import { duration } from '$lib/format';
	import { store } from '$lib/store.svelte';
	import Icon from './Icon.svelte';

	const SOON = 3_600_000;

	const soon = $derived(
		store.myMachines.filter(
			(m) =>
				m.expiresAt !== null &&
				(m.state === 'running' || m.state === 'stopped') &&
				m.expiresAt - store.now < SOON &&
				!page.url.pathname.startsWith(`/machines/${m.id}`),
		),
	);
</script>

{#if soon.length}
	<div class="banner banner-warn expiry" role="status">
		<p><strong>{soon.length === 1 ? 'A machine powers off soon.' : `${soon.length} machines power off soon.`}</strong></p>
		<ul>
			{#each soon as m (m.id)}
				<li>
					<a href="/machines/{m.id}">{m.name}</a> in {duration(m.expiresAt! - store.now, true)}
					<button class="btn btn-sm" type="button" onclick={() => store.extendMachine(m, 2)}><Icon name="clock" /> +2 h</button>
				</li>
			{/each}
		</ul>
	</div>
{/if}

<style>
	.expiry {
		margin-bottom: 1.5rem;
	}
	ul {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem 1.25rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	a {
		font-family: var(--lms-mono);
		font-weight: 600;
	}
</style>
