<script lang="ts">
	// Instances in a table: which lab, whose, its state and how many machines are up. Used by the
	// Instances page and the admin overview.
	import { duration, instanceStates } from '$lib/format';
	import { findLab } from '$lib/mock/labs';
	import { store } from '$lib/mock/store.svelte';
	import type { Instance } from '$lib/types';
	import Status from './Status.svelte';

	let { instances }: { instances: Instance[] } = $props();

	function health(inst: Instance) {
		const states = Object.values(inst.machines);
		return { up: states.filter((s) => s === 'running').length, total: states.length, failing: states.filter((s) => s === 'error').length };
	}
</script>

<div class="table-wrap">
	<table class="table">
		<thead>
			<tr>
				<th scope="col">Lab</th>
				<th scope="col">Copy</th>
				<th scope="col">State</th>
				<th scope="col">Machines up</th>
				<th scope="col">Connected</th>
				<th scope="col">Time</th>
			</tr>
		</thead>
		<tbody>
			{#each instances as inst (inst.id)}
				{@const h = health(inst)}
				<tr>
					<th scope="row"><a href="/instances/{inst.id}">{findLab(inst.lab)?.title}</a></th>
					<td>{inst.kind === 'shared' ? 'Shared' : inst.owner === store.user.username ? 'Yours' : inst.owner}</td>
					<td><Status size="sm" {...instanceStates[inst.state]} /></td>
					<td class="mono">
						{h.up} of {h.total}
						{#if h.failing}<span class="failing">{h.failing} not responding</span>{/if}
					</td>
					<td class="mono">{inst.connected}</td>
					<td class="mono">
						{#if inst.expiresAt}deleted in {duration(inst.expiresAt - store.now)}
						{:else if inst.nextResetAt}resets in {duration(inst.nextResetAt - store.now)}
						{:else}—{/if}
					</td>
				</tr>
			{:else}
				<tr><td colspan="6">No instances running. Deploy one from a lab's page.</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.failing {
		margin-inline-start: 0.5rem;
		color: var(--lab-error);
	}
</style>
