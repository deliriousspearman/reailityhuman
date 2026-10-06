<script lang="ts">
	import LabCard from '$lib/components/LabCard.svelte';
	import { duration, instanceStates, singleMachineStates } from '$lib/format';
	import { findLab } from '$lib/mock/labs';
	import { labs, store } from '$lib/mock/store.svelte';

	// The hero terminal lists what's running for this person: their own lab copies, the shared labs,
	// then their machines.
	const rows = $derived([...store.mine, ...store.instances.filter((i) => i.kind === 'shared')]);
</script>

<svelte:head><title>Pro Labs · Codex Labs</title></svelte:head>

<section class="hero">
	<div class="hero-text">
		<h1>Pro Labs</h1>
		<p>
			Realistic networks of vulnerable machines. Join the shared lab, or start your own copy and reset it whenever you
			like. Need just one system? <a href="/machines">Deploy a single machine</a>.
		</p>
	</div>
	<div class="terminal hero-terminal" role="img" aria-label="Your lab instances and their state">
		<div class="terminal-bar"><span>{store.user.username}@labs: ~</span></div>
		<div class="terminal-body">
			<p><span class="prompt">$</span> labs status</p>
			{#each rows as inst (inst.id)}
				{@const state = instanceStates[inst.state]}
				<p>
					<span class="t-name">{findLab(inst.lab)?.title.toLowerCase()}</span>
					<span class="t-kind">{inst.kind === 'shared' ? 'shared' : 'yours'}</span>
					<span class="t-state" data-tone={state.tone}>{state.label.toLowerCase()}</span>
					<span class="t-note">
						{#if inst.expiresAt}{duration(inst.expiresAt - store.now)} left{:else}{inst.connected} connected{/if}
					</span>
				</p>
			{/each}
			{#each store.myMachines as m (m.id)}
				{@const state = singleMachineStates[m.state]}
				<p>
					<span class="t-name">{m.name}</span>
					<span class="t-kind">machine</span>
					<span class="t-state" data-tone={state.tone}>{state.label.toLowerCase()}</span>
					<span class="t-note">{m.expiresAt === null ? 'kept' : m.state === 'expired' ? 'powered off' : `${duration(m.expiresAt - store.now)} left`}</span>
				</p>
			{/each}
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
	.t-note {
		white-space: nowrap;
	}
	.hero-terminal p {
		display: grid;
		grid-template-columns: 12ch 7ch 8ch 1fr;
		gap: 0 0.75rem;
	}
	.hero-terminal p:first-child,
	.hero-terminal p:last-child {
		display: block;
	}
	.prompt,
	.t-state[data-tone='up'] {
		color: #9fef00;
	}
	.t-name {
		color: #e4e9f4;
	}
	.t-kind,
	.t-note {
		color: #8494b5;
	}
	.t-state[data-tone='busy'] {
		color: #5cb2ff;
	}
	.t-state[data-tone='down'] {
		color: #8494b5;
	}
	.t-state[data-tone='error'] {
		color: #ff3e3e;
	}
	.t-state[data-tone='warn'] {
		color: #ffaf00;
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
	@media (max-width: 30rem) {
		.hero-terminal p {
			grid-template-columns: 1fr auto;
		}
		.t-kind,
		.t-note {
			display: none;
		}
	}

	.lab-list {
		display: grid;
		gap: 1rem;
		grid-template-columns: repeat(auto-fill, minmax(min(26rem, 100%), 1fr));
	}
</style>
