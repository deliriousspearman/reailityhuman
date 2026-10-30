<script lang="ts">
	import { onMount } from 'svelte';
	import MachineTable from '$lib/components/MachineTable.svelte';
	import Meter from '$lib/components/Meter.svelte';
	import ConfirmDialog, { type ConfirmRequest } from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import Status from '$lib/components/Status.svelte';
	import { ago, jobStates, tookLabel } from '$lib/format';
	import { api, ApiError } from '$lib/api';
	import { store } from '$lib/store.svelte';
	import { findTemplate } from '$lib/templates';
	import type { CaptureAppliance, TemplateStatus } from '$lib/types';

	// Capacity comes from vCenter, which is slower to ask than the database: on load, then every 30 s.
	onMount(() => {
		void store.refreshCapacity();
		const timer = setInterval(() => store.refreshCapacity(), 30_000);
		return () => clearInterval(timer);
	});
	// The job list is only polled while a page shows it.
	$effect(() => store.needJobs());

	const cap = $derived(store.capacity);
	// How many more of the biggest machine fit in the free memory.
	const biggest = $derived(Math.max(1, ...(store.config?.templates.map((t) => t.resources.memoryGB) ?? [1])));
	// A failed job's error opens under it from the arrow at the end of its row. Kept by job id, so it
	// stays open across polls.
	let openErrors = $state(new Set<string>());
	let copied = $state('');
	function toggleError(id: string) {
		const next = new Set(openErrors);
		if (!next.delete(id)) next.add(id);
		openErrors = next;
	}
	async function copy(id: string, text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = id;
			setTimeout(() => (copied = ''), 1500);
		} catch {}
	}

	// VMs in the machines folder that no machine owns, e.g. from a deploy that failed partway.
	let leftovers = $state<{ name: string; poweredOn: boolean }[] | null>(null);
	let leftoversProblem = $state<string | null>(null);
	let request = $state<ConfirmRequest>();
	async function loadLeftovers() {
		try {
			leftovers = await api('/leftovers');
			leftoversProblem = null;
		} catch (e) {
			leftoversProblem = e instanceof Error ? e.message : String(e);
		}
	}
	onMount(() => void loadLeftovers());
	function deleteLeftover(name: string) {
		request = {
			title: `Delete ${name}?`,
			body: `The VM ${name} and its disk are deleted from vCenter. No machine in the panel owns it. This can't be undone.`,
			label: 'Delete',
			danger: true,
			run: async () => {
				try {
					await api(`/leftovers/${encodeURIComponent(name)}`, { method: 'DELETE' });
				} catch (e) {
					store.say(e instanceof ApiError ? e.message : String(e));
				}
				await loadLeftovers();
			},
		};
	}

	// Templates on demand (docs/plan.md, section 11): delete one no machine uses, keeping its ISOs; the
	// next deploy of it builds it again. Polled every 15 s while a build is queued or running.
	let templates = $state<TemplateStatus[] | null>(null);
	let templatesProblem = $state<string | null>(null);
	async function loadTemplates() {
		try {
			templates = await api('/templates');
			templatesProblem = null;
		} catch (e) {
			templatesProblem = e instanceof Error ? e.message : String(e);
		}
	}
	onMount(() => {
		void loadTemplates();
		const timer = setInterval(() => {
			if (templates?.some((t) => t.job || t.state === 'building')) void loadTemplates();
		}, 15_000);
		return () => clearInterval(timer);
	});
	const templateStates: Record<TemplateStatus['state'], { label: string; tone: 'up' | 'busy' | 'warn' | 'error' }> = {
		built: { label: 'Built', tone: 'up' },
		deleted: { label: 'Not built', tone: 'warn' },
		building: { label: 'Building', tone: 'busy' },
		failed: { label: 'Build failed', tone: 'error' },
	};
	const templateName = (t: TemplateStatus) => `${findTemplate(t.template)?.name ?? t.template} ${t.version}`;
	const freeable = $derived(
		Math.round((templates ?? []).filter((t) => t.deletable).reduce((sum, t) => sum + (t.sizeGB ?? 0), 0)),
	);
	function deleteTemplate(t: TemplateStatus) {
		request = {
			title: `Delete ${templateName(t)}?`,
			body:
				`The template ${t.vsphere} is deleted from vCenter${t.sizeGB ? `, freeing about ${Math.round(t.sizeGB)} GB` : ''}. ` +
				`Its ISO${t.build && t.build.isos.length > 1 ? 's stay' : ' stays'} on the datastore: the next deploy of it builds it again first, ` +
				`which takes about ${t.build?.minutes ?? 30} minutes more.` +
				(t.build?.rolling ? ' It\'s a rolling release, so that build will be a newer one.' : ''),
			label: 'Delete',
			danger: true,
			run: async () => {
				try {
					await api(`/templates/${encodeURIComponent(t.template)}/${encodeURIComponent(t.version)}`, { method: 'DELETE' });
				} catch (e) {
					store.say(e instanceof ApiError ? e.message : String(e));
				}
				await loadTemplates();
			},
		};
	}
	async function buildTemplate(t: TemplateStatus) {
		try {
			await api(`/templates/${encodeURIComponent(t.template)}/${encodeURIComponent(t.version)}/build`, { method: 'POST' });
		} catch (e) {
			store.say(e instanceof ApiError ? e.message : String(e));
		}
		await loadTemplates();
	}

	// A short label for why a built template can't be deleted; its tooltip has the full reason.
	function cantDeleteLabel(t: TemplateStatus): string {
		if (t.machines.length) return 'In use';
		if (!t.rebuildable) return 'No recipe';
		const missing = t.build?.isos.filter((i) => i.present === false).length ?? 0;
		if (missing) return missing > 1 ? 'ISOs missing' : 'ISO missing';
		return "Can't delete";
	}

	const roomFor = $derived(cap ? Math.max(0, Math.floor((cap.total.memoryGB - cap.used.memoryGB) / biggest)) : 0);

	// The packet capture appliance (packer/capture): whether it answers, and the panel's key for it.
	let appliance = $state<CaptureAppliance | null>(null);
	let applianceProblem = $state<string | null>(null);
	async function loadAppliance() {
		appliance = null;
		try {
			appliance = await api<CaptureAppliance>('/capture-appliance');
			applianceProblem = null;
		} catch (e) {
			applianceProblem = e instanceof Error ? e.message : String(e);
		}
	}
	onMount(() => void loadAppliance());
	async function copyKey() {
		if (!appliance?.publicKey) return;
		try {
			await navigator.clipboard.writeText(appliance.publicKey);
			store.say('Copied the public key', 'ok');
		} catch {
			store.say("Couldn't copy: select the key and copy it instead.");
		}
	}
