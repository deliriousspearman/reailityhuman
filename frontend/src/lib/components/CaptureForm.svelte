<script lang="ts">
	// Starting a capture on the machines picked on the diagram: between them, across a subnet, or
	// with a filter of your own, narrowed by a preset (DNS, SMB…). The panel limits it to those
	// machines' traffic whatever the filter says; Check shows exactly what tcpdump will run.
	import { api, ApiError } from '$lib/api';
	import { allOf, durations, hostsFilter, presets, subnetOf, validSubnet, type CaptureMode } from '$lib/captures';
	import type { Capture, CaptureLimits, SingleMachine } from '$lib/types';
	import Icon from './Icon.svelte';

	let {
		machines,
		limits,
		onstarted,
	}: { machines: SingleMachine[]; limits: CaptureLimits; onstarted: (c: Capture) => void } = $props();

	let mode = $state<CaptureMode>('hosts');
	let preset = $state('');
	let subnet = $state('');
	let custom = $state('');
	let seconds = $state(300);
	let checked = $state<{ filter: string; effective?: string; problem?: string } | null>(null);
	let working = $state(false);
	let problem = $state('');

	const ips = $derived(machines.map((m) => m.ip).filter(Boolean));
	const missing = $derived(machines.filter((m) => !m.ip).map((m) => m.name));
	const choices = $derived(durations(limits.maxSeconds));
	const presetFilter = $derived(presets.find((p) => p.id === preset)?.filter ?? '');

	// A sensible subnet once there's an address to take it from.
	$effect(() => {
		if (!subnet && ips[0]) subnet = subnetOf(ips[0]);
	});
	$effect(() => {
		if (!choices.some((c) => c.seconds === seconds) && choices.length) seconds = choices[Math.min(3, choices.length - 1)].seconds;
	});

	const filter = $derived(
		mode === 'hosts' ? allOf(hostsFilter(ips), presetFilter) : mode === 'subnet' ? allOf(validSubnet(subnet) ? `net ${subnet.trim()}` : '', presetFilter) : custom,
	);
	const blocker = $derived(
		machines.length === 0
			? 'Pick machines on the diagram first.'
			: mode === 'subnet' && !validSubnet(subnet)
				? 'Enter a subnet such as 192.0.2.0/24.'
				: mode === 'hosts' && ips.length === 0
					? 'None of these machines has an address yet.'
					: '',
	);

	// Typing your own starts from what's built so far.
	function toCustom() {
		if (mode !== 'custom') custom = filter;
		mode = 'custom';
	}

	const body = () => ({ machineIds: machines.map((m) => m.id), filter });

	async function check() {
		problem = '';
		working = true;
		const f = filter;
		try {
			const r = await api<{ effectiveFilter: string }>('/captures/check', { method: 'POST', body: body() });
			checked = { filter: f, effective: r.effectiveFilter };
		} catch (e) {
			checked = { filter: f, problem: e instanceof ApiError ? e.message : String(e) };
		} finally {
			working = false;
		}
	}

	async function start() {
		problem = '';
		working = true;
		try {
			onstarted(await api<Capture>('/captures', { method: 'POST', body: { ...body(), seconds } }));
			checked = null;
		} catch (e) {
			problem = e instanceof ApiError ? e.message : String(e);
		} finally {
			working = false;
		}
	}
</script>

