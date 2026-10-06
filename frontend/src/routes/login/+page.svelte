<script lang="ts">
	import { goto } from '$app/navigation';

	// Mock sign-in: any details go straight to the catalogue.
	function signIn(event: SubmitEvent) {
		event.preventDefault();
		goto('/');
	}
</script>

<svelte:head><title>Sign in · Codex Labs</title></svelte:head>

<div class="login">
	<form class="panel" onsubmit={signIn}>
		<p class="site-title">Codex Labs</p>
		<h1>Sign in</h1>
		<div class="field">
			<label for="username">Username</label>
			<input id="username" class="input" autocomplete="username" required />
		</div>
		<div class="field">
			<label for="password">Password</label>
			<input id="password" class="input" type="password" autocomplete="current-password" required />
		</div>
		<button class="btn btn-primary" type="submit">Sign in</button>
		<p class="note">No account? Ask your instructor for one.</p>
	</form>
</div>

<style>
	.login {
		display: grid;
		place-items: center;
		min-height: 100dvh;
		padding: 1rem;
		background:
			radial-gradient(circle, color-mix(in srgb, var(--lms-gray-4) 30%, transparent) 1px, transparent 1.2px) 0 0 / 18px 18px,
			var(--lms-black);
	}
	form {
		display: grid;
		gap: 1.1rem;
		width: min(24rem, 100%);
		padding: 2rem 1.75rem;
		border-top: 3px solid var(--lms-lime);
	}
	.site-title {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font: 700 1.2rem var(--lms-display);
		color: var(--lms-white);
	}
	.site-title::before {
		content: '>_';
		display: grid;
		place-items: center;
		width: 1.8rem;
		height: 1.8rem;
		border-radius: var(--lms-radius-sm);
		background: var(--lms-lime);
		color: var(--lms-on-lime);
		font: 700 0.75rem var(--lms-mono);
	}
	h1 {
		font-size: 1.75rem;
	}
	.note {
		font-size: 0.85rem;
		color: var(--lms-gray-3);
	}
</style>
