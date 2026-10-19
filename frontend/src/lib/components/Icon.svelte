<script lang="ts" module>
	// Inline line icons (24px grid, 2px stroke), so nothing loads from a CDN. The LMS uses a few
	// inline SVGs the same way.
	export const paths = {
		reset: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5',
		reboot: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
		power: 'M12 3v9M6.3 7.2a8 8 0 1 0 11.4 0',
		play: 'M7 4.5v15l12-7.5z',
		stop: 'M6 6h12v12H6z',
		download: 'M12 4v11m-5-5 5 5 5-5M5 20h14',
		copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
		trash: 'M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3',
		clock: 'M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18',
		plus: 'M12 5v14M5 12h14',
		menu: 'M4 7h16M4 12h16M4 17h16',
		close: 'M6 6l12 12M18 6 6 18',
		labs: 'M4 5h16v5H4zM4 14h16v5H4zM8 7.5h.01M8 16.5h.01',
		instances: 'M12 3 3 8l9 5 9-5zM3 13l9 5 9-5',
		admin: 'M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z',
		console: 'M4 5h16v14H4zM8 10l3 2-3 2M13 15h3',
		rebuild: 'M4 20h16M6 16V9l6-5 6 5v7M10 16v-4h4v4',
		alert: 'M12 9v4M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0',
		external: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
		user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21a8 8 0 0 1 16 0',
		eye: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6',
		key: 'M15 9a4 4 0 1 1-8 0 4 4 0 0 1 8 0M13.5 12l7 7M17 16l2-2M19 18l2-2',
		sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
		moon: 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5',
		auto: 'M12 3v18M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18',
		chevron: 'm6 9 6 6 6-6',
		expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
		keyboard: 'M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M8 14h8',
	} as const;

	export type IconName = keyof typeof paths;
</script>

<script lang="ts">
	let { name, label }: { name: IconName; label?: string } = $props();
</script>

<svg
	viewBox="0 0 24 24"
	fill={name === 'play' ? 'currentColor' : 'none'}
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden={label ? undefined : 'true'}
	role={label ? 'img' : undefined}
	aria-label={label}
>
	<path d={paths[name]} />
</svg>

<style>
	svg {
		width: 1.1rem;
		height: 1.1rem;
		flex-shrink: 0;
	}
</style>
