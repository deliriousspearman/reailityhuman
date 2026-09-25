<script lang="ts">
	import InstanceTable from '$lib/components/InstanceTable.svelte';
	import MachineTable from '$lib/components/MachineTable.svelte';
	import Meter from '$lib/components/Meter.svelte';
	import Status from '$lib/components/Status.svelte';
	import { ago, duration, type Tone } from '$lib/format';
	import { findLab, labs } from '$lib/mock/labs';
	import { store } from '$lib/mock/store.svelte';
	import type { JobState } from '$lib/types';

	const jobStates: Record<JobState, { label: string; tone: Tone }> = {
		queued: { label: 'Queued', tone: 'down' },
		running: { label: 'Running', tone: 'busy' },
		done: { label: 'Done', tone: 'up' },
		failed: { label: 'Failed', tone: 'error' },
	};

	const used = $derived(store.used);
	const cap = store.capacity;
	// How many more copies of the biggest lab fit in the free memory: the number that matters when a
	// class wants to start their own copies at once.
	const biggest = [...labs].sort((a, b) => b.resources.memoryGB - a.resources.memoryGB)[0];
	const roomFor = $derived(Math.floor((cap.memoryGB - used.memoryGB) / biggest.resources.memoryGB));
</script>

<svelte:head><title>Admin · Codex Labs</title></svelte:head>

{#if !store.isAdmin}
	<h1>Admins only</h1>
	<p class="lead">This page is for lab admins. <a href="/">Back to Pro Labs</a></p>
{:else}
	<h1>Admin</h1>
	<p class="lead">Capacity of the ProLabs resource pool, every lab instance and machine, and what the job worker is doing.</p>

	<div class="section-heading"><h2>Capacity</h2></div>
	<div class="meters">
		<Meter
			label="Memory"
			used={used.memoryGB}
			total={cap.memoryGB}
			unit="GB"
			note="Room for {roomFor} more {roomFor === 1 ? 'copy' : 'copies'} of {biggest.title} ({biggest.resources.memoryGB} GB each)"
		/>
		<Meter label="CPU" used={used.cpu} total={cap.cpu} unit="vCPU" note="Stopped labs and machines don't count" />
		<Meter label="Storage" used={used.diskGB} total={cap.diskGB} unit="GB" note="Linked clones: only changes use space" />
	</div>

	<div class="section-heading"><h2>Lab instances</h2></div>
	<InstanceTable instances={store.instances} />

	<div class="section-heading">
		<h2>Machines</h2>
		<p>{store.machines.filter((m) => m.expiresAt === null).length} kept permanently</p>
	</div>
	<MachineTable machines={store.machines} owners empty="Nobody has deployed a machine." />

	<div class="section-heading">
		<h2>Jobs</h2>
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
							{#if job.machineId}
								{#if store.machine(job.machineId)}<a href="/machines/{job.machineId}">Machine</a>{:else}Machine{/if}
							{:else if store.instance(job.instanceId)}
								<a href="/instances/{job.instanceId}">{findLab(job.lab)?.title}</a>
							{:else}
								{findLab(job.lab)?.title}
							{/if}
						</td>
						<td class="mono">{job.by}</td>
						<td><Status size="sm" {...jobStates[job.state]} /></td>
						<td class="mono">{ago(job.startedAt, store.now)}</td>
						<td class="mono">{job.finishedAt ? duration(job.finishedAt - job.startedAt) : '…'}</td>
					</tr>
					{#if job.detail}
						<tr class="detail">
							<td colspan="7">
								<span>{job.detail}</span>
								{#if job.state === 'failed'}
									{#if job.retriedAs}
										<span class="retried">Retried as {job.retriedAs}</span>
									{:else}
										<button class="btn btn-sm" type="button" onclick={() => store.retry(job)}>Retry for {job.by}</button>
									{/if}
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
{/if}

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
	.detail td {
		white-space: normal;
		padding-top: 0;
	}
	.detail td {
		color: var(--lab-error);
	}
	.detail td > * + * {
		margin-inline-start: 0.75rem;
	}
	.retried {
		font: 0.8rem var(--lms-mono);
		color: var(--lms-gray-3);
	}
</style>
