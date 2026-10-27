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
	/** A short note after a clipboard action (e.g. "Pasted", or why it couldn't). */
	let clip = $state('');
	let clipTimer: ReturnType<typeof setTimeout> | undefined;
	/** The controls overlay hides itself when the mouse is still, so it's out of the way in full screen. */
	let controlsShown = $state(true);
	let hideTimer: ReturnType<typeof setTimeout> | undefined;

	function flashClip(text: string) {
		clip = text;
		clearTimeout(clipTimer);
		clipTimer = setTimeout(() => (clip = ''), 2500);
	}

	function wakeControls() {
		controlsShown = true;
		clearTimeout(hideTimer);
		hideTimer = setTimeout(() => (controlsShown = false), 2800);
	}

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
				wakeControls();
			});
			// Copy out (machine → your computer): only if the machine's console sends its clipboard,
			// which plain VMware consoles often don't. Best-effort, so it's silent when unsupported.
			r.addEventListener('clipboard', (e) => {
				const text = (e as CustomEvent<{ text: string }>).detail.text;
				if (text) void navigator.clipboard?.writeText(text).then(() => flashClip('Copied from the machine')).catch(() => {});
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

	const SHIFT = 0xffe1;
	const ENTER = 0xff0d;
	const TAB = 0xff09;
	// Characters typed with Shift on a US keyboard. ESXi presses the key a character is on, without
	// Shift, so these need it held.
	const SHIFTED = /[A-Z~!@#$%^&*()_+{}|:"<>?]/;

	/** Sends text to the machine as key presses (the console takes keystrokes, not a paste): printable
	 * ASCII, with new lines as Enter and tabs as Tab. Used by Type password and Paste. */
	function sendText(text: string) {
		if (!rfb) return;
		for (const ch of text) {
			if (ch === '\n' || ch === '\r') {
				rfb.sendKey(ENTER, 'Enter');
				continue;
			}
			if (ch === '\t') {
				rfb.sendKey(TAB, 'Tab');
				continue;
			}
			const code = ch.charCodeAt(0);
			if (code < 0x20 || code > 0x7e) continue;
			const shift = SHIFTED.test(ch);
			if (shift) rfb.sendKey(SHIFT, 'ShiftLeft', true);
			rfb.sendKey(code, null);
			if (shift) rfb.sendKey(SHIFT, 'ShiftLeft', false);
		}
		rfb.focus();
	}

	/** Pastes your computer's clipboard into the machine by typing it (works even where the console
	 * has no clipboard of its own). US keyboard layout; non-ASCII characters are skipped. */
	async function paste() {
		if (!rfb) return;
		let text = '';
		try {
			text = await navigator.clipboard.readText();
		} catch {
			flashClip('Allow clipboard access in your browser to paste');
			return;
		}
		if (!text) {
			flashClip('Your clipboard is empty');
			return;
		}
		sendText(text);
		flashClip('Pasted into the machine');
	}

	function fullScreen() {
		if (document.fullscreenElement) void document.exitFullscreen();
		else void frame.requestFullscreen();
		rfb?.focus();
		wakeControls();
	}

	onMount(() => {
		void open();
		wakeControls();
		return () => {
			close();
			clearTimeout(hideTimer);
			clearTimeout(clipTimer);
		};
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
	{#if status === 'closed'}
		<button class="btn btn-sm btn-primary" type="button" onclick={open}><Icon name="reboot" /> Reconnect</button>
	{/if}
</div>

<!-- The controls sit inside the frame, so they stay on screen in full screen too (the frame is what
     goes full screen). They fade out when the mouse is still. -->
<div class="frame" bind:this={frame} onmousemove={wakeControls} role="presentation">
	<div class="screen" bind:this={screen}></div>
	{#if status === 'connected'}
		<div class="controls" class:shown={controlsShown}>
			<button class="btn btn-sm" type="button" onclick={() => rfb?.sendCtrlAltDel()}><Icon name="keyboard" /> Ctrl+Alt+Del</button>
			<button class="btn btn-sm" type="button" title="Pastes your clipboard by typing it into the machine" onclick={paste}>
				<Icon name="copy" /> Paste
			</button>
			{#if m?.password}
				<button class="btn btn-sm" type="button" title="Types the machine's password, as if on its keyboard" onclick={() => sendText(m.password)}>
					<Icon name="key" /> Type password
				</button>
			{/if}
			<button class="btn btn-sm" type="button" onclick={fullScreen}><Icon name="expand" /> Full screen</button>
			{#if clip}<span class="clip" role="status">{clip}</span>{/if}
		</div>
	{/if}
</div>
<p class="hint">
	Click the screen to type into the machine. Keys like Ctrl+Alt+Del and Alt+Tab stay with your own computer: use the buttons. Paste
	copies your clipboard in by typing it; copying out works only if the machine's console shares its clipboard.
</p>

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

	.frame {
		position: relative;
		height: calc(100dvh - 12rem);
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
	/* Floating over the screen, so they're there in full screen too; centred at the top. */
	.controls {
		position: absolute;
		top: 0.6rem;
		left: 50%;
		transform: translateX(-50%);
		z-index: 2;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		max-width: calc(100% - 1rem);
		padding: 0.4rem;
		border-radius: var(--lms-radius-md);
		background: color-mix(in srgb, var(--lms-panel) 88%, transparent);
		box-shadow: 0 0.5rem 1.5rem -0.5rem rgb(0 0 0 / 0.7);
		opacity: 0;
		transition: opacity 0.2s ease;
		pointer-events: none;
	}
	.controls.shown {
		opacity: 1;
		pointer-events: auto;
	}
	.controls .clip {
		padding-inline: 0.3rem;
		font-size: 0.8rem;
		color: var(--lms-lime-text);
	}
	.hint {
		margin-top: 0.6rem;
		font-size: 0.8125rem;
		color: var(--lms-gray-4);
	}
</style>
