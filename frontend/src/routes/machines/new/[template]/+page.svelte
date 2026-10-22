<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import OsLogo from '$lib/components/OsLogo.svelte';
	import { clock, hoursLabel, inWords } from '$lib/format';
	import { ApiError } from '$lib/api';
	import { store } from '$lib/store.svelte';
	import { findTemplate, flagNotes } from '$lib/templates';
	import type { Access, Extra, ExtraChoice, ExtraOption } from '$lib/types';

	const template = $derived(findTemplate(page.params.template ?? ''));

	const DURATIONS = [2, 4, 8, 24, 72, 168];
	const accessNames: Record<Access, string> = { ssh: 'SSH', rdp: 'Remote Desktop', web: 'Web interface', console: 'Console' };

	let version = $state('');
	let name = $state('');
	/** Who it's for: remembered from last time, as there's no sign-in yet. */
	let owner = $state(store.user);
	/** Hours to keep it, or 'keep' for permanently. */
	let keep = $state<number | 'keep'>(4);
	let sshKey = $state('');
	/** Blank: the panel generates one. */
	let password = $state('');
	let showPassword = $state(false);
	/** Ticked extras, and what's typed in their options, by extra id. */
	let picked = $state<Record<string, Record<string, string>>>({});
	let submitting = $state(false);
	let failure = $state<string | null>(null);

	// Defaults when the template changes (or the API's list of live versions arrives): its newest
	// version that can be deployed, and a free name like "ubuntu01". Only those are tracked, so later
	// changes to the machine list don't overwrite what you've typed.
	// "Deploy another like this" (?from=<machine id>) starts from that machine's version and extras.
	// Coming from a service (?version=<v>&extra=<id>), that version, with the service ticked.
	$effect(() => {
		const t = template;
		const config = store.config;
		const loaded = store.loaded;
		if (!t) return;
		untrack(() => {
			version = (config && t.versions.find((v) => store.isLive(t.id, v.version))?.version) ?? t.versions[0].version;
			const params = page.url.searchParams;
			const wanted = params.get('version');
			if (wanted && store.isLive(t.id, wanted)) version = wanted;
			const service = store.extrasFor(t.id, version).find((x) => x.id === params.get('extra'));
			if (service) picked = { [service.id]: Object.fromEntries(service.options.map((o) => [o.id, pickedDefault(o)])) };
			const from = loaded ? store.machine(page.url.searchParams.get('from') ?? '') : undefined;
			if (from && from.template === t.id && store.isLive(t.id, from.version)) {
				version = from.version;
				// Options that were left to their default (which names the old machine) stay blank.
				const offeredNow = store.extrasFor(t.id, from.version);
				picked = Object.fromEntries(
					from.extras
						.filter((x) => offeredNow.some((o) => o.id === x.id))
						.map((x) => {
							const extra = offeredNow.find((o) => o.id === x.id)!;
							const options = Object.fromEntries(
								extra.options.map((o) => {
									const v = x.options[o.id] ?? '';
									if (o.type === 'choice' || o.type === 'boolean') return [o.id, v || pickedDefault(o)];
									return [o.id, v === store.optionDefault(o.default, from.name) ? '' : v];
								}),
							);
							return [x.id, options];
						}),
				);
			}
			const base = t.id.split('-')[0];
			const taken = new Set(store.machines.map((m) => m.name));
			let n = 1;
			while (taken.has(`${base}${String(n).padStart(2, '0')}`)) n++;
			name = `${base}${String(n).padStart(2, '0')}`;
		});
	});

	// The API's rules (from /api/config), so mistakes show while typing.
	const nameProblem = $derived(
		!name
			? 'Give it a name.'
			: (store.nameProblem(name) ?? (store.machines.some((m) => m.name === name) ? `There's already a machine called ${name}.` : null)),
	);
	const ownerProblem = $derived(
		!owner.trim() ? 'Add your name, so people can tell whose machine it is.' : store.ownerProblem(owner.trim().toLowerCase()),
	);
	const live = $derived(store.config?.templates.find((t) => t.template === template?.id && t.version === version));
	const username = $derived(live?.username);
	const windows = $derived(live?.family === 'windows');
	// A complete image (Metasploitable): its own sign-in, the same on every machine.
	const fixedPassword = $derived(live?.fixedPassword);
	const passwordMin = $derived(store.config?.rules.passwordMin ?? 8);
	const passwordProblem = $derived(
		!password
			? null
			: password.length < passwordMin
				? `At least ${passwordMin} characters.`
				: /[\t\n\r]/.test(password)
					? 'No line breaks or tabs.'
					: windows
						? store.windowsPasswordProblem(password, username ?? '')
						: null,
	);
	const vmName = $derived(`${owner.trim().toLowerCase() || 'you'}-${name || 'name'}-…`);
	const canKeep = $derived(store.permanentCount < store.permanentQuota);
	const blocker = $derived(
		template ? (store.machineBlocker(template) ?? (store.isLive(template.id, version) ? null : `${version} isn't available yet.`)) : null,
	);
	const deployed = $derived(template && store.asDeployed(template, version));
	const eol = $derived(template?.versions.find((v) => v.version === version)?.eol);

	// Extras --------------------------------------------------------------------------------------------
	const offered = $derived(template ? store.extrasFor(template.id, version) : []);
	// Another version may offer different extras: drop what it doesn't.
	$effect(() => {
		const ids = new Set(offered.map((x) => x.id));
		untrack(() => {
			for (const id of Object.keys(picked)) if (!ids.has(id)) delete picked[id];
		});
	});
	const chosen = $derived(offered.filter((x) => x.id in picked));
	/** How to reach the machine: the template's ways, plus a desktop extra's RDP and VNC. */
	const signInWays = $derived.by(() => {
		const ways = (deployed ?? template)?.access.map((a) => accessNames[a]) ?? [];
		const desktop = chosen.find((x) => x.id === 'desktop');
		const protocol = desktop && picked.desktop?.protocol;
		if (protocol === 'rdp' || protocol === 'both') ways.push('Remote Desktop');
		if (protocol === 'vnc' || protocol === 'both') ways.push('VNC');
		return [...new Set(ways)];
	});

	/** Ports the chosen extras use, for the summary. */
	const chosenPorts = $derived([...new Set(chosen.flatMap((x) => x.ports))].sort((a, b) => a - b));

	/** The machine's memory: the template's, or more where an extra chosen needs more (as the panel gives it). */
	const memoryGB = $derived(Math.max(deployed?.resources.memoryGB ?? 0, ...chosen.map((x) => x.minMemoryGB)));

	/** A note when an extra needs more memory than the template has, or null. */
	function moreMemory(x: Extra): string | null {
		const memory = deployed?.resources.memoryGB ?? 0;
		return x.minMemoryGB > memory ? `Gives the machine ${x.minMemoryGB} GB of memory.` : null;
	}

	// Grouped under their categories, in the catalogue's order. Past FOLD_OVER extras, groups start
	// folded, except those with a ticked extra, so a long list stays easy to scan.
	const FOLD_OVER = 8;
	const groups = $derived.by(() => {
		const out: { category: string; items: Extra[] }[] = [];
		for (const x of offered) {
			let group = out.find((g) => g.category === x.category);
			if (!group) out.push((group = { category: x.category, items: [] }));
			group.items.push(x);
		}
		return out;
	});
	const folded = $derived(offered.length > FOLD_OVER);

	/** Ticking an extra that clashes with ticked ones (they use the same port) replaces them. */
	function toggle(x: Extra, on: boolean) {
		if (on) {
			for (const y of chosen) if (clashes(x, y)) delete picked[y.id];
			picked[x.id] = Object.fromEntries(x.options.map((o) => [o.id, pickedDefault(o)]));
		} else delete picked[x.id];
	}

	/** A ticked extra this one can't be combined with. */
	function clashes(x: Extra, y: Extra): boolean {
		return y.id !== x.id && (x.conflicts.includes(y.id) || y.conflicts.includes(x.id));
	}

	/** What an option starts as when its extra is ticked: blank for text (its default shows as a
	 * placeholder), the default for a choice or a tick box. */
	function pickedDefault(o: ExtraOption): string {
		if (o.type === 'machine') return candidates(o)[0]?.id ?? '';
		return o.type === 'choice' || o.type === 'boolean' ? o.default || (o.type === 'boolean' ? 'no' : '') : '';
	}

	/** The machines a machine option can name: running ones with its extra (e.g. domain controllers). */
	function candidates(o: ExtraOption) {
		return store.machines.filter((m) => m.state === 'running' && m.ip && m.extras.some((x) => x.id === o.extra));
	}

	/** Ticked extras that ticking this one would replace, as "A", "A and B" or "A, B and C". */
	function replacing(x: Extra): string | null {
		const names = chosen.filter((y) => clashes(x, y)).map((y) => y.name);
		if (!names.length) return null;
		return names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
	}

	/** Whether an option applies, given the extra's other options (e.g. a domain only with HTTPS). */
	function shown(o: ExtraOption, values: Record<string, string> | undefined): boolean {
		return Object.entries(o.when ?? {}).every(([k, vs]) => vs.includes(values?.[k] ?? ''));
	}

	function optionProblem(o: ExtraOption, value: string): string | null {
		if (o.type === 'choice' || o.type === 'boolean') return null; // can only be one of its values
		if (o.type === 'machine') {
			if (candidates(o).some((m) => m.id === value)) return null;
			const needed = store.config?.services.find((x) => x.id === o.extra)?.name ?? o.extra;
			return candidates(o).length ? 'Choose one.' : `Deploy a machine with ${needed} first, and wait until it's ready.`;
		}
		const v = value.trim().toLowerCase().replace(/\.$/, '');
		if (!v) return o.required ? `Fill in ${o.label.toLowerCase()}.` : null;
		if (o.type === 'hostname' && (v.length > 253 || !store.matches(store.config?.rules.hostname, v))) {
			return 'Use letters, digits, hyphens and dots, e.g. intranet.lab.example.';
		}
		if (o.type === 'text' && (value.trim().length > 200 || !store.matches(o.pattern && `^(?:${o.pattern})$`, value.trim()))) {
			return `That isn't a valid ${o.label.toLowerCase()}.`;
		}
		return null;
	}
	const extrasProblem = $derived(
		chosen.some((x) => x.options.some((o) => shown(o, picked[x.id]) && optionProblem(o, picked[x.id]?.[o.id] ?? '')))
			? "Fix the extras' settings first."
			: null,
	);

	async function deploy(event: SubmitEvent) {
		event.preventDefault();
		if (!template || nameProblem || ownerProblem || passwordProblem || blocker || extrasProblem || submitting) return;
		submitting = true;
		failure = null;
		const extras: ExtraChoice[] = chosen.map((x) => ({ id: x.id, options: { ...picked[x.id] } }));
		try {
			const m = await store.deployMachine(template, version, name, keep === 'keep' ? null : keep, sshKey, extras, owner, password);
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
		<OsLogo id={template.id} name={template.name} size="lg" />
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

			{#if offered.length}
				<fieldset>
					<legend>Extras <span class="optional">optional</span></legend>
					{#each groups as group (group.category)}
						{@const ticked = group.items.filter((x) => x.id in picked).length}
						<details class="extra-group" open={!folded || ticked > 0}>
							<summary>
								{group.category}
								<span class="group-count">{ticked ? `${ticked} of ${group.items.length} ticked` : group.items.length}</span>
							</summary>
							<ul class="extras">
								{#each group.items as x (x.id)}
									{@const clash = replacing(x)}
									{@const on = x.id in picked}
									{@const more = moreMemory(x)}
									<li class="extra" class:on>
										<label class="extra-head">
											<input type="checkbox" checked={on} onchange={(e) => toggle(x, e.currentTarget.checked)} />
											<span class="extra-name">{x.name}</span>
										</label>
										<p class="extra-desc">
											{x.description}{#if more}{' '}<span class="replaces">{more}</span>{/if}{#if clash && !on}{' '}<span class="replaces">Replaces {clash}: they'd use the same port.</span>{/if}
										</p>
										{#if on}
											{#each x.options.filter((o) => shown(o, picked[x.id])) as o (o.id)}
												{@const problem = optionProblem(o, picked[x.id][o.id] ?? '')}
												{@const fallback = o.type === 'machine' ? '' : store.optionDefault(o.default, name || 'name')}
												{#if o.type === 'boolean'}
													<label class="extra-flag">
														<input
															type="checkbox"
															checked={picked[x.id][o.id] === 'yes'}
															onchange={(e) => (picked[x.id][o.id] = e.currentTarget.checked ? 'yes' : 'no')}
														/>
														<span>{o.label}</span>
														{#if o.help}<span class="hint">{o.help}</span>{/if}
													</label>
												{:else}
													<div class="field extra-option">
														<label for="opt-{x.id}-{o.id}">
															{o.label}{#if !o.required && o.type !== 'choice' && o.type !== 'machine'}<span class="optional">optional</span>{/if}
														</label>
														{#if o.type === 'choice'}
															<select id="opt-{x.id}-{o.id}" class="input" bind:value={picked[x.id][o.id]} aria-describedby="opt-{x.id}-{o.id}-hint">
																{#each o.choices ?? [] as c (c.value)}
																	<option value={c.value}>{c.label}</option>
																{/each}
															</select>
														{:else if o.type === 'machine'}
															<select id="opt-{x.id}-{o.id}" class="input" bind:value={picked[x.id][o.id]} aria-invalid={!!problem} aria-describedby="opt-{x.id}-{o.id}-hint">
																{#each candidates(o) as m (m.id)}
																	<option value={m.id}>{m.name} ({m.ip})</option>
																{:else}
																	<option value="">None running</option>
																{/each}
															</select>
														{:else}
															<input
																id="opt-{x.id}-{o.id}"
																class="input mono-input"
																bind:value={picked[x.id][o.id]}
																placeholder={fallback}
																autocomplete="off"
																spellcheck="false"
																aria-invalid={!!problem}
																aria-describedby="opt-{x.id}-{o.id}-hint"
															/>
														{/if}
														<p id="opt-{x.id}-{o.id}-hint" class="hint" class:problem>
															{#if problem}{problem}{:else}{o.help}{#if fallback && o.type !== 'choice'}{' '}Left blank: <code>{fallback}</code>.{/if}{/if}
														</p>
													</div>
												{/if}
											{/each}
										{/if}
									</li>
								{/each}
							</ul>
						</details>
					{/each}
					<p class="hint">Set up and started on its first boot, without downloading anything. Deploying takes a little longer.</p>
				</fieldset>
			{/if}

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
				<p id="owner-hint" class="hint" class:problem={ownerProblem}>
					{#if ownerProblem}{ownerProblem}{:else}Your name. In vCenter it's called <code>{vmName}</code>; remembered in this browser.{/if}
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
						Powered off at {clock(store.now + keep * 3_600_000, store.now)} and deleted {inWords(store.grace)} later, unless you extend it.
					{/if}
					{#if !canKeep}{store.permanentCount} are kept permanently already, the most allowed.{/if}
				</p>
			</fieldset>

			{#if fixedPassword}
				<div class="field">
					<p class="hint">
						A complete image, deployed as it is: every machine signs in as <code>{username}</code> with the password
						<code>{fixedPassword}</code>. It's deliberately vulnerable, so keep it on the lab network.
					</p>
				</div>
			{:else}
				<div class="field">
					<label for="password">Password <span class="optional">optional</span></label>
					<div class="password-row">
						<input
							id="password"
							class="input mono-input"
							type={showPassword ? 'text' : 'password'}
							bind:value={password}
							autocomplete="new-password"
							spellcheck="false"
							placeholder="Leave blank for a random one"
							aria-invalid={!!passwordProblem}
							aria-describedby="password-hint"
						/>
						<button class="btn btn-quiet btn-sm" type="button" onclick={() => (showPassword = !showPassword)}>
							<Icon name="eye" />{showPassword ? 'Hide' : 'Show'}
						</button>
					</div>
					<p id="password-hint" class="hint" class:problem={passwordProblem}>
						{passwordProblem ??
							`For ${username ?? 'the user'}, ${windows ? 'an administrator. Windows needs three of: capitals, small letters, digits and symbols' : 'and sudo'}. Blank: a random one, shown once it's deployed. Anyone who can open the panel can see it, so don't reuse one you use elsewhere.`}
					</p>
				</div>

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
			{/if}
		</div>

		<aside class="summary panel">
			<h2>Summary</h2>
			<dl>
				<div><dt>Machine</dt><dd>{template.name} {version}</dd></div>
				<div><dt>Owner</dt><dd>{owner.trim().toLowerCase() || '–'}</dd></div>
				<div><dt>Uses</dt><dd>{deployed?.resources.cpu} vCPU, {memoryGB} GB memory, {deployed?.resources.diskGB} GB disk</dd></div>
				<div><dt>Network</dt><dd>The LAN, with an address from DHCP</dd></div>
				<div><dt>Sign in with</dt><dd>{signInWays.join(', ')}</dd></div>
				{#if chosen.length}
					<div><dt>Extras</dt><dd>{chosen.map((x) => x.name).join(', ')}</dd></div>
					{#if chosenPorts.length}
						<div><dt>Ports</dt><dd>{chosenPorts.join(', ')}</dd></div>
					{/if}
				{/if}
				{#if username}
					<div>
						<dt>First sign-in</dt>
						<dd>
							<code>{username}</code>, {fixedPassword
								? `with the image's password, ${fixedPassword}`
								: password
									? 'with your password'
									: "with a password shown once it's deployed"}
						</dd>
					</div>
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
			<button class="btn btn-primary" type="submit" disabled={!!nameProblem || !!ownerProblem || !!passwordProblem || !!blocker || !!extrasProblem || submitting}>
				<Icon name="plus" /> {submitting ? 'Deploying…' : `Deploy ${name || 'machine'}`}
			</button>
			{#if blocker || failure || extrasProblem}<p class="blocker" role="status"><Icon name="alert" /> {failure ?? blocker ?? extrasProblem}</p>{/if}
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
	.password-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	textarea.mono-input {
		resize: vertical;
		min-height: 4.5rem;
		font-size: 0.8rem;
	}
	/* Extras: a tile each, with a real checkbox; the ticked ones get the lime rail. */
	.extras {
		display: grid;
		gap: 0.5rem;
		max-width: 40rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.extra {
		padding: 0.65rem 0.85rem;
		border: var(--lms-border-width) solid var(--lms-gray-5);
		border-radius: var(--lms-radius-sm);
		background: var(--lms-panel);
	}
	.extra-group + .extra-group {
		margin-top: 0.75rem;
	}
	.extra-group summary {
		list-style: none;
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		margin-bottom: 0.5rem;
		font: 600 0.8rem var(--lms-font);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--lms-gray-2);
		cursor: pointer;
	}
	.extra-group summary::-webkit-details-marker {
		display: none;
	}
	.extra-group summary::before {
		content: '▸';
		display: inline-block;
		width: 0.8rem;
		transition: transform 0.15s ease;
	}
	.extra-group[open] summary::before {
		transform: rotate(90deg);
	}
	.extra-group summary:hover {
		color: var(--lms-white);
	}
	.group-count {
		font-weight: 400;
		letter-spacing: 0;
		text-transform: none;
		color: var(--lms-gray-3);
	}
	.extra.on {
		border-color: var(--lms-lime);
		box-shadow: inset 3px 0 0 var(--lms-lime);
	}
	.extra-head {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		cursor: pointer;
	}
	.extra-head input {
		width: 1rem;
		height: 1rem;
		accent-color: var(--lms-lime);
	}
	.extra-name {
		font: 600 0.95rem var(--lms-mono);
		color: var(--lms-white);
	}
	.extra-desc {
		margin: 0.25rem 0 0 1.6rem;
		font-size: 0.85rem;
		color: var(--lms-gray-2);
	}
	.extra-flag {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem 0.6rem;
		margin: 0.6rem 0 0 1.6rem;
		font-size: 0.9rem;
		cursor: pointer;
	}
	.extra-flag input {
		accent-color: var(--lms-lime);
	}
	.extra-flag .hint {
		flex-basis: 100%;
	}
	.replaces {
		color: var(--lms-gray-3);
	}
	.extra-option {
		margin: 0.75rem 0 0.15rem 1.6rem;
	}
	.extra-option label {
		display: block;
		margin-bottom: 0.35rem;
		font: 600 0.9rem var(--lms-display);
	}
	.hint code {
		color: var(--lms-lime-text);
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
