<script lang="ts">
	// A lab on the Pro Labs page: one that can be deployed (a link to its page), or a planned one,
	// greyed out with a "Soon" tag.
	import type { Level } from '$lib/types';

	let {
		title,
		description,
		level,
		tags,
		image,
		href,
		note,
	}: { title: string; description: string; level: Level; tags: string[]; image?: string; href?: string; note: string } = $props();
</script>

<article class="lab-card" class:soon={!href}>
	<header>
		<div class="card-title">
			{#if image}<img class="picture" src={image} alt="" width="56" height="56" />{/if}
			<h2>{#if href}<a {href}>{title}</a>{:else}{title}{/if}</h2>
		</div>
		<span class="level-chip" data-level={level.toLowerCase()}>{level}</span>
	</header>
	<p>{description}</p>
	<ul class="lab-tags">
		{#each tags as tag, i (tag)}
			<li class="tag" class:tag-accent={i === 0}>{tag}</li>
		{/each}
	</ul>
	<footer>
		<div class="footer-row">{#if !href}<span class="soon-tag">Soon</span>{/if} <span>{note}</span></div>
	</footer>
</article>

<style>
	.lab-card {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1.25rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-lg);
		background: var(--lms-panel);
	}
	/* Not deployable yet: dimmed, and it doesn't lift on hover the way live cards do. */
	.lab-card.soon {
		border-style: dashed;
	}
	.lab-card.soon > :not(footer) {
		opacity: 0.55;
		filter: grayscale(0.6);
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.card-title {
		display: flex;
		align-items: center;
		gap: 0.875rem;
		min-width: 0;
	}
	.picture {
		flex-shrink: 0;
		width: 3.5rem;
		height: 3.5rem;
		border-radius: var(--lms-radius-md);
		border: var(--lms-border-width) solid var(--lms-gray-5);
		background: #0d1420;
	}
	h2 {
		font-size: 1.3rem;
	}
	/* The whole card is the link's target. */
	h2 a {
		color: inherit;
		text-decoration: none;
	}
	h2 a::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
	}
	.lab-card:not(.soon):hover {
		border-color: var(--lms-lime);
	}
	.lab-card > p {
		flex: 1;
		color: var(--lms-gray-2);
	}
	.lab-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	footer {
		display: grid;
		gap: 0.4rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--lms-gray-5);
		font: 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.footer-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}
</style>
