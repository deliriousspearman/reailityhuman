<script lang="ts">
	// A capacity meter: how much of one resource is in use. One series, so no legend; the numbers are
	// printed beside the bar and the fullness is named in words, not colour alone.
	let { label, used, total, unit, note }: { label: string; used: number; total: number; unit: string; note?: string } =
		$props();

	const ratio = $derived(Math.min(1, used / total));
	const level = $derived(ratio >= 0.9 ? { tone: 'error', text: 'Full' } : ratio >= 0.75 ? { tone: 'warn', text: 'Getting full' } : { tone: 'up', text: 'Room free' });
</script>

<div class="meter" data-tone={level.tone}>
	<div class="meter-head">
		<span class="meter-label">{label}</span>
		<span class="meter-level">{level.text}</span>
	</div>
	<p class="meter-value">
		<strong>{used.toLocaleString()}</strong> of {total.toLocaleString()} {unit}
		<span>{Math.round(ratio * 100)}%</span>
	</p>
	<div
		class="bar"
		role="meter"
		aria-label={label}
		aria-valuemin={0}
		aria-valuemax={total}
		aria-valuenow={used}
		aria-valuetext="{used} of {total} {unit}"
		title="{used} of {total} {unit} in use"
	>
		<span style:width="{ratio * 100}%"></span>
	</div>
	{#if note}<p class="meter-note">{note}</p>{/if}
</div>

<style>
	.meter {
		--tone: var(--lab-up);
		display: grid;
		gap: 0.5rem;
		padding: 1rem;
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lab-radius-sm);
		background: var(--lms-panel);
	}
	.meter[data-tone='warn'] {
		--tone: var(--lab-warn);
	}
	.meter[data-tone='error'] {
		--tone: var(--lab-error);
	}
	.meter-head {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
	}
	.meter-label {
		font: 700 1rem var(--lms-display);
		color: var(--lms-white);
	}
	.meter-level {
		font: 600 0.75rem var(--lms-mono);
		color: var(--lms-gray-2);
	}
	.meter-level::before {
		content: '';
		display: inline-block;
		width: 0.5rem;
		height: 0.5rem;
		margin-inline-end: 0.4rem;
		border-radius: 50%;
		background: var(--tone);
	}
	.meter-value {
		display: flex;
		align-items: baseline;
		gap: 0.35rem;
		font-size: 0.875rem;
	}
	.meter-value strong {
		font: 700 1.35rem var(--lms-display);
		color: var(--lms-white);
	}
	.meter-value span {
		margin-inline-start: auto;
		font: 600 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
	/* Track and fill: thin, rounded ends. */
	.bar {
		height: 0.5rem;
		border-radius: 999px;
		background: var(--lms-gray-5);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: var(--tone);
		transition: width 0.4s ease;
	}
	.meter-note {
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
</style>
