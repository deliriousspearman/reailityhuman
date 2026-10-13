<script lang="ts">
	import { onMount } from 'svelte';
	import MachineTable from '$lib/components/MachineTable.svelte';
	import Meter from '$lib/components/Meter.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import Status from '$lib/components/Status.svelte';
	import { ago, duration, type Tone } from '$lib/format';
	import { store } from '$lib/store.svelte';
	import type { JobState } from '$lib/types';

	const jobStates: Record<JobState, { label: string; tone: Tone }> = {
		queued: { label: 'Queued', tone: 'down' },
		running: { label: 'Running', tone: 'busy' },
		done: { label: 'Done', tone: 'up' },
		failed: { label: 'Failed', tone: 'error' },
	};

	// Capacity comes from vCenter, which is slower to ask than the database: on load, then every 30 s.
	onMount(() => {
		void store.refreshCapacity();
		const timer = setInterval(() => store.refreshCapacity(), 30_000);
		return () => clearInterval(timer);
	});

	const cap = $derived(store.capacity);
	// How many more of the biggest machine fit in the free memory.
	const biggest = $derived(Math.max(1, ...(store.config?.templates.map((t) => t.resources.memoryGB) ?? [1])));
	// Job errors show one line; long ones open in place. Kept by job id, so they stay open across polls.
	const LONG = 140;
	let openErrors = $state(new Set<string>());
	let copied = $state('');
	const isLong = (text: string) => text.length > LONG || text.includes('\n');
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

	const roomFor = $derived(cap ? Math.max(0, Math.floor((cap.total.memoryGB - cap.used.memoryGB) / biggest)) : 0);
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
		<Meter label="Storage" used={cap.used.diskGB} total={cap.total.diskGB} unit="GB" note="Linked clones: only changes use space" />
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
	<h2 id="jobs">Jobs</h2>
	<p>Deploys, resets and power changes, newest first</p>
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
			</tr>
		</thead>
		<tbody>
			{#each store.jobs as job (job.id)}
				<tr class:has-detail={job.detail}>
					<th scope="row">{job.id}</th>
					<td>{job.action}</td>
					<td>
						{#if job.machineId && store.machine(job.machineId)}
							<a href="/machines/{job.machineId}">Machine</a>
						{:else}
							Machine
						{/if}
					</td>
					<td class="mono">{job.by}</td>
					<td><Status size="sm" {...jobStates[job.state]} /></td>
					<td class="mono">{ago(job.startedAt, store.now)}</td>
					<td class="mono">{job.finishedAt ? duration(job.finishedAt - job.startedAt) : '…'}</td>
				</tr>
				{#if job.detail}
					{@const open = openErrors.has(job.id)}
					{@const long = isLong(job.detail)}
					<tr class="detail">
						<td colspan="7">
							{#if open}
								<pre class="error-full" id="error-{job.id}">{job.detail}</pre>
							{:else}
								<p class="error-line" id="error-{job.id}">{job.detail.split('\n')[0]}</p>
							{/if}
							{#if long}
								<div class="error-actions">
									<button
										class="btn btn-quiet btn-sm"
										type="button"
										aria-expanded={open}
										aria-controls="error-{job.id}"
										onclick={() => toggleError(job.id)}
									>
										{open ? 'Hide' : 'Show full error'}
									</button>
									{#if open}
										<button class="btn btn-quiet btn-sm" type="button" onclick={() => copy(job.id, job.detail!)}>
											<Icon name="copy" />{copied === job.id ? 'Copied' : 'Copy'}
										</button>
									{/if}
								</div>
							{/if}
						</td>
					</tr>
				{/if}
			{:else}
				<tr><td colspan="7">{store.loaded ? 'No jobs yet.' : 'Loading…'}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
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
	.error-line {
		margin: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
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
	h2 .soon-tag {
		vertical-align: middle;
	}
</style>
