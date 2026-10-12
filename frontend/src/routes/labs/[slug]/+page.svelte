<script lang="ts">
	import { page } from '$app/state';
	import ComingSoon from '$lib/components/ComingSoon.svelte';
	import { findLab } from '$lib/labs';

	const lab = $derived(findLab(page.params.slug ?? ''));
</script>

<svelte:head><title>{lab?.title ?? 'Pro Lab'} · Codex Labs</title></svelte:head>

<ComingSoon title={lab?.title ?? 'Pro Labs'}>
	Pro Labs can't be deployed yet. {lab ? lab.description : ''} <a href="/labs">See the planned labs</a>.
</ComingSoon>