<form class="capture-form panel" onsubmit={(e) => (e.preventDefault(), start())}>
	<div class="row">
		<fieldset class="modes">
			<legend class="field-label">Capture</legend>
			<label><input type="radio" bind:group={mode} value="hosts" /> {machines.length === 2 ? 'Between these two' : machines.length > 2 ? 'Among these' : 'This machine'}</label>
			<label><input type="radio" bind:group={mode} value="subnet" /> A subnet</label>
			<label><input type="radio" bind:group={mode} value="custom" onchange={toCustom} /> Your own filter</label>
		</fieldset>
		<div class="field duration">
			<label for="capture-seconds">For up to</label>
			<select id="capture-seconds" class="select" bind:value={seconds}>
				{#each choices as c (c.seconds)}<option value={c.seconds}>{c.label}</option>{/each}
			</select>
		</div>
	</div>

	{#if mode === 'subnet'}
		<div class="field">
			<label for="capture-subnet">Subnet</label>
			<input id="capture-subnet" class="input mono" bind:value={subnet} placeholder="192.0.2.0/24" spellcheck="false" autocomplete="off" />
		</div>
	{/if}

	{#if mode !== 'custom'}
		<div class="presets" role="group" aria-label="Only this kind of traffic">
			<span class="field-label">Only</span>
			<button type="button" class="chip" aria-pressed={preset === ''} onclick={() => (preset = '')}>Everything</button>
			{#each presets as p (p.id)}
				<button type="button" class="chip" aria-pressed={preset === p.id} title={p.filter} onclick={() => (preset = p.id)}>{p.label}</button>
			{/each}
		</div>
	{/if}

	<div class="field">
		<label for="capture-filter">BPF filter <span class="optional">(tcpdump syntax; empty: all their traffic)</span></label>
		{#if mode === 'custom'}
			<input
				id="capture-filter"
				class="input mono"
				bind:value={custom}
				maxlength="1000"
				placeholder="e.g. tcp port 445 and host 192.0.2.10"
				spellcheck="false"
				autocomplete="off"
			/>
		{:else}
			<div class="built">
				<code id="capture-filter">{filter || '(all their traffic)'}</code>
				<button type="button" class="btn btn-quiet btn-sm" onclick={toCustom}>Edit</button>
			</div>
		{/if}
	</div>

	{#if missing.length && mode === 'hosts'}
		<p class="note">No address yet, so left out of the filter: {missing.join(', ')}.</p>
	{/if}
	{#if checked && checked.filter === filter}
		{#if checked.problem}
			<p class="note error" role="alert">{checked.problem}</p>
		{:else}
			<p class="note">tcpdump will run <code>{checked.effective}</code></p>
		{/if}
	{/if}
	{#if problem}<p class="note error" role="alert">{problem}</p>{/if}

	<div class="actions">
		<button type="submit" class="btn btn-primary" disabled={!!blocker || working}><Icon name="capture" /> Start capture</button>
		<button type="button" class="btn" disabled={!!blocker || working} onclick={check}>Check filter</button>
		{#if blocker}<span class="note">{blocker}</span>{/if}
	</div>
	<p class="hint">
		Only these machines' traffic is captured, whatever the filter says. Captures stop after the time above or {limits.maxMB} MB, and are kept for {limits.keepDays} day{limits.keepDays === 1 ? '' : 's'}.
	</p>
</form>

<style>
	.capture-form {
		display: grid;
		gap: 1rem;
		padding: 1rem 1.25rem;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: end;
		justify-content: space-between;
		gap: 1rem;
	}
	.modes {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem 1.25rem;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.modes legend {
		margin-bottom: 0.4rem;
	}
	.modes label {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		cursor: pointer;
	}
	.duration {
		min-width: 11rem;
	}
	.presets {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}
	.presets .field-label {
		margin-right: 0.3rem;
	}
	.chip {
		padding: 0.2rem 0.6rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-xs);
		background: none;
		font: 600 0.78rem var(--lms-mono);
		color: var(--lms-gray-2);
		cursor: pointer;
	}
	.chip:hover {
		border-color: var(--lms-gray-4);
	}
	.chip[aria-pressed='true'] {
		border-color: var(--lms-lime);
		color: var(--lms-lime-text);
	}
	.optional {
		font-weight: 400;
		color: var(--lms-gray-3);
	}
	.built {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-height: 2.5rem;
		padding: 0.3rem 0.4rem 0.3rem 0.75rem;
		border: var(--lms-border-width) dashed var(--lms-gray-5);
	}
	.built code {
		flex: 1;
		font: 0.85rem var(--lms-mono);
		color: var(--lms-lime-text);
		overflow-wrap: anywhere;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 0.75rem;
	}
	.note {
		font-size: 0.875rem;
		color: var(--lms-gray-2);
		overflow-wrap: anywhere;
	}
	.note code {
		font: 0.82rem var(--lms-mono);
		color: var(--lms-lime-text);
	}
	.note.error {
		color: var(--lab-error);
	}
	.hint {
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
</style>
