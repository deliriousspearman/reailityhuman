<script lang="ts" module>
	export interface ConfirmRequest {
		title: string;
		body: string;
		/** Button text: the action's name, e.g. "Reset lab". */
		label: string;
		danger?: boolean;
		run: () => void;
	}
</script>

<script lang="ts">
	// A modal confirmation for disruptive actions (reset, stop, rebuild, destroy). Set `request` to open
	// it; it clears itself when closed.
	let { request = $bindable() }: { request?: ConfirmRequest } = $props();

	let dialog: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (request && !dialog?.open) dialog?.showModal();
	});

	function confirm() {
		request?.run();
		dialog?.close();
	}
</script>

<dialog bind:this={dialog} onclose={() => (request = undefined)} aria-labelledby="confirm-title">
	{#if request}
		<h2 id="confirm-title">{request.title}</h2>
		<p>{request.body}</p>
		<div class="actions">
			<button class="btn btn-quiet" type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="btn {request.danger ? 'btn-danger' : 'btn-primary'}" type="button" onclick={confirm}>
				{request.label}
			</button>
		</div>
	{/if}
</dialog>

<style>
	dialog {
		width: min(28rem, calc(100vw - 2rem));
		padding: 1.5rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-top: 3px solid var(--lms-lime);
		border-radius: var(--lms-radius-lg);
		background: var(--lms-panel);
		color: var(--lms-gray-2);
		box-shadow: 0 1.5rem 3rem -1rem rgb(0 0 0 / 0.6);
	}
	dialog::backdrop {
		background: rgb(8 12 20 / 0.65);
	}
	h2 {
		font-size: 1.3rem;
	}
	p {
		margin-top: 0.75rem;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 1.5rem;
	}
</style>
