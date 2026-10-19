<script lang="ts">
	// The machine's screen, keyboard and mouse in the browser. The API relays the VM's console from
	// ESXi (backend/app/console.py) and noVNC shows it. noVNC is loaded only on this page.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import type RFB from '@novnc/novnc';
	import Icon from '$lib/components/Icon.svelte';
	import { api, ApiError } from '$lib/api';
	import { store } from '$lib/store.svelte';

	const id = page.params.id ?? '';
	const m = $derived(store.machine(id));

	let frame: HTMLDivElement;
	let screen: HTMLDivElement;
	let rfb: RFB | undefined;
	let status = $state<'connecting' | 'connected' | 'closed'>('connecting');
	let message = $state('');

	async function open() {
		close();
		status = 'connecting';
		message = '';
		try {
			const { path } = await api<{ path: string }>(`/machines/${encodeURIComponent(id)}/console`, { method: 'POST' });
			const { default: RFBClass } = await import('@novnc/novnc');
			const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;
			const r = new RFBClass(screen, url, { wsProtocols: ['binary'] });
			r.scaleViewport = true;
			r.background = 'transparent';
			r.addEventListener('connect', () => {
				status = 'connected';
				r.focus();
			});
			r.addEventListener('disconnect', (e) => {
				if (rfb !== r) return;
				rfb = undefined;
				status = 'closed';
				message = (e as CustomEvent<{ clean: boolean }>).detail.clean
					? 'The console closed.'
					: 'Lost the connection to the console. The machine may have restarted or switched off.';
			});
			rfb = r;
		} catch (e) {
			status = 'closed';
			message = e instanceof ApiError ? e.message : `Couldn't open the console: ${e}`;
		}
	}

	function close() {
		const r = rfb;
		rfb = undefined;
		r?.disconnect();
	}

	/** Types text as key presses: pasting doesn't reach the machine. Printable ASCII only. */
	function type(text: string) {
		if (!rfb) return;
		for (const ch of text) {
			const code = ch.charCodeAt(0);
			if (code >= 0x20 && code <= 0x7e) rfb.sendKey(code, null);
		}
		rfb.focus();
	}

	function fullScreen() {
		if (document.fullscreenElement) void document.exitFullscreen();
		else void frame.requestFullscreen();
		rfb?.focus();
	}

	onMount(() => {
		void open();
		return close;
	});
</script>

<svelte:head><title>{m?.name ?? 'Machine'} console · Codex Labs</title></svelte:head>

<nav class="breadcrumbs" aria-label="Breadcrumbs">
	<a href="/machines">Machines</a> <span aria-hidden="true">›</span>
	<a href="/machines/{id}">{m?.name ?? id}</a> <span aria-hidden="true">›</span>
	<span aria-current="page">Console</span>
</nav>

<div class="toolbar">
	<p class="state" data-status={status} role="status">
		{#if status === 'connecting'}Connecting…{:else if status === 'connected'}Connected{:else}{message}{/if}
	</p>
	<div class="actions">
		{#if status === 'connected'}
			<button class="btn btn-sm" type="button" onclick={() => rfb?.sendCtrlAltDel()}><Icon name="keyboard" /> Ctrl+Alt+Del</button>
			{#if m?.password}
				<button class="btn btn-sm" type="button" title="Types the machine's password, as if on its keyboard" onclick={() => type(m.password)}>
					<Icon name="key" /> Type password
				</button>
			{/if}
			<button class="btn btn-sm" type="button" onclick={fullScreen}><Icon name="expand" /> Full screen</button>
		{:else if status === 'closed'}
			<button class="btn btn-sm btn-primary" type="button" onclick={open}><Icon name="reboot" /> Reconnect</button>
		{/if}
	</div>
</div>

<div class="frame" bind:this={frame}>
	<div class="screen" bind:this={screen}></div>
</div>
<p class="hint">Click the screen to type into the machine. Keys like Ctrl+Alt+Del and Alt+Tab stay with your own computer: use the buttons.</p>

<style>
	.breadcrumbs {
		margin-bottom: 1.25rem;
		font-size: 0.875rem;
		color: var(--lms-gray-4);
	}
	.breadcrumbs a {
		color: var(--lms-gray-2);
		text-decoration: none;
	}
	.breadcrumbs a:hover {
		color: var(--lms-white);
		text-decoration: underline;
	}
	.breadcrumbs span {
		margin-inline: 0.35rem;
	}
	.breadcrumbs [aria-current='page'] {
		margin: 0;
		color: var(--lms-white);
		font-weight: 600;
	}

	.toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem 1.5rem;
		margin-bottom: 0.75rem;
	}
	.state {
		color: var(--lms-gray-2);
	}
	.state[data-status='connected'] {
		color: var(--lms-white);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.frame {
		height: calc(100dvh - 15rem);
		min-height: 20rem;
		border-radius: var(--lms-radius-xs);
		background: #000;
		overflow: hidden;
	}
	.frame:fullscreen {
		height: 100%;
		border-radius: 0;
	}
	.screen {
		width: 100%;
		height: 100%;
	}
	.hint {
		margin-top: 0.6rem;
		font-size: 0.8125rem;
		color: var(--lms-gray-4);
	}
</style>
