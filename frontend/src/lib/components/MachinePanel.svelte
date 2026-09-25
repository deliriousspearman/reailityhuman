<script lang="ts">
	// Details and controls for the machine selected on the network map.
	import { ago, machineStates } from '$lib/format';
	import { store } from '$lib/mock/store.svelte';
	import type { Instance, Lab } from '$lib/types';
	import type { ConfirmRequest } from './ConfirmDialog.svelte';
	import Icon from './Icon.svelte';
	import Status from './Status.svelte';

	let {
		lab,
		instance,
		name,
		confirm,
		onclose,
	}: { lab: Lab; instance: Instance; name: string; confirm: (r: ConfirmRequest) => void; onclose: () => void } = $props();

	const machine = $derived(lab.machines.find((m) => m.name === name)!);
	const state = $derived(instance.machines[name] ?? 'stopped');
	const busy = $derived(state === 'booting' || state === 'resetting' || instance.state !== 'running');
	const canControl = $derived(store.canControl(instance));
	// Domain labs reset as a whole, so only admins may reset one machine (with a warning).
	const canResetOne = $derived(lab.resetScope === 'machine' || store.isAdmin);
	const others = $derived(instance.kind === 'shared' && instance.connected > 0);

	function resetMachine() {
		confirm({
			title: `Reset ${name}?`,
			body:
				(lab.resetScope === 'lab'
					? `${lab.title} is a domain lab. Resetting one machine can break its trust with the domain controller, so reset the whole lab unless you know it's safe. `
					: '') +
				`${name} goes back to its clean snapshot and anything changed on it is lost` +
				(others ? `, including other learners' work (${instance.connected} connected).` : '.'),
			label: `Reset ${name}`,
			danger: true,
			run: () => store.resetMachine(instance, name),
		});
	}
</script>

<section class="machine-panel panel" aria-labelledby="machine-title">
	<header>
		<div>
			<h2 id="machine-title">{machine.name}</h2>
			<p>{machine.role}</p>
		</div>
		<button class="btn btn-quiet btn-sm close" type="button" onclick={onclose}>
			<Icon name="close" label="Close machine details" />
		</button>
	</header>

	<Status {...machineStates[state]} />

	<dl>
		<div>
			<dt>Operating system</dt>
			<dd>{machine.os}</dd>
		</div>
		{#each machine.nics as nic (nic.network)}
			<div>
				<dt>{nic.network}</dt>
				<dd><code>{nic.ip}</code></dd>
			</div>
		{/each}
		{#if lab.environment === 'domain'}
			<div>
				<dt>Domain</dt>
				<dd>{machine.domainJoined ? lab.domain : 'Not joined'}</dd>
			</div>
		{/if}
		{#if instance.lastResetAt}
			<div>
				<dt>Last reset</dt>
				<dd>{ago(instance.lastResetAt, store.now)}</dd>
			</div>
		{/if}
	</dl>

	{#if canControl}
		<div class="actions">
			{#if canResetOne}
				<button class="btn btn-danger" type="button" disabled={busy} onclick={resetMachine}>
					<Icon name="reset" /> Reset machine
				</button>
			{/if}
			<button class="btn" type="button" disabled={busy || state === 'stopped'} onclick={() => store.reboot(instance, name)}>
				<Icon name="reboot" /> Reboot
			</button>
			{#if state === 'stopped'}
				<button class="btn" type="button" disabled={instance.state !== 'running'} onclick={() => store.power(instance, name, true)}>
					<Icon name="power" /> Power on
				</button>
			{:else}
				<button class="btn" type="button" disabled={busy} onclick={() => store.power(instance, name, false)}>
					<Icon name="power" /> Power off
				</button>
			{/if}
			{#if store.isAdmin}
				<button class="btn" type="button" disabled title="Planned: browser console for admins">
					<Icon name="console" /> Console
				</button>
			{/if}
		</div>
		{#if lab.resetScope === 'lab'}
			<p class="note">Domain lab: reset the whole lab to keep the domain consistent.</p>
		{/if}
	{:else}
		<p class="note">
			Instructors reset machines in the shared lab. If {machine.name} is stuck, ask one, or start your own copy of {lab.title}.
		</p>
	{/if}
</section>

<style>
	.machine-panel {
		display: grid;
		gap: 1rem;
		align-content: start;
		padding: 1.25rem;
		border-top: 3px solid var(--lms-lime);
	}
	header {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
	}
	h2 {
		font: 700 1.4rem var(--lms-mono);
	}
	header p {
		font-size: 0.9rem;
		color: var(--lms-gray-2);
	}
	.close {
		padding: 0.3rem;
	}
	dl {
		display: grid;
		gap: 0.5rem;
		margin: 0;
		padding: 0.75rem 0;
		border-block: 1px solid var(--lms-gray-5);
		font-size: 0.875rem;
	}
	dl div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
	}
	dt {
		color: var(--lms-gray-3);
	}
	dd {
		margin: 0;
		color: var(--lms-white);
		text-align: end;
	}
	dd code {
		color: var(--lms-lime-text);
	}
	.actions {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.5rem;
	}
	.actions .btn {
		justify-content: flex-start;
	}
	.actions .btn-danger {
		grid-column: 1 / -1;
	}
	.note {
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
</style>
