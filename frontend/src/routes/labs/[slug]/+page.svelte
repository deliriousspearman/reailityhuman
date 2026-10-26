<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError } from '$lib/api';
	import ComingSoon from '$lib/components/ComingSoon.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import OsLogo from '$lib/components/OsLogo.svelte';
	import Status from '$lib/components/Status.svelte';
	import { clock, duration, hoursLabel, inWords, singleMachineStates } from '$lib/format';
	import { findLab } from '$lib/labs';
	import { store } from '$lib/store.svelte';
	import { templateFor } from '$lib/templates';

	const DURATIONS = [2, 4, 8, 24, 72];

	const lab = $derived(store.lab(page.params.slug ?? ''));
	// The LMS's design of a lab that isn't in labs.yaml yet.
	const design = $derived(findLab(page.params.slug ?? ''));
	const running = $derived(store.instances.filter((i) => i.lab === lab?.slug));
	const blocker = $derived(lab ? store.labBlocker(lab) : null);

	let owner = $state(store.user);
	let hours = $state(4);
	let submitting = $state(false);
	let failure = $state<string | null>(null);

	const ownerProblem = $derived(
		!owner.trim() ? 'Add your name, so people can tell whose lab it is.' : store.ownerProblem(owner.trim().toLowerCase()),
	);

	async function deploy(event: SubmitEvent) {
		event.preventDefault();
		if (!lab || ownerProblem || blocker || submitting) return;
		submitting = true;
		failure = null;
		try {
			const i = await store.deployLab(lab, hours, owner);
			goto(`/instances/${i.id}`);
		} catch (e) {
			failure = e instanceof ApiError ? e.message : String(e);
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head><title>{lab?.title ?? design?.title ?? 'Pro Lab'} · Codex Labs</title></svelte:head>

{#if !lab}
	{#if !store.config}
		<p class="loading">Loading…</p>
	{:else}
		<ComingSoon title={design?.title ?? 'Pro Labs'}>
			This lab can't be deployed yet. {design ? design.description : ''} <a href="/labs">See the labs</a>.
		</ComingSoon>
	{/if}
{:else}
	<nav class="breadcrumbs" aria-label="Breadcrumbs">
		<a href="/labs">Pro Labs</a> <span aria-hidden="true">›</span> <span aria-current="page">{lab.title}</span>
	</nav>

	<header class="title">
		{#if design?.image}<img class="picture" src={design.image} alt="" width="64" height="64" />{/if}
		<h1>{lab.title}</h1>
		<span class="level-chip" data-level={lab.level.toLowerCase()}>{lab.level}</span>
		{#if lab.planned}<span class="soon-tag">Soon</span>{/if}
	</header>
	<p class="lead">{lab.description}</p>

	<div class="layout">
		<div class="main">
			<div class="section-heading"><h2>Machines</h2></div>
			<p class="hint">
				Set up in this order{lab.domain ? `, in the domain ${lab.domain}` : ''}: each waits until the ones before it are
				running.{lab.resetScope === 'lab' ? ' Resetting puts every machine back together.' : ''}
			</p>
			<div class="table-wrap">
				<table class="table">
					<thead>
						<tr>
							<th scope="col">Order</th>
							<th scope="col">Name</th>
							<th scope="col">Role</th>
							<th scope="col">Runs</th>
						</tr>
					</thead>
					<tbody>
						{#each lab.machines as m (m.name)}
							{@const t = templateFor(m.template)}
							<tr>
								<td class="mono">{m.bootOrder}</td>
								<th scope="row" class="mono">{m.name}</th>
								<td>{m.role || '–'}</td>
								<td><span class="runs"><OsLogo id={t.id} name={t.name} size="sm" /> {t.name} {m.version}</span></td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			{#if lab.flags.length}
				<div class="section-heading"><h2>Flags</h2></div>
				<p class="hint">New ones are planted in every instance, each time it's deployed or reset.</p>
				<ul class="flags">
					{#each lab.flags as f (f.id)}
						<li><span class="tag">{f.id}</span> {f.where}</li>
					{/each}
				</ul>
			{/if}

			{#if running.length}
				<div class="section-heading"><h2>Running</h2></div>
				<ul class="running">
					{#each running as i (i.id)}
						<li>
							<a class="mono" href="/instances/{i.id}">{i.id}</a>
							<Status size="sm" {...singleMachineStates[i.state]} />
							<span class="meta">
								{i.owner}, {i.expiresAt === null ? 'kept permanently' : `${duration(i.expiresAt - store.now)} left`}
							</span>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<form class="summary panel" onsubmit={deploy}>
			<h2>Deploy</h2>
			<div class="field">
				<label for="owner">Owner</label>
				<input
					id="owner"
					class="input mono-input"
					bind:value={owner}
					autocomplete="username"
					spellcheck="false"
					placeholder="e.g. john"
					aria-invalid={!!ownerProblem}
					aria-describedby="owner-hint"
				/>
				<p id="owner-hint" class="hint" class:problem={ownerProblem}>{ownerProblem ?? 'Your name; remembered in this browser.'}</p>
			</div>
			<fieldset>
				<legend>Keep it for</legend>
				<div class="options">
					{#each DURATIONS as h (h)}
						<label class="option">
							<input type="radio" name="hours" value={h} bind:group={hours} />
							<span>{hoursLabel(h)}</span>
						</label>
					{/each}
				</div>
				<p class="hint">
					Powered off at {clock(store.now + hours * 3_600_000, store.now)} and deleted {inWords(store.grace)} later, unless you extend it.
				</p>
			</fieldset>
			{#if !lab.planned}
				<p class="hint">{lab.machines.length} machines, about {lab.memoryGB} GB of memory.</p>
			{/if}
			{#if blocker}<p class="hint problem">{blocker}</p>{/if}
			{#if failure}<p class="hint problem" role="alert">{failure}</p>{/if}
			<button class="btn btn-primary" type="submit" disabled={!!ownerProblem || !!blocker || submitting}>
				<Icon name="plus" /> {submitting ? 'Deploying…' : `Deploy ${lab.title}`}
			</button>
		</form>
	</div>
{/if}

<style>
	.loading {
		padding-block: 3rem;
		color: var(--lms-gray-3);
	}
	.title {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem 1rem;
	}
	.picture {
		width: 4rem;
		height: 4rem;
		border-radius: var(--lms-radius-md);
		border: var(--lms-border-width) solid var(--lms-gray-5);
		background: #0d1420;
	}
	.lead {
		max-width: 44rem;
		margin-top: 0.75rem;
		color: var(--lms-gray-2);
	}
	.layout {
		display: grid;
		gap: 1.5rem;
		align-items: start;
		margin-top: 1.5rem;
	}
	@media (min-width: 64rem) {
		.layout {
			grid-template-columns: minmax(0, 1fr) 22rem;
			gap: 2.5rem;
		}
		.summary {
			position: sticky;
			top: calc(var(--lab-header-height) + 1rem);
		}
	}
	.main .section-heading:not(:first-child) {
		margin-top: 1.75rem;
	}
	.runs {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
	}
	.hint {
		margin-block: 0.5rem;
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}
	.hint.problem {
		color: var(--lms-hard);
	}
	.flags,
	.running {
		display: grid;
		gap: 0.5rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.flags .tag {
		margin-inline-end: 0.4rem;
	}
	.running li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1rem;
	}
	.running .meta {
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}

	.summary {
		display: grid;
		gap: 1.1rem;
		padding: 1.25rem;
		border-top: 3px solid var(--lms-lime);
	}
	.summary h2 {
		font-size: 1.3rem;
	}
	.field {
		display: grid;
		gap: 0.4rem;
	}
	.field label,
	legend {
		font: 700 1.05rem var(--lms-display);
		color: var(--lms-white);
	}
	legend {
		margin-bottom: 0.6rem;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: 0;
	}
	.mono-input {
		font-family: var(--lms-mono);
	}
	.mono-input[aria-invalid='true'] {
		border-color: var(--lms-hard);
	}
	/* Choices as outlined tiles; the chosen one gets the lime rail (as on the machine deploy form). */
	.options {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.option {
		position: relative;
		display: inline-flex;
		align-items: center;
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
</style>
