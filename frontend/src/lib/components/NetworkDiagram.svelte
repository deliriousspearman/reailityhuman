<script lang="ts">
	// Your machines on the LAN: the switch at the top, a trunk down the side, and each lab instance's
	// machines (then those deployed on their own) in rows hanging off it. Machines are buttons that
	// select them for a capture. A capture's conversations are drawn over it as links between the
	// machines that talked, thicker for more traffic.
	import { singleMachineStates } from '$lib/format';
	import { size } from '$lib/captures';
	import { templateFor } from '$lib/templates';
	import type { Conversation, Instance, SingleMachine } from '$lib/types';
	import Icon from './Icon.svelte';
	import OsLogo from './OsLogo.svelte';

	let {
		machines,
		instances,
		selected = $bindable([]),
		conversations = [],
	}: { machines: SingleMachine[]; instances: Instance[]; selected?: string[]; conversations?: Conversation[] } = $props();

	// Layout, in the SVG's own units (it scales to the page's width).
	const W = 960;
	const NODE_W = 196;
	const NODE_H = 64;
	const GAP_X = 18;
	const ROW_GAP = 40;
	const TRUNK_X = 30;
	const LEFT = 60;
	const PER_ROW = Math.floor((W - LEFT - 12 + GAP_X) / (NODE_W + GAP_X));

	interface Group {
		id: string;
		title: string;
		href?: string;
		machines: SingleMachine[];
	}
	interface Placed {
		m: SingleMachine;
		x: number;
		y: number;
	}

	const groups = $derived.by(() => {
		const out: Group[] = [];
		for (const m of machines) {
			const id = m.instanceId || '';
			let g = out.find((x) => x.id === id);
			if (!g) {
				const i = instances.find((x) => x.id === id);
				g = id ? { id, title: i ? `${i.title} · ${id}` : id, href: `/instances/${id}`, machines: [] } : { id, title: 'Machines on their own', machines: [] };
				out.push(g);
			}
			g.machines.push(m);
		}
		// Labs first, then the rest.
		return out.sort((a, b) => Number(!a.id) - Number(!b.id));
	});

	const layout = $derived.by(() => {
		const nodes: Placed[] = [];
		const boxes: { g: Group; y: number; h: number }[] = [];
		const buses: { y: number; x2: number; drops: number[] }[] = [];
		let y = 92;
		for (const g of groups) {
			const top = y;
			const rows = Math.ceil(g.machines.length / PER_ROW);
			let rowY = top + 34 + 22;
			for (let r = 0; r < rows; r++) {
				const row = g.machines.slice(r * PER_ROW, (r + 1) * PER_ROW);
				const drops = row.map((_, c) => LEFT + c * (NODE_W + GAP_X) + NODE_W / 2);
				buses.push({ y: rowY - 16, x2: drops[drops.length - 1], drops });
				row.forEach((m, c) => nodes.push({ m, x: LEFT + c * (NODE_W + GAP_X), y: rowY }));
				rowY += NODE_H + ROW_GAP;
			}
			const h = rowY - ROW_GAP + 14 - top;
			boxes.push({ g, y: top, h });
			y = top + h + 22;
		}
		return { nodes, boxes, buses, height: Math.max(y, 140), trunkEnd: buses.length ? buses[buses.length - 1].y : 70 };
	});

	const byIp = $derived(new Map(layout.nodes.filter((n) => n.m.ip).map((n) => [n.m.ip, n])));

	// Conversations between two machines on the diagram; the rest are listed underneath.
	const links = $derived.by(() => {
		const max = Math.max(1, ...conversations.map((c) => c.bytes));
		return conversations.flatMap((c) => {
			const a = byIp.get(c.a);
			const b = byIp.get(c.b);
			if (!a || !b || a === b) return [];
			const [ax, ay, bx, by] = [a.x + NODE_W / 2, a.y + NODE_H / 2, b.x + NODE_W / 2, b.y + NODE_H / 2];
			// Bowed up, so links along a row clear the machines between.
			const lift = Math.min(70, 26 + Math.abs(bx - ax) / 6);
			const d = `M${ax},${a.y} Q${(ax + bx) / 2},${Math.min(a.y, b.y) - lift} ${bx},${b.y}`;
			const width = 1.5 + 4.5 * (Math.log(1 + c.bytes) / Math.log(1 + max));
			return [{ c, d, width, mid: { x: (ax + bx) / 2, y: Math.min(ay, by) } }];
		});
	});
	const elsewhere = $derived(conversations.filter((c) => !(byIp.has(c.a) && byIp.has(c.b))).slice(0, 12));

	function toggle(id: string) {
		selected = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
	}

	function selectGroup(g: Group) {
		const ids = g.machines.map((m) => m.id);
		const all = ids.every((id) => selected.includes(id));
		selected = all ? selected.filter((id) => !ids.includes(id)) : [...new Set([...selected, ...ids])];
	}

	const nameOf = (address: string) => byIp.get(address)?.m.name ?? address;
