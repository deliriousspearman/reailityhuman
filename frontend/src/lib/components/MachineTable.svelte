<script lang="ts">
	// Single machines in a table: name, what it runs, its address, state and how long it has left.
	// Used on the Machines page (your own) and the admin page (everyone's, with owners).
	import { duration, singleMachineStates } from '$lib/format';
	import { GRACE, store } from '$lib/mock/store.svelte';
	import { findTemplate } from '$lib/mock/templates';
	import type { SingleMachine } from '$lib/types';
	import Icon from './Icon.svelte';
	import Status from './Status.svelte';

	let {
		machines,
		owners = false,
		empty = 'No machines yet.',
	}: { machines: SingleMachine[]; owners?: boolean; empty?: string } = $props();

	const HOUR = 3_600_000;
</script>

<div class="table-wrap">
	<table class="table">
		<thead>
			<tr>
				<th scope="col">Name</th>
				<th scope="col">Runs</th>
				{#if owners}<th scope="col">Owner</th>{/if}
				<th scope="col">Address</th>
				<th scope="col">State</th>
				<th scope="col">Time left</th>
				<th scope="col"><span class="visually-hidden">Actions</span></th>
			</tr>
		</thead>
		<tbody>
			{#each machines as m (m.id)}
				{@const t = findTemplate(m.template)}
				{@const left = m.expiresAt === null ? null : m.expiresAt - store.now}
				<tr>
					<th scope="row"><a href="/machines/{m.id}">{m.name}</a></th>
					<td>
						{#if t}<span class="os" data-os={t.os.toLowerCase()}>{t.os}</span>{/if}
						{t?.name} {m.version}
					</td>
					{#if owners}<td class="mono">{m.owner}</td>{/if}
					<td class="mono">{m.ip}</td>
					<td><Status size="sm" {...singleMachineStates[m.state]} /></td>
					<td class="mono" class:soon={left !== null && left < HOUR}>
						{#if left === null}
							kept permanently
						{:else if m.state === 'expired'}
							deleted in {duration(m.expiresAt! + GRACE - store.now)}
						{:else}
							{duration(left)}
						{/if}
					</td>
					<td class="row-actions">
						{#if store.canControlMachine(m) && m.expiresAt !== null && m.state !== 'destroying'}
							<button class="btn btn-sm" type="button" onclick={() => store.extendMachine(m, 2)}>
								<Icon name="clock" />
								{m.state === 'expired' ? 'Extend and start' : '+2 h'}
							</button>
						{/if}
					</td>
				</tr>
			{:else}
				<tr><td colspan={owners ? 7 : 6}>{empty}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	td .os {
		margin-inline-end: 0.4rem;
	}
	.soon {
		color: var(--lab-warn);
	}
	.row-actions {
		text-align: end;
		padding-block: 0.35rem;
	}
	.row-actions :global(svg) {
		width: 0.9rem;
		height: 0.9rem;
	}
</style>
