<script lang="ts">
	import LabCard from '$lib/components/LabCard.svelte';
	import { labs } from '$lib/labs';
</script>

<svelte:head><title>Pro Labs · Codex Labs</title></svelte:head>

<section class="hero">
	<div class="hero-text">
		<h1>Pro Labs <span class="soon-tag">Soon</span></h1>
		<p>
			Realistic networks of vulnerable machines, shared or your own copy, reached over a VPN. They're not built yet:
			these are the labs that are planned. For now, <a href="/machines">deploy a single machine</a>.
		</p>
	</div>
	<div class="terminal hero-terminal" role="img" aria-label="Pro Labs aren't available yet">
		<div class="terminal-bar"><span>labs: ~</span></div>
		<div class="terminal-body">
			<p><span class="prompt">$</span> labs status</p>
			<p class="t-note">labs: not available yet. Coming after single machines.</p>
			<p><span class="prompt">$</span> <span class="cursor"></span></p>
		</div>
	</div>
</section>

<div class="lab-list">
	{#each labs as lab (lab.slug)}
		<LabCard {lab} />
	{/each}
</div>

<style>
	.hero {
		display: grid;
		gap: 1.5rem 2.5rem;
		align-items: center;
		margin-bottom: 2rem;
	}
	@media (min-width: 56rem) {
		.hero {
			grid-template-columns: minmax(0, 1fr) minmax(0, 27rem);
			padding-block: 1rem 1.5rem;
		}
	}
	h1 {
		font-size: clamp(2.75rem, 1.5rem + 4vw, 4.5rem);
		line-height: 1;
	}
	.hero-text p {
		max-width: 34rem;
		margin-top: 1rem;
		font-size: 1.1rem;
		color: var(--lms-gray-2);
	}
	.hero-terminal {
		box-shadow:
			0 0 0 1px color-mix(in srgb, var(--lms-lime) 8%, transparent),
			0 1.5rem 3rem -1rem rgb(0 0 0 / 0.6);
	}
	.hero-terminal .terminal-body {
		font-size: 0.8rem;
		white-space: normal;
	}
	h1 .soon-tag {
		vertical-align: middle;
		font-size: 0.9rem;
		line-height: 1.5rem;
	}
	.prompt {
		color: #9fef00;
	}
	.t-note {
		color: #8494b5;
	}
	.cursor {
		display: inline-block;
		width: 0.55rem;
		height: 1rem;
		vertical-align: -0.15rem;
		background: #9fef00;
	}
	@media (prefers-reduced-motion: no-preference) {
		.cursor {
			animation: blink 1.1s steps(1) infinite;
		}
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}

	.lab-list {
		display: grid;
		gap: 1rem;
		grid-template-columns: repeat(auto-fill, minmax(min(26rem, 100%), 1fr));
	}
</style>
