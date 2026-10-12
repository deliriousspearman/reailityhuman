import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	// Keep font files as separate assets rather than inlined data: URIs, so a strict CSP
	// (font-src 'self') still allows them. Same reasoning as the LMS's astro.config.mjs.
	build: { assetsInlineLimit: 0 },
	// In development, the API runs separately (uvicorn on :8000); in production Caddy routes /api to it.
	server: { proxy: { '/api': 'http://localhost:8000' } },
});
