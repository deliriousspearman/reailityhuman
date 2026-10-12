<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import { clock, hoursLabel } from '$lib/format';
	import { ApiError } from '$lib/api';
	import { store } from '$lib/store.svelte';
	import { findTemplate, flagNotes } from '$lib/templates';
	import type { Access } from '$lib/types';

	const template = $derived(findTemplate(page.params.template ?? ''));

	const DURATIONS = [2, 4, 8, 24, 72, 168];
	const accessNames: Record<Access, string> = { ssh: 'SSH', rdp: 'Remote Desktop', web: 'Web interface', console: 'Console' };

	let version = $state('');
	let name = $state('');
	/** Hours to keep it, or 'keep' for permanently. */
	let keep = $state<number | 'keep'>(4);
	let sshKey = $state('');
	let submitting = $state(false);
	let failure = $state<string | null>(null);

	// Defaults when the template changes (or the API's list of live versions arrives): its newest
	// version that can be deployed, and a free name like "ubuntu01". Only those are tracked, so later
	// changes to the machine list don't overwrite what you've typed.
	$effect(() => {
		const t = template;
		const config = store.config;
		if (!t) return;
		untrack(() => {
			version = (config && t.versions.find((v) => store.isLive(t.id, v.version))?.version) ?? t.versions[0].version;
			const base = t.id.split('-')[0];
			const taken = new Set(store.machines.map((m) => m.name));
			let n = 1;
			while (taken.has(`${base}${String(n).padStart(2, '0')}`)) n++;
			name = `${base}${String(n).padStart(2, '0')}`;
		});
	});

	// Hostname rules: what vSphere guest customisation and most OSes accept.
	const nameProblem = $derived(
		!name
			? 'Give it a name.'
			: !/^[a-z][a-z0-9-]{0,14}$/.test(name)
				? 'Use 1 to 15 lowercase letters, digits or hyphens, starting with a letter.'
				: store.machines.some((m) => m.name === name)
					? `There's already a machine called ${name}.`
					: null,
	);
	const canKeep = $derived(store.permanentCount < store.permanentQuota);
	const blocker = $derived(
		template ? (store.machineBlocker(template) ?? (store.isLive(template.id, version) ? null : `${version} isn't available yet.`)) : null,
	);
	const eol = $derived(template?.versions.find((v) => v.version === version)?.eol);
	const username = $derived(store.config?.templates.find((t) => t.template === template?.id && t.version === version)?.username);

	async function deploy(event: SubmitEvent) {
		event.preventDefault();
		if (!template || nameProblem || blocker || submitting) return;
		submitting = true;
		failure = null;
		try {
			const m = await store.deployMachine(template, version, name, keep === 'keep' ? null : keep, sshKey);
			goto(`/machines/${m.id}`);
		} catch (e) {
			failure = e instanceof ApiError ? e.message : String(e);
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head><title>Deploy {template?.name ?? 'machine'} · Codex Labs</title></svelte:head>

{#if !template}
	<h1>Not found</h1>
	<p class="lead">There's no machine template here. <a href="/machines">See all machines</a>.</p>
{:else}
	<nav class="breadcrumbs" aria-label="Breadcrumbs">
		<a href="/machines">Machines</a> <span aria-hidden="true">›</span> <span aria-current="page">Deploy {template.name}</span>
	</nav>

	<header class="title">
		<h1>Deploy {template.name}</h1>
		<span class="os" data-os={template.os.toLowerCase()}>{template.os}</span>
	</header>
	<p class="lead">{template.description}</p>

	<form class="deploy" onsubmit={deploy}>
		<div class="fields">
			<fieldset>
				<legend>Version</legend>
				<div class="options">
					{#each template.versions as v (v.version)}
						{@const live = store.isLive(template.id, v.version)}
						<label class="option" class:disabled={!live}>
							<input type="radio" name="version" value={v.version} bind:group={version} disabled={!live} />
							<span>{v.version}</span>
							{#if !live}<span class="soon-tag">Soon</span>{:else if v.eol}<span class="eol">End of life</span>{/if}
						</label>
					{/each}
				</div>
				{#if eol}
					<p class="hint">No more updates from the vendor. Good for practising on old systems; don't use it for anything else.</p>
				{/if}
			</fieldset>

			<div class="field">
				<label for="name">Name</label>
				<input
					id="name"
					class="input mono-input"
					bind:value={name}
					autocomplete="off"
					spellcheck="false"
					aria-invalid={!!nameProblem}
					aria-describedby="name-hint"
				/>
				<p id="name-hint" class="hint" class:problem={nameProblem}>
					{nameProblem ?? 'Also its hostname.'}
				</p>
			</div>

			<fieldset>
				<legend>Keep it for</legend>
				<div class="options">
					{#each DURATIONS as h (h)}
						<label class="option">
							<input type="radio" name="keep" value={h} bind:group={keep} />
							<span>{hoursLabel(h)}</span>
						</label>
					{/each}
					<label class="option" class:disabled={!canKeep}>
						<input type="radio" name="keep" value="keep" bind:group={keep} disabled={!canKeep} />
						<span>Permanently</span>
					</label>
				</div>
				<p class="hint">
					{#if keep === 'keep'}
						It won't expire. {store.permanentQuota === 1 ? 'One machine' : `${store.permanentQuota} machines`} can be kept permanently.
					{:else}
						Powered off at {clock(store.now + keep * 3_600_000, store.now)} and deleted a day later, unless you extend it.
					{/if}
					{#if !canKeep}{store.permanentCount} are kept permanently already, the most allowed.{/if}
				</p>
			</fieldset>

			<div class="field">
				<label for="ssh-key">SSH public key <span class="optional">optional</span></label>
				<textarea
					id="ssh-key"
					class="input mono-input"
					rows="3"
					bind:value={sshKey}
					spellcheck="false"
					placeholder="ssh-ed25519 AAAA… you@laptop"
					aria-describedby="ssh-key-hint"
				></textarea>
				<p id="ssh-key-hint" class="hint">Added for {username ?? 'the user'}, so you can sign in without the password.</p>
			</div>
		</div>

		<aside class="summary panel">
			<h2>Summary</h2>
			<dl>
				<div><dt>Machine</dt><dd>{template.name} {version}</dd></div>
				<div><dt>Uses</dt><dd>{template.resources.cpu} vCPU, {template.resources.memoryGB} GB memory, {template.resources.diskGB} GB disk</dd></div>
				<div><dt>Network</dt><dd>The LAN, with an address from DHCP</dd></div>
				<div><dt>Sign in with</dt><dd>{template.access.map((a) => accessNames[a]).join(', ')}</dd></div>
				{#if username}
					<div><dt>First sign-in</dt><dd><code>{username}</code>, with a password shown once it's deployed</dd></div>
				{:else if template.credentials}
					<div><dt>First sign-in</dt><dd><code>{template.credentials}</code></dd></div>
				{/if}
			</dl>
			{#if template.flags?.length}
				<ul class="flag-notes">
					{#each template.flags as f (f)}
						<li><span class="tag">{flagNotes[f].label}</span> {flagNotes[f].note}</li>
					{/each}
				</ul>
			{/if}
			<button class="btn btn-primary" type="submit" disabled={!!nameProblem || !!blocker || submitting}>
				<Icon name="plus" /> {submitting ? 'Deploying…' : `Deploy ${name || 'machine'}`}
			</button>
			{#if blocker || failure}<p class="blocker" role="status"><Icon name="alert" /> {failure ?? blocker}</p>{/if}
		</aside>
	</form>
{/if}

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
	.title {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1rem;
	}
	.title .os {
		font-size: 0.8rem;
		padding: 0.1rem 0.5rem;
	}
	.lead {
		max-width: 44rem;
		margin: 0.75rem 0 2rem;
	}

	.deploy {
		display: grid;
		gap: 1.5rem;
		align-items: start;
	}
	@media (min-width: 64rem) {
		.deploy {
			grid-template-columns: minmax(0, 1fr) 22rem;
			gap: 2.5rem;
		}
		.summary {
			position: sticky;
			top: calc(var(--lab-header-height) + 1rem);
		}
	}
	.fields {
		display: grid;
		gap: 1.75rem;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: 0;
	}
	legend {
		margin-bottom: 0.6rem;
		font: 700 1.05rem var(--lms-display);
		color: var(--lms-white);
	}
	.field label {
		font: 700 1.05rem var(--lms-display);
		color: var(--lms-white);
	}
	.mono-input {
		max-width: 20rem;
		font-family: var(--lms-mono);
	}
	.mono-input[aria-invalid='true'] {
		border-color: var(--lms-hard);
	}

	/* Choices as outlined tiles; the chosen one gets the lime rail. */
	.options {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.option {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.85rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-sm);
		background: var(--lms-panel);
		color: var(--lms-gray-1);
		font: 600 0.9rem var(--lms-mono);
		cursor: pointer;
	}
	.option:hover {
		border-color: var(--lms-gray-3);
	}
	.option input {
		position: absolute;
		opacity: 0;
		pointer-events: none;
	}
	.option:has(input:checked) {
		border-color: var(--lms-lime);
		background: var(--lms-accent-low);
		color: var(--lms-lime-text);
		box-shadow: inset 3px 0 0 var(--lms-lime);
	}
	.option:has(input:focus-visible) {
		outline: 2px solid var(--lms-accent-high);
		outline-offset: 2px;
	}
	.option.disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	textarea.mono-input {
		resize: vertical;
		min-height: 4.5rem;
		font-size: 0.8rem;
	}
	.optional {
		margin-inline-start: 0.4rem;
		font-weight: 400;
		font-size: 0.8rem;
		color: var(--lms-gray-3);
	}
	.eol {
		padding: 0 0.35rem;
		border: 1px solid var(--lms-medium);
		border-radius: var(--lms-radius-xs);
		font-size: 0.68rem;
		color: var(--lms-medium);
	}
	.hint {
		margin-top: 0.5rem;
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}
	.hint.problem {
		color: var(--lms-hard);
	}

	.summary {
		display: grid;
		gap: 1rem;
		padding: 1.25rem;
		border-top: 3px solid var(--lms-lime);
	}
	.summary h2 {
		font-size: 1.15rem;
	}
	dl {
		display: grid;
		gap: 0.6rem;
		margin: 0;
		font-size: 0.875rem;
	}
	dt {
		font: 600 0.7rem var(--lms-mono);
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--lms-gray-3);
	}
	dd {
		margin: 0.1rem 0 0;
		color: var(--lms-white);
	}
	dd code {
		color: var(--lms-lime-text);
	}
	.flag-notes {
		display: grid;
		gap: 0.5rem;
		margin: 0;
		padding: 0.75rem 0 0;
		border-top: 1px solid var(--lms-gray-5);
		list-style: none;
		font-size: 0.8rem;
		color: var(--lms-gray-2);
	}
	.flag-notes .tag {
		margin-inline-end: 0.3rem;
	}
	.blocker {
		display: flex;
		gap: 0.5rem;
		font-size: 0.85rem;
		color: var(--lms-medium);
	}
</style>
