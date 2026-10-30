<script lang="ts">
	// One capture: its packets in a table, newest first. A running one's arrive over its WebSocket
	// every half second; a finished one's are read from its file. Its conversations go up to the
	// diagram (onconversations). Wireshark has the rest: Download .pcap.
	import { untrack } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { liveUrl, size } from '$lib/captures';
	import { duration } from '$lib/format';
	import { store } from '$lib/store.svelte';
	import type { Capture, CaptureLive, Conversation, PacketLine } from '$lib/types';
	import Icon from './Icon.svelte';
	import Status from './Status.svelte';

	let {
		capture,
		onchange,
		onconversations,
		onclose,
	}: { capture: Capture; onchange: (c: Capture) => void; onconversations: (c: Conversation[]) => void; onclose: () => void } = $props();

	// What the table can hold before it drops the oldest (the file has everything).
	const KEEP = 5000;
	const SHOW = 500;
	const PAGE = 1000;

	let rows = $state<PacketLine[]>([]);
	let count = $state(0);
	let bytes = $state(0);
	let paused = $state<PacketLine[] | null>(null);
	let find = $state('');
	let more = $state(false);
	let problem = $state('');
	let stopping = $state(false);

	const running = $derived(capture.state === 'running');
	const shown = $derived.by(() => {
		const list = paused ?? rows;
		const needle = find.trim().toLowerCase();
		const hits = needle
			? list.filter((p) => `${p.src} ${p.dst} ${p.proto} ${p.info}`.toLowerCase().includes(needle))
			: list;
		return hits.slice(-SHOW).reverse();
	});

	// Starts again only for another capture, or when this one finishes (then it's read from its file).
	$effect(() => {
		const id = capture.id;
		const live = capture.state === 'running';
		untrack(() => {
			rows = [];
			paused = null;
			problem = '';
			count = capture.packets;
			bytes = capture.bytes;
			onconversations(capture.conversations);
		});
		if (!live) {
			void loadFile(id, 0);
			return;
		}
		const ws = new WebSocket(liveUrl(id));
		ws.onmessage = (e) => {
			const msg = JSON.parse(e.data) as CaptureLive;
			if (msg.packets.length) rows = [...rows, ...msg.packets].slice(-KEEP);
			if (msg.count !== undefined) count = msg.count;
			if (msg.bytes !== undefined) bytes = msg.bytes;
			if (msg.conversations) onconversations(msg.conversations);
			if (msg.done) void finished(id);
		};
		ws.onerror = () => (problem = "Lost the live view. The capture carries on: reopen it to see where it's got to.");
		return () => ws.close();
	});

	async function finished(id: string) {
		try {
			onchange(await api<Capture>(`/captures/${id}`));
		} catch {}
	}

	async function loadFile(id: string, after: number) {
		try {
			const r = await api<{ packets: PacketLine[] }>(`/captures/${id}/packets?after=${after}&limit=${PAGE}`);
			if (id !== capture.id) return;
			rows = after ? [...rows, ...r.packets] : r.packets;
			more = r.packets.length === PAGE;
		} catch (e) {
			problem = e instanceof ApiError ? e.message : String(e);
		}
	}

	async function stop() {
		stopping = true;
		try {
			onchange(await api<Capture>(`/captures/${capture.id}/stop`, { method: 'POST' }));
		} catch (e) {
			problem = e instanceof ApiError ? e.message : String(e);
		} finally {
			stopping = false;
		}
	}

	const tones = { running: 'busy', stopped: 'up', failed: 'error' } as const;
	const labels = { running: 'Capturing', stopped: 'Finished', failed: 'Failed' } as const;
	const time = (t: number) => {
		const d = new Date(t * 1000);
		return `${d.toLocaleTimeString([], { hour12: false })}.${String(d.getMilliseconds()).padStart(3, '0')}`;
	};
</script>

