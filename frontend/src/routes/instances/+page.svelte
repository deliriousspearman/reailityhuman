<script lang="ts">
	import InstanceTable from '$lib/components/InstanceTable.svelte';
	import { store } from '$lib/mock/store.svelte';

	// Learners see their own copies and the shared labs; admins see everything.
	const visible = $derived(
		store.isAdmin ? store.instances : [...store.mine, ...store.instances.filter((i) => i.kind === 'shared')],
	);
</script>

<svelte:head><title>Instances · Codex Labs</title></svelte:head>

<h1>Instances</h1>
<p class="lead">
	{store.isAdmin
		? 'Every running copy of every lab.'
		: `The shared labs and your own copies. You can run ${store.quota === 1 ? 'one copy' : `${store.quota} copies`} at a time.`}
</p>

<InstanceTable instances={visible} />

<style>
	.lead {
		margin: 0.75rem 0 1.5rem;
	}
</style>
