<script lang="ts">
	// The instance's network as learners experience it: their computer, the WireGuard tunnel to the
	// lab gateway, the entry network behind it, and the networks further in that are only reached by
	// pivoting. Each machine is a tile on its network's bus; a machine on two networks appears on both.
	// Tiles are buttons that select the machine (bindable `selected`).
	import { machineStates } from '$lib/format';
	import type { Instance, Lab, Network } from '$lib/types';
	import Status from './Status.svelte';

	let { lab, instance, selected = $bindable() }: { lab: Lab; instance: Instance; selected?: string } = $props();

	const entry = $derived(lab.networks.find((n) => n.entry) ?? lab.networks[0]);
	const others = $derived(lab.networks.filter((n) => n !== entry));

	function machinesOn(network: string) {
		return lab.machines
			.filter((m) => m.nics.some((nic) => nic.network === network))
			.map((m) => ({ machine: m, ip: m.nics.find((nic) => nic.network === network)!.ip }));
	}

	/** Machines on both the entry network and this one: the way in. */
	function pivotsTo(network: string) {
		return lab.machines
			.filter((m) => m.nics.some((n) => n.network === network) && m.nics.length > 1)
			.map((m) => m.name);
	}
</script>

{#snippet segment(network: Network)}
	<section class="segment" class:entry={network.entry} aria-label="{network.name} network">
		<header class="segment-head">
			<h3>{network.name}</h3>
			<code>{network.cidr}</code>
			{#if network.entry}<span class="tag tag-accent">Entry point</span>{/if}
		</header>
		<ul class="machines">
			{#each machinesOn(network.name) as { machine, ip } (machine.name)}
				{@const state = machineStates[instance.machines[machine.name] ?? 'stopped']}
				{@const elsewhere = machine.nics.filter((n) => n.network !== network.name)}
				<li>
					<button
						type="button"
						class="machine"
						data-tone={state.tone}
						aria-pressed={selected === machine.name}
						onclick={() => (selected = selected === machine.name ? undefined : machine.name)}
					>
						<span class="m-top">
							<span class="m-name">{machine.name}</span>
							<span class="os" data-os={machine.os.toLowerCase()}>{machine.os}</span>
						</span>
						<span class="m-ip">{ip}</span>
						<span class="m-role">{machine.role}</span>
						<span class="m-foot">
							<Status size="sm" {...state} />
							{#if elsewhere.length}<span class="m-also">+ {elsewhere.map((n) => n.network).join(', ')}</span>{/if}
						</span>
					</button>
				</li>
			{/each}
		</ul>
	</section>
{/snippet}

<div class="map">
	<div class="uplink">
		<div class="node you">
			<span class="node-title">Your computer</span>
			<span class="node-note">WireGuard client</span>
		</div>
		<div class="tunnel" aria-hidden="true">
			<span>{instance.connected} connected</span>
		</div>
		<div class="node gateway">
			<span class="node-title">Lab gateway</span>
			<code>{instance.endpoint}</code>
			<span class="node-note">Not a target</span>
		</div>
	</div>

	{@render segment(entry)}

	{#each others as network (network.name)}
		{@const via = pivotsTo(network.name)}
		<p class="pivot">
			Not routed over the VPN{#if via.length}. Reach it through {via.join(' or ')}{/if}.
		</p>
		{@render segment(network)}
	{/each}
</div>

<style>
	.map {
		--wire-gap: 1.75rem;
		padding: 1.25rem;
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lab-radius);
		/* A faint dot grid, like a network diagram's canvas. */
		background:
			radial-gradient(circle, color-mix(in srgb, var(--lms-gray-4) 35%, transparent) 1px, transparent 1.2px) 0 0 / 18px
				18px,
			var(--lms-black);
	}

	/* You ── tunnel ── gateway, with a wire from the gateway down to the entry network. */
	.uplink {
		display: flex;
		align-items: center;
		margin-bottom: var(--wire-gap);
	}
	.node {
		position: relative;
		display: grid;
		gap: 0.1rem;
		padding: 0.55rem 0.85rem;
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lab-radius-sm);
		background: var(--lms-panel);
		font-size: 0.8rem;
	}
	.node-title {
		font: 700 0.9rem var(--lms-display);
		color: var(--lms-white);
	}
	.node code {
		color: var(--lms-lime-text);
		font-size: 0.78rem;
	}
	.node-note {
		font: 500 0.7rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.you {
		border-style: dashed;
	}
	.gateway {
		border-color: var(--lms-accent);
	}
	.gateway::after {
		content: '';
		position: absolute;
		left: 1.5rem;
		top: 100%;
		width: 3px;
		height: calc(var(--wire-gap) + 1px);
		background: var(--lms-lime);
	}
	.tunnel {
		position: relative;
		flex: 1;
		min-width: 3rem;
		max-width: 16rem;
		height: 3px;
		/* A dashed lime line: an encrypted tunnel rather than a cable. */
		background: repeating-linear-gradient(90deg, var(--lms-lime) 0 8px, transparent 8px 13px);
	}
	.tunnel span {
		position: absolute;
		left: 50%;
		bottom: 0.4rem;
		translate: -50% 0;
		font: 600 0.7rem var(--lms-mono);
		color: var(--lms-gray-3);
		white-space: nowrap;
	}
	/* Phones: the connected count is in the stat tiles above, and there's no room for it here. */
	@media (max-width: 30rem) {
		.map {
			padding: 0.9rem;
		}
		.tunnel span {
			display: none;
		}
	}
	@media (prefers-reduced-motion: no-preference) {
		.tunnel {
			animation: flow 1.2s linear infinite;
		}
	}
	@keyframes flow {
		to {
			background-position: 13px 0;
		}
	}

	/* A network: a heading on a bus line, machines hanging off it. */
	.segment {
		--bus: var(--lab-wire);
		border-top: 3px solid var(--bus);
		padding-top: 0.6rem;
	}
	.segment.entry {
		--bus: var(--lms-lime);
	}
	.segment-head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.35rem 0.75rem;
	}
	.segment-head h3 {
		font-size: 1.05rem;
	}
	.segment-head code {
		color: var(--lms-gray-2);
		font-size: 0.8rem;
	}
	.segment-head .tag {
		align-self: center;
	}

	.machines {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(9rem, 100%), 1fr));
		gap: 0.75rem;
		margin: 0.9rem 0 0;
		padding: 0;
		list-style: none;
	}
	.machine {
		--tone: var(--lms-gray-5);
		position: relative;
		display: grid;
		gap: 0.2rem;
		width: 100%;
		height: 100%;
		padding: 0.65rem 0.75rem 0.6rem;
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lab-radius-sm);
		background: var(--lms-panel);
		color: inherit;
		font: inherit;
		text-align: start;
		cursor: pointer;
	}
	.machine:hover {
		border-color: var(--lms-gray-3);
	}
	.machine[aria-pressed='true'] {
		border-color: var(--lms-lime);
		box-shadow: 0 0 0 1px var(--lms-lime);
	}
	.machine[data-tone='error'] {
		border-left: 3px solid var(--lab-error);
	}
	.machine[data-tone='busy'] {
		border-style: dashed;
		border-color: var(--lab-busy);
	}
	.machine[data-tone='down'] .m-name,
	.machine[data-tone='down'] .m-ip {
		color: var(--lms-gray-3);
	}
	.m-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.m-name {
		font: 700 0.95rem var(--lms-mono);
		color: var(--lms-white);
	}
	.m-ip {
		font: 500 0.8rem var(--lms-mono);
		color: var(--lms-lime-text);
	}
	.m-role {
		font-size: 0.8rem;
		line-height: 1.35;
		color: var(--lms-gray-2);
	}
	.m-foot {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.25rem 0.5rem;
		margin-top: 0.35rem;
	}
	.m-also {
		font: 500 0.7rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.os {
		--os: var(--lms-gray-3);
		padding: 0 0.4rem;
		border: 1px solid var(--os);
		border-radius: 4px;
		font: 600 0.68rem var(--lms-mono);
		color: var(--os);
	}
	.os[data-os='windows'] {
		--os: var(--lms-lime-text);
	}
	.os[data-os='linux'] {
		--os: var(--lms-medium);
	}

	/* Between networks: a dashed wire, since the VPN doesn't route there. */
	.pivot {
		position: relative;
		margin: 0.5rem 0;
		padding: 0.9rem 0 0.9rem 2.5rem;
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
	.pivot::before {
		content: '';
		position: absolute;
		left: 1.5rem;
		top: 0;
		bottom: 0;
		border-left: 3px dashed var(--lab-wire);
	}
</style>
