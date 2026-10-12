import { redirect } from '@sveltejs/kit';

// Machines are what works so far; Pro Labs are at /labs, coming soon.
export function load() {
	redirect(307, '/machines');
}
