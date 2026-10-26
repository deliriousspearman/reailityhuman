<script lang="ts">
	import LabCard from '$lib/components/LabCard.svelte';
	import { labs as designs } from '$lib/labs';
	import { store } from '$lib/store.svelte';
	import type { Lab } from '$lib/types';

	// The LMS's labs not in labs.yaml yet: designs, shown as planned.
	const planned = $derived(designs.filter((d) => !store.lab(d.slug)));

	function osTags(lab: Lab): string[] {
		const counts = lab.machines.reduce<Record<string, number>>((acc, m) => ((acc[m.os] = (acc[m.os] ?? 0) + 1), acc), {});
		return Object.entries(counts).map(([os, n]) => `${n} ${os}`);
	}
</script>

<svelte:head><title>Pro Labs · Codex Labs</title></svelte:head>

<section class="hero">
	<div class="hero-text">
		<h1>Pro Labs</h1>
		<p>
			Networks of vulnerable machines, deployed together as one instance and set up in order. Find the flags, then
			reset the whole lab and start again.
		</p>
	</div>
	<div class="terminal hero-terminal" role="img" aria-label="Pro Labs status">
		<div class="terminal-bar"><span>labs: ~</span></div>
		<div class="terminal-body">
			<p><span class="prompt">$</span> labs status</p>
			<p class="t-note">
				{store.labs.filter((l) => !l.planned).length} ready, {store.labs.filter((l) => l.planned).length + planned.length} planned,
				{store.instances.length} running
			</p>
			<p><span class="prompt">$</span> <span class="cursor"></span></p>
		</div>
	</div>
</section>

<div class="lab-list">
	{#each store.labs as lab (lab.slug)}
		{@const design = designs.find((d) => d.slug === lab.slug)}
		<LabCard
			title={lab.title}
			description={lab.description}
			level={lab.level}
			image={design?.image}
			href="/labs/{lab.slug}"
			tags={[lab.domain ? 'Active Directory' : 'Standalone hosts', `${lab.machines.length} machines`, `${lab.flags.length} flags`]}
			note={lab.planned ? 'Being built: not deployable yet' : `Needs about ${lab.memoryGB} GB of memory`}
		/>
	{/each}
	{#each planned as lab (lab.slug)}
		<LabCard
			title={lab.title}
			description={lab.description}
			level={lab.level}
			image={lab.image}
			tags={[lab.environment === 'domain' ? 'Active Directory' : 'Standalone hosts', `${lab.machines.length} machines`, ...osTags(lab)]}
			note="Not available to deploy yet"
		/>
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
