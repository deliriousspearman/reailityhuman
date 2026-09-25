<script lang="ts">
	// The instance's activity (deploys, resets, health warnings) in a terminal window, newest last.
	// Follows new lines unless the reader has scrolled up.
	import { tick } from 'svelte';
	import { logTime } from '$lib/format';
	import type { LogLine } from '$lib/types';

	let { lines, title }: { lines: LogLine[]; title: string } = $props();

	let body: HTMLElement | undefined = $state();

	$effect(() => {
		void lines.length;
		if (!body) return;
		const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
		if (atBottom || lines.length <= 1) tick().then(() => body && (body.scrollTop = body.scrollHeight));
	});
</script>

<div class="terminal log">
	<div class="terminal-bar"><span>{title}</span></div>
	<!-- Focusable so keyboard users can scroll the log. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div class="terminal-body" bind:this={body} role="log" aria-live="polite" tabindex="0">
		{#each lines as line, i (i)}
			<p data-tone={line.tone}><time>{logTime(line.at)}</time> {line.text}</p>
		{:else}
			<p data-tone="muted">No activity yet.</p>
		{/each}
	</div>
</div>

<style>
	.terminal-body {
		max-height: 18rem;
		overflow-y: auto;
		white-space: normal;
	}
	p {
		margin: 0;
		display: grid;
		grid-template-columns: 5rem 1fr;
	}
	time {
		color: #52627f;
	}
	[data-tone='ok'] {
		color: #c5f467;
	}
	[data-tone='warn'] {
		color: #ffaf00;
	}
	[data-tone='error'] {
		color: #ff3e3e;
	}
	[data-tone='muted'] {
		color: #8494b5;
	}
</style>
