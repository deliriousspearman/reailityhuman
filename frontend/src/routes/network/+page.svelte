<script lang="ts">
	// Your machines' network, and packet captures between them (backend/app/capture.py). Pick machines
	// on the diagram (or come from a machine's or lab's page with ?machines= or ?instance=), start a
	// capture, and watch it live; what they said to each other is drawn on the diagram.
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { size } from '$lib/captures';
	import CaptureForm from '$lib/components/CaptureForm.svelte';
	import CaptureView from '$lib/components/CaptureView.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import NetworkDiagram from '$lib/components/NetworkDiagram.svelte';
	import Status from '$lib/components/Status.svelte';
	import { ago } from '$lib/format';
	import { store } from '$lib/store.svelte';
	import type { Capture, Conversation } from '$lib/types';

	// Running captures move on; the list catches up this often.
	const LIST_EVERY = 10_000;

	let selected = $state<string[]>([]);
	let captures = $state<Capture[]>([]);
	let open = $state<Capture | null>(null);
	let conversations = $state<Conversation[]>([]);
	let problem = $state('');

	const mine = $derived(store.myMachines);
	const chosen = $derived(mine.filter((m) => selected.includes(m.id)));
	const limits = $derived(store.config?.capture);
	const myCaptures = $derived(store.user ? captures.filter((c) => c.owner === store.user) : captures);

	// From a machine's or a lab's page.
	let fromLink = false;
	$effect(() => {
		if (fromLink || !store.loaded) return;
		fromLink = true;
		const q = page.url.searchParams;
		const ids = q.get('machines')?.split(',') ?? [];
		const instance = q.get('instance');
		selected = mine.filter((m) => ids.includes(m.id) || (instance && m.instanceId === instance)).map((m) => m.id);
	});

	async function loadList() {
		try {
			captures = await api<Capture[]>('/captures');
			problem = '';
			if (open) {
				const fresh = captures.find((c) => c.id === open!.id);
				// The open one's live view keeps its own counts; take the rest (state, detail) from here.
				if (fresh && fresh.state !== open.state) open = fresh;
			}
		} catch (e) {
			problem = e instanceof ApiError ? e.message : String(e);
		}
	}

	onMount(() => {
		void loadList();
		const timer = setInterval(loadList, LIST_EVERY);
		return () => clearInterval(timer);
	});

	function started(c: Capture) {
		open = c;
		captures = [c, ...captures];
	}

	function changed(c: Capture) {
		open = c;
		captures = captures.map((x) => (x.id === c.id ? c : x));
	}

	async function remove(c: Capture) {
		try {
			await api(`/captures/${c.id}`, { method: 'DELETE' });
			captures = captures.filter((x) => x.id !== c.id);
			if (open?.id === c.id) close();
		} catch (e) {
			store.say(e instanceof ApiError ? e.message : String(e));
		}
	}

	function close() {
		open = null;
		conversations = [];
	}

	const tones = { running: 'busy', stopped: 'up', failed: 'error' } as const;
	const labels = { running: 'Capturing', stopped: 'Finished', failed: 'Failed' } as const;
</script>

<svelte:head><title>Network · Codex Labs</title></svelte:head>

<header class="title-row">
	<div>
		<h1>Network</h1>
		<p class="subtitle">
			{#if store.user}Machines deployed as <strong>{store.user}</strong>, on the lab's LAN.{:else}Everyone's machines: deploy one under your name to see only yours.{/if}
			Pick machines to capture the traffic between them.
		</p>
	</div>
</header>

{#if limits && !limits.configured}
	<div class="banner banner-warn">
		<p><strong>Packet capture isn't set up on this panel yet.</strong> It needs the capture appliance: see the admin guide.</p>
	</div>
{/if}

{#if !store.loaded}
	<p class="loading">Loading…</p>
{:else if mine.length === 0}
	<div class="panel empty">
		<p>No machines yet.</p>
		<a class="btn btn-primary" href="/machines"><Icon name="plus" /> Deploy a machine</a>
	</div>
{:else}
	<NetworkDiagram machines={mine} instances={store.instances} bind:selected {conversations} />

	{#if limits?.configured}
		<div class="section-heading">
			<h2>Capture</h2>
			<p>
				{#if chosen.length}{chosen.map((m) => m.name).join(', ')}
					<button class="btn btn-quiet btn-sm" type="button" onclick={() => (selected = [])}>Clear</button>
				{:else}Select machines on the diagram{/if}
			</p>
		</div>
		{#if open}
			<CaptureView capture={open} onchange={changed} onconversations={(c) => (conversations = c)} onclose={close} />
		{/if}
		{#if !open || open.state !== 'running'}
			<CaptureForm machines={chosen} {limits} onstarted={started} />
		{/if}
	{/if}
{/if}

{#if myCaptures.length}
	<div class="section-heading"><h2>Captures</h2><p>Kept for {limits?.keepDays ?? 1} day{(limits?.keepDays ?? 1) === 1 ? '' : 's'}, or until their machines are destroyed.</p></div>
	{#if problem}<p class="problem" role="alert">{problem}</p>{/if}
	<div class="table-wrap">
		<table class="table">
			<thead>
				<tr>
					<th scope="col">Machines</th>
					<th scope="col">Filter</th>
					<th scope="col">Started</th>
					<th scope="col">Packets</th>
					<th scope="col">Size</th>
					<th scope="col">State</th>
					<th scope="col"><span class="visually-hidden">Actions</span></th>
				</tr>
			</thead>
			<tbody>
				{#each myCaptures as c (c.id)}
					<tr class:current={open?.id === c.id}>
						<th scope="row">{c.machines.map((m) => m.name).join(', ')}</th>
						<td class="mono filter" title={c.effectiveFilter}>{c.filter || 'all their traffic'}</td>
						<td>{ago(c.startedAt, store.now)}</td>
						<td class="mono">{c.packets.toLocaleString()}</td>
						<td class="mono">{size(c.bytes)}</td>
						<td title={c.detail}><Status size="sm" tone={tones[c.state]} label={labels[c.state]} /></td>
						<td class="row-actions">
							<button class="btn btn-sm" type="button" onclick={() => (open = c)}><Icon name="eye" /> View</button>
							<a class="btn btn-sm" href="/api/captures/{c.id}/pcap" download aria-label="Download {c.id}.pcap"><Icon name="download" /></a>
							<button class="btn btn-quiet btn-sm" type="button" disabled={c.state === 'running'} onclick={() => remove(c)} aria-label="Delete capture {c.id}">
								<Icon name="trash" />
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.title-row {
		margin-bottom: 1.25rem;
	}
	.subtitle {
		margin-top: 0.4rem;
		color: var(--lms-gray-2);
	}
	.subtitle strong {
		color: var(--lms-white);
	}
	.banner {
		margin-bottom: 1.25rem;
	}
	.loading {
		padding-block: 3rem;
		color: var(--lms-gray-3);
	}
	.empty {
		display: grid;
		gap: 1rem;
		justify-items: start;
		padding: 1.5rem;
	}
	.section-heading p {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	:global(.capture) + :global(.capture-form) {
		margin-top: 1rem;
	}
	.filter {
		max-width: 22rem;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	tr.current > * {
		background: color-mix(in srgb, var(--lms-lime) 6%, transparent);
	}
	.row-actions {
		display: flex;
		gap: 0.35rem;
		justify-content: end;
	}
	.problem {
		margin-bottom: 0.75rem;
		color: var(--lab-error);
	}
</style>
