<script lang="ts">
	// How to connect: a per-person WireGuard file for a lab instance or for the person's own network.
	// The real file (with the private key) comes from the API; this preview never shows the key.
	import { store } from '$lib/mock/store.svelte';
	import Icon from './Icon.svelte';

	let {
		fileName,
		label,
		endpoint,
		cidr,
		ready,
		expires = false,
		lab = true,
	}: {
		fileName: string;
		/** What the tunnel is for, written into the file as a comment. */
		label: string;
		endpoint: string;
		/** The network the tunnel routes to, and where to start. */
		cidr: string;
		ready: boolean;
		/** Whether the file stops working when the thing it connects to expires. */
		expires?: boolean;
		/** A lab: every copy uses the same addresses, so only one lab tunnel can be up at a time. */
		lab?: boolean;
	} = $props();

	const config = $derived(
		[
			'[Interface]',
			`# ${store.user.username}: ${label}`,
			'PrivateKey = <in the downloaded file>',
			'Address = 10.254.1.7/32',
			'',
			'[Peer]',
			'PublicKey = mJ3vT1bq0uXfZt6Lr8Hn2yWcQe5Pd9Ka4Sg7Vx1Bo0=',
			`Endpoint = ${endpoint}`,
			`AllowedIPs = ${cidr}`,
			'PersistentKeepalive = 25',
		].join('\n'),
	);

	let copied = $state(false);

	function download() {
		const blob = new Blob([config.replace('<in the downloaded file>', 'mock-private-key-not-real=') + '\n'], {
			type: 'text/plain',
		});
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = fileName;
		a.click();
		URL.revokeObjectURL(a.href);
	}

	async function copy() {
		try {
			await navigator.clipboard.writeText(cidr);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch {}
	}
</script>

<section class="access" aria-labelledby="access-title">
	<div class="section-heading">
		<h2 id="access-title">Connect</h2>
		<p>WireGuard</p>
	</div>

	<ol class="steps">
		<li>
			<span>Download your connection file.</span>
			<button class="btn btn-primary" type="button" disabled={!ready} onclick={download}>
				<Icon name="download" /> Download
			</button>
		</li>
		<li><span>Import it into the WireGuard app and activate the tunnel.</span></li>
		<li>
			<span>
				{lab ? 'Start from' : 'Your machines are in'} <code>{cidr}</code>
				<button class="btn btn-quiet btn-sm copy" type="button" onclick={copy}>
					<Icon name="copy" />{copied ? 'Copied' : 'Copy'}
				</button>
			</span>
		</li>
	</ol>
	{#if !ready}
		<p class="note">The file is ready once it's running.</p>
	{/if}

	<div class="terminal">
		<div class="terminal-bar"><span>{fileName}</span></div>
		<pre class="terminal-body">{config}</pre>
	</div>
	<p class="note">
		{#if lab}Connect to one lab at a time: every copy of a lab uses the same addresses.{/if}
		Your file stops working when {expires ? 'this is destroyed or expires' : 'this is destroyed'}.
	</p>
</section>

<style>
	.access {
		display: grid;
		gap: 1rem;
		align-content: start;
	}
	.access .section-heading {
		margin: 0;
	}
	/* A real sequence, so numbered. */
	.steps {
		display: grid;
		gap: 0.75rem;
		margin: 0;
		padding: 0;
		list-style: none;
		counter-reset: step;
	}
	.steps li {
		counter-increment: step;
		position: relative;
		display: grid;
		gap: 0.5rem;
		justify-items: start;
		padding-left: 2.25rem;
		color: var(--lms-gray-1);
	}
	.steps li::before {
		content: counter(step);
		position: absolute;
		left: 0;
		top: 0;
		display: grid;
		place-items: center;
		width: 1.5rem;
		height: 1.5rem;
		border: 1px solid var(--lms-lime);
		border-radius: var(--lms-radius-xs);
		font: 700 0.75rem var(--lms-mono);
		color: var(--lms-lime-text);
	}
	.steps code {
		color: var(--lms-lime-text);
	}
	.copy {
		min-height: 1.75rem;
		margin-inline-start: 0.25rem;
		vertical-align: middle;
	}
	.copy :global(svg) {
		width: 0.9rem;
		height: 0.9rem;
	}
	.note {
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
</style>
