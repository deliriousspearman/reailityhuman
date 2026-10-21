<script lang="ts">
	// A template's logo in a small tile (lib/os-logos.ts), or its name's first letter for one without
	// a logo. Decorative next to the name it sits by, so hidden from screen readers unless labelled.
	import { osLogos } from '$lib/os-logos';

	let { id, name = '', size = 'md', label = false }: { id: string; name?: string; size?: 'sm' | 'md' | 'lg'; label?: boolean } =
		$props();

	const logo = $derived(osLogos[id]);
	// A near-black or near-white mark would vanish on one of the themes: those take the text colour.
	const plain = $derived.by(() => {
		const hex = logo?.color.replace('#', '') ?? '';
		if (hex.length !== 6) return true;
		const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
		const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
		return lum < 0.18 || lum > 0.85;
	});
	const letters = $derived(logo && 'letters' in logo ? logo.letters : (name || id).slice(0, 1).toUpperCase());
</script>

<span
	class="logo {size}"
	class:plain
	style:--brand={logo?.color}
	role={label ? 'img' : undefined}
	aria-label={label ? name || logo?.title : undefined}
	aria-hidden={label ? undefined : 'true'}
	title={label ? undefined : name || logo?.title}
>
	{#if logo && 'path' in logo}
		<svg viewBox="0 0 24 24" focusable="false"><path d={logo.path} /></svg>
	{:else}
		<span class="letters" class:long={letters.length > 2}>{letters}</span>
	{/if}
</span>

<style>
	.logo {
		--brand: var(--lms-gray-3);
		display: inline-grid;
		place-items: center;
		flex: none;
		border-radius: var(--lms-radius-md);
		background: color-mix(in srgb, var(--brand) 14%, transparent);
		border: var(--lms-border-width) solid color-mix(in srgb, var(--brand) 35%, transparent);
		color: var(--brand);
	}
	.logo.plain {
		color: var(--lms-white);
		background: color-mix(in srgb, var(--lms-white) 8%, transparent);
		border-color: color-mix(in srgb, var(--lms-white) 20%, transparent);
	}
	.sm {
		width: 1.5rem;
		height: 1.5rem;
	}
	.md {
		width: 2.25rem;
		height: 2.25rem;
	}
	.lg {
		width: 3rem;
		height: 3rem;
	}
	svg {
		width: 62%;
		height: 62%;
		fill: currentColor;
	}
	.letters {
		font: 700 0.8em var(--lms-display);
		line-height: 1;
		letter-spacing: -0.02em;
	}
	.sm .letters {
		font-size: 0.6rem;
	}
	.md .letters {
		font-size: 0.8rem;
	}
	.lg .letters {
		font-size: 1rem;
	}
	.letters.long {
		font-size: 0.85em;
	}
	.sm .letters.long {
		font-size: 0.5rem;
	}
</style>