<section class="capture panel" aria-label="Capture {capture.id}">
	<header>
		<div class="title">
			<h3>{capture.machines.map((m) => m.name).join(', ')} <span class="cid">{capture.id}</span></h3>
			<p class="meta">
				<Status size="sm" tone={tones[capture.state]} label={labels[capture.state]} />
				{#if running}
					<span>{duration(Math.max(0, capture.endsAt - store.now))} left</span>
				{:else if capture.detail}
					<span>{capture.detail}</span>
				{/if}
				<span>{count.toLocaleString()} packets, {size(bytes)}</span>
			</p>
			<p class="meta"><code title="What tcpdump ran: {capture.effectiveFilter}">{capture.filter || 'all their traffic'}</code></p>
		</div>
		<div class="actions">
			{#if running}
				<button class="btn btn-sm" type="button" onclick={() => (paused = paused ? null : [...rows])}>
					<Icon name={paused ? 'play' : 'stop'} />{paused ? 'Resume view' : 'Pause view'}
				</button>
				<button class="btn btn-sm btn-danger" type="button" disabled={stopping} onclick={stop}><Icon name="stop" /> Stop</button>
			{/if}
			<a class="btn btn-sm" href="/api/captures/{capture.id}/pcap" download><Icon name="download" /> Download .pcap</a>
			<button class="btn btn-quiet btn-sm" type="button" onclick={onclose} aria-label="Close this capture"><Icon name="close" /></button>
		</div>
	</header>

	{#if problem}<p class="problem" role="alert">{problem}</p>{/if}

	<div class="tools">
		<input class="input find" type="search" bind:value={find} placeholder="Find in the table: an address, protocol or word" aria-label="Find in the table" />
		<span class="hint">
			{#if paused}Paused: new packets are still captured.{:else if running}Newest first; the last {SHOW} are shown.{:else}{rows.length.toLocaleString()} of {count.toLocaleString()} loaded.{/if}
		</span>
	</div>

	<div class="table-wrap packets">
		<table class="table">
			<thead>
				<tr>
					<th scope="col">No.</th>
					<th scope="col">Time</th>
					<th scope="col">Source</th>
					<th scope="col">Destination</th>
					<th scope="col">Protocol</th>
					<th scope="col">Length</th>
					<th scope="col">Info</th>
				</tr>
			</thead>
			<tbody>
				{#each shown as p (p.n)}
					<tr>
						<td class="mono num">{p.n}</td>
						<td class="mono">{time(p.t)}</td>
						<td class="mono">{p.src}</td>
						<td class="mono">{p.dst}</td>
						<td><span class="proto" data-proto={p.proto}>{p.proto}</span></td>
						<td class="mono num">{p.len}</td>
						<td class="info">{p.info}</td>
					</tr>
				{:else}
					<tr><td colspan="7" class="empty">{running ? 'Waiting for traffic…' : find ? 'Nothing matches.' : 'No packets.'}</td></tr>
				{/each}
			</tbody>
		</table>
	</div>
	{#if more && !running}
		<button class="btn btn-sm load-more" type="button" onclick={() => loadFile(capture.id, rows[rows.length - 1]?.n ?? 0)}>Load {PAGE} more</button>
	{/if}
</section>

<style>
	.capture {
		display: grid;
		gap: 0.75rem;
		padding: 1rem 1.25rem;
	}
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: start;
		justify-content: space-between;
		gap: 0.75rem 1.25rem;
	}
	h3 {
		font: 700 1.05rem var(--lms-display);
		color: var(--lms-white);
	}
	.cid {
		font: 600 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem 1rem;
		margin-top: 0.35rem;
		font-size: 0.85rem;
		color: var(--lms-gray-2);
	}
	.meta code {
		font: 0.82rem var(--lms-mono);
		color: var(--lms-lime-text);
		overflow-wrap: anywhere;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.problem {
		color: var(--lab-error);
		font-size: 0.875rem;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1rem;
	}
	.find {
		max-width: 26rem;
	}
	.hint {
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
	.packets {
		max-height: 32rem;
		overflow-y: auto;
	}
	.packets thead th {
		position: sticky;
		top: 0;
	}
	.packets .table td {
		padding-block: 0.3rem;
	}
	.num {
		text-align: end;
	}
	.info {
		white-space: normal;
		min-width: 18rem;
		color: var(--lms-gray-1);
	}
	.proto {
		font: 700 0.75rem var(--lms-mono);
		color: var(--lms-gray-1);
	}
	.proto[data-proto='DNS'],
	.proto[data-proto='mDNS'],
	.proto[data-proto='LLMNR'] {
		color: var(--lab-busy);
	}
	.proto[data-proto='HTTP'],
	.proto[data-proto='TLS'] {
		color: var(--lms-lime-text);
	}
	.proto[data-proto='Kerberos'],
	.proto[data-proto='LDAP'],
	.proto[data-proto='SMB'],
	.proto[data-proto='MSRPC'] {
		color: var(--lms-medium);
	}
	.proto[data-proto='ARP'],
	.proto[data-proto='ICMP'],
	.proto[data-proto='ICMPv6'] {
		color: var(--lms-gray-3);
	}
	.empty {
		padding-block: 1.5rem;
		text-align: center;
		color: var(--lms-gray-3);
	}
	.load-more {
		justify-self: start;
	}
</style>
