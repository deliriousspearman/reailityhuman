import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	// Keep font files as separate assets rather than inlined data: URIs, so a strict CSP
	// (font-src 'self') still allows them. Same reasoning as the LMS's astro.config.mjs.
	build: { assetsInlineLimit: 0 },
});
