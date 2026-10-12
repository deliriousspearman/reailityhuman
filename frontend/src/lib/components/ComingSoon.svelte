<script lang="ts">
	// Stands in for pages of features that aren't built yet (Pro Labs and their instances).
	let { title, children }: { title: string; children?: import('svelte').Snippet } = $props();
</script>

<div class="soon-page">
	<h1>{title} <span class="soon-tag">Soon</span></h1>
	<p class="lead">
		{#if children}{@render children()}{:else}This isn't built yet.{/if}
	</p>
	<a class="btn btn-primary" href="/machines">Deploy a machine instead</a>
</div>

<style>
	.soon-page {
		display: grid;
		gap: 1rem;
		justify-items: start;
		max-width: 36rem;
		padding-block: 3rem;
	}
	h1 .soon-tag {
		vertical-align: middle;
		font-size: 0.8rem;
	}
	.lead {
		color: var(--lms-gray-2);
	}
</style>
