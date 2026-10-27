<script lang="ts">
	// The machine's screen, keyboard and mouse in the browser. The API relays the VM's console from
	// ESXi (backend/app/console.py) and noVNC shows it. noVNC (its core RFB, not its own UI) is loaded
	// only on this page; the controls here are our own, in a sidebar that stays on screen in full screen.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import type RFB from '@novnc/novnc';
	import Icon from '$lib/components/Icon.svelte';
	import { api, ApiError } from '$lib/api';
	import { store } from '$lib/store.svelte';

	const id = page.params.id ?? '';
	const m = $derived(store.machine(id));
	// In full, for its password (Type password): the lists leave it out.
	$effect(() => {
		store.watch(id);
		return () => store.watch(null);
	});

	let frame: HTMLDivElement;
	let screen: HTMLDivElement;
	let rfb: RFB | undefined;
	let status = $state<'connecting' | 'connected' | 'closed'>('connecting');
	let message = $state('');
	/** Whether the screen is scaled to fit, or shown at its own size (and scrolled). */
	let fit = $state(true);
	/** The sidebar: open or just its tab; it fades out when the mouse is still, so it's unobtrusive
	 * (especially in full screen) and reappears on movement. */
	let sidebarOpen = $state(true);
	let controlsShown = $state(true);
	/** A short note after an action (e.g. "Pasted", or why it couldn't). */
	let note = $state('');
	/** Which corner the control dock sits in; remembered in this browser. */
	type Corner = 'tr' | 'tl' | 'br' | 'bl';
	let pos = $state<Corner>('tr');
	const POS_KEY = 'lab-deploy:console-dock';

	function setPos(p: Corner) {
		pos = p;
		try {
			localStorage.setItem(POS_KEY, p);
		} catch {
			// a browser without storage (private window): the choice just isn't remembered
		}
		wakeControls();
	}

	// Auto-reconnect: a dropped console is retried a few times before giving up, so a brief blip (or a
	// machine still settling) doesn't need a manual reconnect.
	const MAX_RETRIES = 4;
	let retries = 0;
	let hideTimer: ReturnType<typeof setTimeout> | undefined;
	let noteTimer: ReturnType<typeof setTimeout> | undefined;
	let retryTimer: ReturnType<typeof setTimeout> | undefined;

	function flash(text: string) {
		note = text;
		clearTimeout(noteTimer);
		noteTimer = setTimeout(() => (note = ''), 2500);
	}

	function wakeControls() {
		controlsShown = true;
		clearTimeout(hideTimer);
		hideTimer = setTimeout(() => (controlsShown = false), 3000);
	}

	async function open() {
		clearTimeout(retryTimer);
		close();
		status = 'connecting';
		message = '';
		try {
			const { path } = await api<{ path: string }>(`/machines/${encodeURIComponent(id)}/console`, { method: 'POST' });
			const { default: RFBClass } = await import('@novnc/novnc');
			const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;
			const r = new RFBClass(screen, url, { wsProtocols: ['binary'] });
			r.scaleViewport = fit;
			r.clipViewport = !fit;
			r.background = 'transparent';
			r.addEventListener('connect', () => {
				status = 'connected';
				retries = 0;
				r.focus();
				wakeControls();
			});
			// Copy out (machine → your computer): only if the machine's console sends its clipboard,
			// which plain VMware consoles don't. Best-effort, so it's silent when unsupported.
			r.addEventListener('clipboard', (e) => {
				const text = (e as CustomEvent<{ text: string }>).detail.text;
				if (text) void navigator.clipboard?.writeText(text).then(() => flash('Copied from the machine')).catch(() => {});
			});
			r.addEventListener('disconnect', (e) => {
				if (rfb !== r) return; // we replaced it on purpose (close/open)
				rfb = undefined;
				const clean = (e as CustomEvent<{ clean: boolean }>).detail.clean;
				if (!clean && retries < MAX_RETRIES) {
					retries += 1;
					status = 'connecting';
					message = `Reconnecting… (${retries}/${MAX_RETRIES})`;
					retryTimer = setTimeout(open, 1500);
				} else {
					status = 'closed';
					message = clean
						? 'The console closed.'
						: 'Lost the connection to the console. The machine may be off or restarting.';
				}
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

	function reconnect() {
		retries = 0;
		void open();
	}

	// Keysyms (X11) for keys and chords the browser keeps to itself.
	const K = {
		shift: 0xffe1,
		ctrl: 0xffe3,
		alt: 0xffe9,
		enter: 0xff0d,
		tab: 0xff09,
		esc: 0xff1b,
		f: (n: number) => 0xffbd + n, // F1 = 0xffbe
	};
	// Characters typed with Shift on a US keyboard. ESXi presses the key a character is on, without
	// Shift, so these need it held.
	const SHIFTED = /[A-Z~!@#$%^&*()_+{}|:"<>?]/;

	/** Sends text to the machine as key presses (the console takes keystrokes, not a paste): printable
	 * ASCII, with new lines as Enter and tabs as Tab. Used by Type password and Paste. */
	function sendText(text: string) {
		if (!rfb) return;
		for (const ch of text) {
			if (ch === '\n' || ch === '\r') {
				rfb.sendKey(K.enter, 'Enter');
			} else if (ch === '\t') {
				rfb.sendKey(K.tab, 'Tab');
			} else {
				const code = ch.charCodeAt(0);
				if (code < 0x20 || code > 0x7e) continue;
				const shift = SHIFTED.test(ch);
				if (shift) rfb.sendKey(K.shift, 'ShiftLeft', true);
				rfb.sendKey(code, null);
				if (shift) rfb.sendKey(K.shift, 'ShiftLeft', false);
			}
		}
		rfb.focus();
	}

	/** Holds the chord's keys down in order, then releases them in reverse — for combinations the
	 * browser traps (Alt+Tab) or that go to the host OS, and the TTY switches on Linux. */
	function chord(...keys: number[]) {
		if (!rfb) return;
		for (const k of keys) rfb.sendKey(k, null, true);
		for (let i = keys.length - 1; i >= 0; i--) rfb.sendKey(keys[i], null, false);
		rfb.focus();
	}

	/** Pastes your computer's clipboard into the machine by typing it (the only way that works over
	 * these consoles, which have no clipboard of their own). US keyboard layout; non-ASCII skipped. */
	async function paste() {
		if (!rfb) return;
		let text = '';
		try {
			text = await navigator.clipboard.readText();
		} catch {
			flash('Allow clipboard access in your browser to paste');
			return;
		}
		if (!text) {
			flash('Your clipboard is empty');
			return;
		}
		sendText(text);
		flash('Pasted into the machine');
	}

	function screenshot() {
		const canvas = screen.querySelector('canvas');
		if (!canvas) return;
		try {
			const a = document.createElement('a');
			a.href = canvas.toDataURL('image/png');
			a.download = `${m?.name ?? 'console'}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`;
			a.click();
			flash('Screenshot saved');
		} catch {
			flash("Couldn't take a screenshot");
		}
	}

	function setFit(value: boolean) {
		fit = value;
		if (rfb) {
			rfb.scaleViewport = value;
			rfb.clipViewport = !value;
			rfb.focus();
		}
	}

	/** Moves the console to a new browser tab (e.g. to keep it beside the machine's page), and closes
	 * it here so the two don't both drive the machine; Reconnect takes it back. */
	function openInNewTab() {
		const tab = window.open(location.href, '_blank');
		if (!tab) {
			flash('Your browser blocked the new tab: allow pop-ups for the panel');
			return;
		}
		tab.opener = null;
		if (document.fullscreenElement) void document.exitFullscreen();
		clearTimeout(retryTimer);
		close();
		status = 'closed';
		message = 'The console is open in another tab.';
	}

	function fullScreen() {
		if (document.fullscreenElement) void document.exitFullscreen();
		else void frame.requestFullscreen();
		rfb?.focus();
		wakeControls();
	}

	onMount(() => {
		try {
			const saved = localStorage.getItem(POS_KEY);
			if (saved === 'tr' || saved === 'tl' || saved === 'br' || saved === 'bl') pos = saved;
		} catch {
			// no stored preference
		}
		void open();
		wakeControls();
		return () => {
			close();
			clearTimeout(hideTimer);
			clearTimeout(noteTimer);
			clearTimeout(retryTimer);
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
		{#if status === 'connecting'}{message || 'Connecting…'}{:else if status === 'connected'}Connected{:else}{message}{/if}
	</p>
	{#if status === 'closed'}
		<button class="btn btn-sm btn-primary" type="button" onclick={reconnect}><Icon name="reboot" /> Reconnect</button>
	{/if}
</div>

<!-- The sidebar sits inside the frame (what goes full screen), so its controls stay reachable there.
     It fades out when the mouse is still and returns on movement. -->
<div class="frame" bind:this={frame} onmousemove={wakeControls} role="presentation">
	<div class="screen" bind:this={screen} class:actual={!fit}></div>

	{#if note}<div class="note" class:top={pos === 'br' || pos === 'bl'} role="status">{note}</div>{/if}
	{#if status === 'connected'}
		<div class="dock" data-pos={pos} class:shown={controlsShown}>
			<button
				class="tab"
				type="button"
				aria-label={sidebarOpen ? 'Hide controls' : 'Show controls'}
				title={sidebarOpen ? 'Hide controls' : 'Show controls'}
				onclick={() => (sidebarOpen = !sidebarOpen)}
			>
				<Icon name={sidebarOpen ? 'chevron' : 'menu'} />
			</button>
			{#if sidebarOpen}
				<div class="panel">
					<button class="item" type="button" onclick={() => rfb?.sendCtrlAltDel()}><Icon name="keyboard" /> Ctrl+Alt+Del</button>
					<button class="item" type="button" title="Pastes your clipboard by typing it in" onclick={paste}><Icon name="copy" /> Paste</button>
					{#if m?.password}
						<button class="item" type="button" title="Types the machine's password" onclick={() => sendText(m.password ?? '')}><Icon name="key" /> Type password</button>
					{/if}

					<div class="group-label">Send keys</div>
					<div class="keys">
						<button type="button" onclick={() => chord(K.esc)}>Esc</button>
						<button type="button" onclick={() => chord(K.tab)}>Tab</button>
						<button type="button" onclick={() => chord(K.alt, K.tab)}>Alt+Tab</button>
					</div>
					<div class="group-label" title="Switch a Linux machine to a text login (handy if a graphical console is blank)">Ctrl+Alt+F…</div>
					<div class="keys">
						{#each [2, 3, 4, 5, 6] as n (n)}
							<button type="button" title={`Ctrl+Alt+F${n}`} onclick={() => chord(K.ctrl, K.alt, K.f(n))}>F{n}</button>
						{/each}
					</div>

					<div class="group-label">View</div>
					<div class="keys">
						<button type="button" class:on={fit} onclick={() => setFit(true)}>Fit</button>
						<button type="button" class:on={!fit} onclick={() => setFit(false)}>1:1</button>
					</div>
					<button class="item" type="button" onclick={screenshot}><Icon name="download" /> Screenshot</button>
					<button class="item" type="button" onclick={fullScreen}><Icon name="expand" /> Full screen</button>
					<button class="item" type="button" title="Moves the console to a new browser tab" onclick={openInNewTab}><Icon name="external" /> Open in new tab</button>

					<div class="group-label">Position</div>
					<div class="corners">
						<button type="button" class:on={pos === 'tl'} title="Top left" aria-label="Move controls to the top left" onclick={() => setPos('tl')}>↖</button>
						<button type="button" class:on={pos === 'tr'} title="Top right" aria-label="Move controls to the top right" onclick={() => setPos('tr')}>↗</button>
						<button type="button" class:on={pos === 'bl'} title="Bottom left" aria-label="Move controls to the bottom left" onclick={() => setPos('bl')}>↙</button>
						<button type="button" class:on={pos === 'br'} title="Bottom right" aria-label="Move controls to the bottom right" onclick={() => setPos('br')}>↘</button>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
<p class="hint">
	Click the screen to type into it. Combinations like Ctrl+Alt+Del and Alt+Tab stay with your own computer — use the Send keys
	buttons. Paste types your clipboard in (copying out isn't supported by these consoles). A dropped console reconnects itself.
	Open in new tab moves the console to a tab of its own; Reconnect here takes it back.
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
	/* At its own size, let it scroll rather than scale. */
	.screen.actual {
		overflow: auto;
	}

	/* The control dock: a tab plus a panel, in a chosen corner, over the screen. Fades when the mouse
	   is still. The note is separate (below), so showing it never shifts these controls. */
	.dock {
		position: absolute;
		z-index: 2;
		display: flex;
		align-items: flex-start;
		gap: 0.4rem;
		opacity: 0;
		transition: opacity 0.2s ease;
		pointer-events: none;
	}
	.dock[data-pos='tr'] {
		top: 0.6rem;
		right: 0.6rem;
	}
	.dock[data-pos='tl'] {
		top: 0.6rem;
		left: 0.6rem;
	}
	.dock[data-pos='br'] {
		bottom: 0.6rem;
		right: 0.6rem;
		align-items: flex-end;
	}
	.dock[data-pos='bl'] {
		bottom: 0.6rem;
		left: 0.6rem;
		align-items: flex-end;
	}
	/* The panel opens into the screen: left of the tab on the right, right of the tab on the left. */
	.dock[data-pos='tr'] .panel,
	.dock[data-pos='br'] .panel {
		order: -1;
	}
	.dock[data-pos='tl'] .panel,
	.dock[data-pos='bl'] .panel {
		order: 1;
	}
	.dock.shown {
		opacity: 1;
		pointer-events: auto;
	}
	.tab {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		flex-shrink: 0;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-sm);
		background: color-mix(in srgb, var(--lms-panel) 90%, transparent);
		color: var(--lms-gray-1);
		cursor: pointer;
	}
	.tab:hover {
		border-color: var(--lms-gray-3);
	}
	.panel {
		display: grid;
		gap: 0.3rem;
		width: 11.5rem;
		padding: 0.5rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-md);
		background: color-mix(in srgb, var(--lms-panel) 92%, transparent);
		box-shadow: 0 0.5rem 1.5rem -0.5rem rgb(0 0 0 / 0.7);
	}
	.panel .item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.4rem 0.55rem;
		border: 0;
		border-radius: var(--lms-radius-xs);
		background: var(--lms-panel-2);
		color: var(--lms-gray-1);
		font: 600 0.82rem var(--lms-font);
		text-align: start;
		cursor: pointer;
	}
	.panel .item:hover {
		background: var(--lms-gray-5);
		color: var(--lms-white);
	}
	.panel .item :global(svg) {
		width: 0.9rem;
		height: 0.9rem;
		flex-shrink: 0;
	}
	.group-label {
		margin-top: 0.2rem;
		font: 600 0.68rem var(--lms-font);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--lms-gray-3);
	}
	.keys {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem;
	}
	.keys button {
		flex: 1 1 auto;
		min-width: 2rem;
		padding: 0.3rem 0.4rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-xs);
		background: var(--lms-panel-2);
		color: var(--lms-gray-1);
		font: 600 0.75rem var(--lms-mono);
		cursor: pointer;
	}
	.keys button:hover {
		border-color: var(--lms-gray-3);
		color: var(--lms-white);
	}
	.keys button.on {
		border-color: var(--lms-lime);
		color: var(--lms-lime-text);
		background: var(--lms-accent-low);
	}
	.corners {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.25rem;
	}
	.corners button {
		padding: 0.25rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-xs);
		background: var(--lms-panel-2);
		color: var(--lms-gray-1);
		font-size: 0.9rem;
		line-height: 1;
		cursor: pointer;
	}
	.corners button:hover {
		border-color: var(--lms-gray-3);
		color: var(--lms-white);
	}
	.corners button.on {
		border-color: var(--lms-lime);
		color: var(--lms-lime-text);
		background: var(--lms-accent-low);
	}
	/* The action note: fixed at the bottom centre of the screen, independent of the dock, so it never
	   moves the controls. Shows even when the dock has faded. */
	.note {
		position: absolute;
		bottom: 0.8rem;
		left: 50%;
		transform: translateX(-50%);
		z-index: 3;
		padding: 0.35rem 0.7rem;
		border-radius: var(--lms-radius-sm);
		background: color-mix(in srgb, var(--lms-panel) 92%, transparent);
		box-shadow: 0 0.3rem 1rem -0.4rem rgb(0 0 0 / 0.6);
		font-size: 0.8rem;
		color: var(--lms-lime-text);
		white-space: nowrap;
		pointer-events: none;
	}
	/* When the dock is along the bottom, show the note at the top instead, so they don't overlap. */
	.note.top {
		bottom: auto;
		top: 0.8rem;
	}
	.hint {
		margin-top: 0.6rem;
		font-size: 0.8125rem;
		color: var(--lms-gray-4);
	}
</style>
