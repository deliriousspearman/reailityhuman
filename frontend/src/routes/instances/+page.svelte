<script lang="ts">
	import Status from '$lib/components/Status.svelte';
	import { duration, singleMachineStates } from '$lib/format';
	import { store } from '$lib/store.svelte';

	const HOUR = 3_600_000;
</script>

<svelte:head><title>Instances · Codex Labs</title></svelte:head>

<h1>Instances</h1>
<p class="lead">Pro Labs deployed now, each a set of machines that's reset and destroyed together. <a href="/labs">Deploy a lab</a>.</p>

<div class="table-wrap">
	<table class="table">
		<thead>
			<tr>
				<th scope="col">Instance</th>
				<th scope="col">Lab</th>
				<th scope="col">Owner</th>
				<th scope="col">Machines</th>
				<th scope="col">State</th>
				<th scope="col">Time left</th>
			</tr>
		</thead>
		<tbody>
			{#each store.instances as i (i.id)}
				{@const left = i.expiresAt === null ? null : i.expiresAt - store.now}
				<tr>
					<th scope="row"><a class="mono" href="/instances/{i.id}">{i.id}</a></th>
					<td><a href="/labs/{i.lab}">{i.title}</a></td>
					<td class="mono">{i.owner}</td>
					<td class="mono">{i.machines.filter((m) => m.state === 'running').length} of {i.machines.length} running</td>
					<td><Status size="sm" {...singleMachineStates[i.state]} /></td>
					<td class="mono" class:soon={left !== null && left < HOUR}>
						{#if left === null}
							kept permanently
						{:else if i.state === 'expired'}
							deleted in {duration(i.expiresAt! + store.grace - store.now)}
						{:else}
							{duration(left)}
						{/if}
					</td>
				</tr>
			{:else}
				<tr><td colspan="6">{store.loaded ? 'No labs deployed.' : 'Loading…'}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.lead {
		margin-block: 0.75rem 1.5rem;
		color: var(--lms-gray-2);
	}
	.soon {
		color: var(--lab-warn);
	}
</style>