</script>

<div class="diagram panel">
	<svg viewBox="0 0 {W} {layout.height}" role="group" aria-label="Network diagram of your machines">
		<!-- The switch and the trunk -->
		<g class="switch">
			<rect x="10" y="14" width="250" height="48" />
			<foreignObject x="10" y="14" width="250" height="48">
				<div class="switch-label">
					<Icon name="network" />
					<span><strong>LAN</strong><small>Port group with DHCP</small></span>
				</div>
			</foreignObject>
		</g>
		<line class="wire" x1={TRUNK_X} y1="62" x2={TRUNK_X} y2={layout.trunkEnd} />
		{#each layout.buses as bus, i (i)}
			<line class="wire" x1={TRUNK_X} y1={bus.y} x2={bus.x2} y2={bus.y} />
			{#each bus.drops as x, j (j)}
				<line class="wire" x1={x} y1={bus.y} x2={x} y2={bus.y + 16} />
			{/each}
		{/each}

		<!-- Labs and machines on their own -->
		{#each layout.boxes as box (box.g.id)}
			<rect class="group" x={LEFT - 14} y={box.y} width={W - LEFT + 6} height={box.h} />
			<foreignObject x={LEFT - 6} y={box.y + 4} width={W - LEFT - 12} height="28">
				<div class="group-label">
					{#if box.g.href}<a href={box.g.href}>{box.g.title}</a>{:else}<span>{box.g.title}</span>{/if}
					<button type="button" class="group-select" onclick={() => selectGroup(box.g)}>
						{box.g.machines.every((m) => selected.includes(m.id)) ? 'Clear' : 'Select all'}
					</button>
				</div>
			</foreignObject>
		{/each}

		<!-- Traffic seen by the capture -->
		{#each links as l (l.c.a + l.c.b)}
			<path class="link" d={l.d} stroke-width={l.width}>
				<title>{nameOf(l.c.a)} ↔ {nameOf(l.c.b)}: {l.c.packets} packets, {size(l.c.bytes)}</title>
			</path>
		{/each}

		{#each layout.nodes as n (n.m.id)}
			{@const t = templateFor(n.m.template)}
			{@const state = singleMachineStates[n.m.state]}
			{@const on = selected.includes(n.m.id)}
			<foreignObject x={n.x} y={n.y} width={NODE_W} height={NODE_H}>
				<div class="node" class:on>
					<button
						type="button"
						class="node-main"
						aria-pressed={on}
						title={on ? `Deselect ${n.m.name}` : `Select ${n.m.name} for a capture`}
						onclick={() => toggle(n.m.id)}
					>
						<OsLogo id={t.id} name={t.name} size="sm" />
						<span class="node-text">
							<span class="node-name">{n.m.name}</span>
							<span class="node-ip">{n.m.ip || 'no address yet'}</span>
						</span>
						<span class="dot" data-tone={state.tone} title={state.label}></span>
						<span class="visually-hidden">{state.label}</span>
					</button>
					<a class="node-open" href="/machines/{n.m.id}" title="Open {n.m.name}" aria-label="Open {n.m.name}"><Icon name="external" /></a>
				</div>
			</foreignObject>
		{/each}
	</svg>
</div>

{#if elsewhere.length}
	<div class="elsewhere">
		<span class="elsewhere-title">Also seen</span>
		{#each elsewhere as c (c.a + c.b)}
			<span class="tag" title="{c.packets} packets, {size(c.bytes)}">{nameOf(c.a)} ↔ {nameOf(c.b)}</span>
		{/each}
	</div>
{/if}

<style>
	.diagram {
		padding: 0.5rem;
		overflow-x: auto;
	}
	svg {
		display: block;
		width: 100%;
		min-width: 40rem;
		height: auto;
		font-family: var(--lms-font);
	}
	.switch rect {
		fill: var(--lms-panel-2);
		stroke: var(--lms-lime);
		stroke-width: 2;
	}
	.switch-label {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		height: 100%;
		padding-inline: 0.8rem;
		color: var(--lms-lime-text);
	}
	.switch-label span {
		display: grid;
		line-height: 1.15;
	}
	.switch-label strong {
		font: 700 0.95rem var(--lms-display);
		color: var(--lms-white);
	}
	.switch-label small {
		font: 500 0.7rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.wire {
		stroke: var(--lab-wire);
		stroke-width: 2;
	}
	.group {
		fill: none;
		stroke: var(--lms-gray-5);
		stroke-width: 1.5;
		stroke-dasharray: 5 4;
	}
	.group-label {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		font: 600 0.75rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.group-label a {
		color: var(--lms-gray-2);
	}
	.group-select {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		color: var(--lms-lime-text);
		cursor: pointer;
	}
	.group-select:hover {
		text-decoration: underline;
	}
	.link {
		fill: none;
		stroke: var(--lms-lime);
		stroke-linecap: round;
		opacity: 0.75;
	}
	.link:hover {
		opacity: 1;
	}
	.node {
		position: relative;
		height: 100%;
		border: 2px solid var(--lms-gray-5);
		border-radius: var(--lms-radius-md);
		background: var(--lms-panel-2);
	}
	.node:hover {
		border-color: var(--lms-gray-4);
	}
	.node.on {
		border-color: var(--lms-lime);
		box-shadow: inset 0 0 0 1px var(--lms-lime);
	}
	.node-main {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		width: 100%;
		height: 100%;
		padding: 0 1.9rem 0 0.6rem;
		border: 0;
		background: none;
		color: inherit;
		text-align: start;
		cursor: pointer;
	}
	.node-text {
		display: grid;
		min-width: 0;
		line-height: 1.2;
	}
	.node-name {
		overflow: hidden;
		font: 700 0.85rem var(--lms-mono);
		color: var(--lms-white);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.node-ip {
		font: 500 0.72rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	.dot {
		position: absolute;
		top: 0.5rem;
		right: 0.55rem;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--lab-down);
	}
	.dot[data-tone='up'] {
		background: var(--lab-up);
	}
	.dot[data-tone='busy'] {
		background: var(--lab-busy);
	}
	.dot[data-tone='warn'] {
		background: var(--lab-warn);
	}
	.dot[data-tone='error'] {
		background: var(--lab-error);
	}
	.node-open {
		position: absolute;
		right: 0.35rem;
		bottom: 0.3rem;
		display: grid;
		padding: 0.15rem;
		color: var(--lms-gray-3);
	}
	.node-open:hover {
		color: var(--lms-lime-text);
	}
	.node-open :global(svg) {
		width: 0.85rem;
		height: 0.85rem;
	}
	.elsewhere {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		margin-top: 0.6rem;
		font-size: 0.85rem;
	}
	.elsewhere-title {
		margin-right: 0.25rem;
		color: var(--lms-gray-3);
	}
</style>
