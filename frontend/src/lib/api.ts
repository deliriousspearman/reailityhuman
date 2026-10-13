// Calls to the panel's API (backend/app/api.py), served under /api by the same host. Errors carry
// the API's message (its `detail`), written to be shown to people as it is.

export class ApiError extends Error {
	constructor(
		message: string,
		readonly status: number,
	) {
		super(message);
	}
}

/** Who's using the panel (no sign-in yet: the name they typed), sent so jobs record who did what. */
let actor = '';
export function setActor(name: string) {
	actor = name;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
	let res: Response;
	try {
		res = await fetch(`/api${path}`, {
			method: init.method ?? 'GET',
			headers: {
				...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
				...(actor ? { 'X-Lab-User': actor } : {}),
			},
			body: init.body === undefined ? undefined : JSON.stringify(init.body),
		});
	} catch {
		throw new ApiError("Can't reach the panel's server. Check your connection and try again.", 0);
	}
	if (!res.ok) {
		let message = `The server answered ${res.status}.`;
		try {
			const body = await res.json();
			if (typeof body.detail === 'string') message = body.detail;
			else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ');
		} catch {}
		throw new ApiError(message, res.status);
	}
	return res.json() as Promise<T>;
}
