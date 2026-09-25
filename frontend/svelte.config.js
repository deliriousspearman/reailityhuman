import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		// A single-page app served as static files by Caddy. Every route falls back to 200.html and
		// renders in the browser, since instance state comes from the API at runtime.
		adapter: adapter({ fallback: '200.html' }),
	},
};

export default config;
