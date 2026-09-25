<script lang="ts">
	// A state shown as a dot and a label (never colour alone). Busy states pulse.
	import type { Tone } from '$lib/format';

	let { tone, label, size = 'md' }: { tone: Tone; label: string; size?: 'sm' | 'md' } = $props();
</script>

<span class="status" data-tone={tone} data-size={size}><span class="dot" aria-hidden="true"></span>{label}</span>

<style>
	.status {
		--tone: var(--lab-up);
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		font: 600 0.8rem var(--lms-mono);
		color: var(--tone);
		white-space: nowrap;
	}
	.status[data-size='sm'] {
		font-size: 0.72rem;
		gap: 0.35rem;
	}
	.status[data-tone='busy'] {
		--tone: var(--lab-busy);
	}
	.status[data-tone='warn'] {
		--tone: var(--lab-warn);
	}
	.status[data-tone='down'] {
		--tone: var(--lab-down);
	}
	.status[data-tone='error'] {
		--tone: var(--lab-error);
	}
	.dot {
		flex-shrink: 0;
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 50%;
		background: var(--tone);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--tone) 22%, transparent);
	}
	.status[data-tone='down'] .dot {
		background: transparent;
		box-shadow: inset 0 0 0 2px var(--tone);
	}
	@media (prefers-reduced-motion: no-preference) {
		.status[data-tone='busy'] .dot {
			animation: pulse 1.1s ease-in-out infinite;
		}
	}
	@keyframes pulse {
		50% {
			box-shadow: 0 0 0 5px color-mix(in srgb, var(--tone) 8%, transparent);
			opacity: 0.55;
		}
	}
</style>