</script>

<svelte:head><title>Admin · Codex Labs</title></svelte:head>

<h1>Admin</h1>
<p class="lead">Capacity of the vSphere cluster, every machine, and what the job worker is doing.</p>

<div class="section-heading">
	<h2 id="capacity">Capacity</h2>
	<p>Powered-on VMs on the cluster, and the datastore machines use</p>
</div>
{#if cap}
	<div class="meters">
		<Meter
			label="Memory"
			used={cap.used.memoryGB}
			total={cap.total.memoryGB}
			unit="GB"
			note="Room for {roomFor} more {roomFor === 1 ? 'machine' : 'machines'} of {biggest} GB"
		/>
		<Meter label="CPU" used={cap.used.cpu} total={cap.total.cpu} unit="vCPU" note="Can be overcommitted; stopped VMs don't count" />
		<Meter
			label="Storage"
			used={cap.used.diskGB}
			total={cap.total.diskGB}
			unit="GB"
			reserve={cap.reserveGB ?? 0}
			note={cap.reserveGB
				? `Linked clones: only changes use space. ${cap.reserveGB} GB is kept free; deploys stop below it.`
				: 'Linked clones: only changes use space'}
		/>
	</div>
{:else if store.capacityProblem}
	<p class="problem"><strong>Can't read capacity:</strong> {store.capacityProblem}</p>
{:else}
	<p class="loading">Asking vCenter…</p>
{/if}

<div class="section-heading">
	<h2>Lab instances <span class="soon-tag">Soon</span></h2>
	<p>Coming with <a href="/labs">Pro Labs</a></p>
</div>

<div class="section-heading">
	<h2 id="machines">Machines</h2>
	<p>{store.machines.filter((m) => m.expiresAt === null).length} kept permanently</p>
</div>
<MachineTable machines={store.machines} owners empty={store.loaded ? 'Nobody has deployed a machine.' : 'Loading…'} />

<div class="section-heading">
	<h2 id="leftovers">Leftover VMs</h2>
	<p>VMs in the machines folder that no machine owns, e.g. from a deploy that failed partway</p>
</div>
{#if leftoversProblem}
	<p class="problem"><strong>Can't list them:</strong> {leftoversProblem}</p>
{:else if !leftovers}
	<p class="loading">Asking vCenter…</p>
{:else if !leftovers.length}
	<p class="loading">None.</p>
{:else}
	<div class="table-wrap">
		<table class="table">
			<thead>
				<tr>
					<th scope="col">VM in vCenter</th>
					<th scope="col">Power</th>
					<th scope="col"><span class="visually-hidden">Actions</span></th>
				</tr>
			</thead>
			<tbody>
				{#each leftovers as vm (vm.name)}
					<tr>
						<th scope="row" class="mono">{vm.name}</th>
						<td>{vm.poweredOn ? 'On' : 'Off'}</td>
						<td class="toggle-cell">
							<button class="btn btn-sm" type="button" onclick={() => deleteLeftover(vm.name)}><Icon name="trash" /> Delete</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<div class="section-heading">
	<h2 id="jobs">Jobs</h2>
	<p>Deploys, resets, power changes and template builds, newest first</p>
</div>
<div class="table-wrap">
	<table class="table jobs">
		<thead>
			<tr>
				<th scope="col">Job</th>
				<th scope="col">Action</th>
				<th scope="col">For</th>
				<th scope="col">By</th>
				<th scope="col">State</th>
				<th scope="col">Started</th>
				<th scope="col">Took</th>
				<th scope="col"><span class="visually-hidden">Error</span></th>
			</tr>
		</thead>
		<tbody>
			{#each store.jobs as job (job.id)}
				{@const open = !!job.detail && openErrors.has(job.id)}
				<tr class:has-detail={open}>
					<th scope="row">{job.id}</th>
					<td>{job.action}</td>
					<td>
						{#if job.template}
							<a href="#templates">Template</a>
						{:else if job.machineId && store.machine(job.machineId)}
							<a href="/machines/{job.machineId}">Machine</a>
						{:else}
							Machine
						{/if}
					</td>
					<td class="mono">{job.by}</td>
					<td><Status size="sm" {...jobStates[job.state]} /></td>
					<td class="mono">{ago(job.queuedAt, store.now)}</td>
					<td class="mono">{tookLabel(job, store.now)}</td>
					<td class="toggle-cell">
						{#if job.detail}
							<button
								class="btn btn-quiet btn-sm toggle"
								class:open
								type="button"
								aria-expanded={open}
								aria-controls="error-{job.id}"
								aria-label="{open ? 'Hide' : 'Show'} the error for {job.id}"
								title={open ? 'Hide error' : 'Show error'}
								onclick={() => toggleError(job.id)}
							>
								<Icon name="chevron" />
							</button>
						{/if}
					</td>
				</tr>
				{#if open}
					<tr class="detail">
						<td colspan="8">
							<pre class="error-full" id="error-{job.id}">{job.detail}</pre>
							<div class="error-actions">
								<button class="btn btn-quiet btn-sm" type="button" onclick={() => copy(job.id, job.detail!)}>
									<Icon name="copy" />{copied === job.id ? 'Copied' : 'Copy'}
								</button>
							</div>
						</td>
					</tr>
				{/if}
			{:else}
				<tr><td colspan="8">{store.loaded ? 'No jobs yet.' : 'Loading…'}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<div class="section-heading">
	<h2 id="templates">Templates</h2>
	<p>
		Delete one no machine uses to free its space; its ISO stays, and the next deploy builds it again{#if freeable}
			· {freeable} GB could be freed{/if}
	</p>
</div>
{#if templatesProblem}
	<p class="problem"><strong>Can't list them:</strong> {templatesProblem}</p>
{:else if !templates}
	<p class="loading">Asking vCenter…</p>
{:else}
	<div class="table-wrap">
		<table class="table templates">
			<thead>
				<tr>
					<th scope="col">Template</th>
					<th scope="col">State</th>
					<th scope="col">Size</th>
					<th scope="col">Machines</th>
					<th scope="col">Last deployed</th>
					<th scope="col">Rebuild</th>
					<th scope="col"><span class="visually-hidden">Actions</span></th>
				</tr>
			</thead>
			<tbody>
				{#each templates as t (`${t.template}/${t.version}`)}
					{@const st = t.job && t.state !== 'building' ? { label: 'Build queued', tone: 'busy' as const } : templateStates[t.state]}
					<tr>
						<th scope="row">
							{templateName(t)}
							{#if t.vsphere}<span class="path mono">{t.vsphere}</span>{/if}
						</th>
						<td>
							<Status size="sm" {...st} />
							{#if t.state === 'failed' && t.detail}<span class="why" title={t.detail}>{t.detail}</span>{/if}
							{#if t.problem}<span class="why">{t.problem}</span>{/if}
						</td>
						<td class="mono">{t.sizeGB === null ? '—' : `${Math.round(t.sizeGB)} GB`}</td>
						<td>{t.machines.length || '—'}</td>
						<td class="mono">{t.lastDeployedAt ? ago(t.lastDeployedAt, store.now) : '—'}</td>
						<td class="mono">{t.build ? `~${t.build.minutes} min` : '—'}</td>
						<td class="toggle-cell">
							{#if t.deletable}
								<button class="btn btn-sm" type="button" onclick={() => deleteTemplate(t)}><Icon name="trash" /> Delete</button>
							{:else if t.rebuildable && (t.state === 'deleted' || t.state === 'failed') && !t.job}
								<button class="btn btn-sm" type="button" onclick={() => buildTemplate(t)}><Icon name="rebuild" /> Build</button>
							{:else if t.cantDelete && t.state === 'built'}
								<span class="why hint" title={t.cantDelete}>{cantDeleteLabel(t)}</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<ConfirmDialog bind:request />

<div class="section-heading">
	<h2 id="capture">Packet capture</h2>
	<p>The capture appliance, which sees the machines' traffic for the Network page's captures</p>
</div>
{#if applianceProblem}
	<p class="problem"><strong>Can't ask the panel:</strong> {applianceProblem}</p>
{:else if !appliance}
	<p class="loading">Asking the appliance…</p>
{:else}
	<dl class="stats">
		<div>
			<dt>Appliance</dt>
			<dd><Status tone={appliance.ok ? 'up' : 'error'} label={appliance.ok ? 'Answering' : 'Not answering'} /></dd>
			<span class="stat-note">{appliance.problem ?? (appliance.vm || appliance.host)}</span>
		</div>
		<div>
			<dt>Address</dt>
			<dd><code>{appliance.host || '—'}</code></dd>
			<span class="stat-note">{appliance.vm ? `from VMware Tools (${appliance.vm})` : 'CAPTURE_HOST'}</span>
		</div>
		<div>
			<dt>Running now</dt>
			<dd>{appliance.running}</dd>
			<span class="stat-note">captures</span>
		</div>
	</dl>
	{#if appliance.publicKey}
		<p class="key-intro">The panel's key: build the appliance with it (<code>packer/build.sh capture -var panel_key="…"</code>).</p>
		<div class="key">
			<code>{appliance.publicKey}</code>
			<button class="btn btn-sm" type="button" onclick={copyKey}><Icon name="copy" /> Copy</button>
		</div>
	{/if}
	<button class="btn btn-sm recheck" type="button" onclick={loadAppliance}><Icon name="reboot" /> Check again</button>
{/if}

<style>
	.key-intro {
		margin-top: 1rem;
		font-size: 0.875rem;
		color: var(--lms-gray-2);
	}
	.key-intro code {
		font: 0.82rem var(--lms-mono);
	}
	.key {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem;
		margin-top: 0.5rem;
		padding: 0.6rem 0.8rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		background: var(--lms-bg-code);
	}
	.key code {
		flex: 1;
		font: 0.78rem var(--lms-mono);
		color: var(--lms-lime-text);
		overflow-wrap: anywhere;
	}
	.recheck {
		margin-top: 0.75rem;
	}
	.lead {
		margin: 0.75rem 0 0;
	}
	.meters {
		display: grid;
		gap: 1rem;
		grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr));
	}
	.jobs tr.has-detail > * {
		border-bottom: none;
	}
	/* The error cell mustn't widen the table: with max-width 0 it takes the width the other
	   columns set, and its text fits inside that. */
	.detail td {
		max-width: 0;
		width: 100%;
		padding-top: 0;
		white-space: normal;
		color: var(--lab-error);
	}
	.toggle-cell {
		width: 1%;
		padding-block: 0.3rem;
		text-align: end;
	}
	.toggle {
		padding-inline: 0.35rem;
		color: var(--lab-error);
	}
	.toggle :global(svg) {
		transition: transform 0.15s ease;
	}
	.toggle.open :global(svg) {
		transform: rotate(180deg);
	}
	.error-full {
		max-height: 16rem;
		margin: 0;
		padding: 0.6rem 0.75rem;
		overflow: auto;
		border: 1px solid var(--lms-gray-5);
		border-radius: var(--lms-radius-sm);
		background: var(--lms-panel);
		font: 0.8rem/1.6 var(--lms-mono);
		color: var(--lab-error);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.error-actions {
		display: flex;
		gap: 0.25rem;
		margin-top: 0.35rem;
	}
	.problem,
	.loading {
		color: var(--lms-gray-3);
	}
	.problem strong {
		color: var(--lab-error);
	}
	.templates .path {
		display: block;
		font-size: 0.75rem;
		color: var(--lms-gray-3);
		font-weight: normal;
	}
	.templates .why {
		display: block;
		max-width: 22rem;
		font-size: 0.8rem;
		color: var(--lms-gray-3);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* The full reason is in its tooltip: show that it has one. */
	.templates .hint {
		text-decoration: underline dotted;
		text-underline-offset: 0.2em;
		cursor: help;
	}
	h2 .soon-tag {
		vertical-align: middle;
	}
</style>
