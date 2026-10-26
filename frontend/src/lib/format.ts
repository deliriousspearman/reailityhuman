import type { Job, JobState, SingleMachineState } from './types';

/**
 * "45 s", "12 min", "2 h 40 min", "3 d 4 h": the same style as LMS lesson lengths ("1 h 5 min").
 * `short` keeps only the largest unit ("2 h"), for tight spaces like the sidebar.
 */
export function duration(ms: number, short = false): string {
	const s = Math.max(0, Math.round(ms / 1000));
	if (s < 60) return `${s} s`;
	const min = Math.floor(s / 60);
	if (min < 60) return `${min} min`;
	const h = Math.floor(min / 60);
	if (h < 24) return min % 60 && !short ? `${h} h ${min % 60} min` : `${h} h`;
	const d = Math.floor(h / 24);
	return h % 24 && !short ? `${d} d ${h % 24} h` : `${d} d`;
}

export function ago(at: number, now: number): string {
	return now - at < 60_000 ? 'just now' : `${duration(now - at)} ago`;
}

/** "14:05" today, otherwise "Tue 14:05". */
export function clock(at: number, now = Date.now()): string {
	const d = new Date(at);
	const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
	return new Date(now).toDateString() === d.toDateString()
		? time
		: `${d.toLocaleDateString([], { weekday: 'short' })} ${time}`;
}

export function logTime(at: number): string {
	return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

/** Tone for a state: `up` (lime), `busy` (blue, animated), `warn`, `down` (grey), `error` (red). */
export type Tone = 'up' | 'busy' | 'warn' | 'down' | 'error';

export const singleMachineStates: Record<SingleMachineState, { label: string; tone: Tone }> = {
	deploying: { label: 'Starting', tone: 'busy' },
	rebooting: { label: 'Rebooting', tone: 'busy' },
	running: { label: 'Running', tone: 'up' },
	stopping: { label: 'Stopping', tone: 'busy' },
	stopped: { label: 'Stopped', tone: 'down' },
	resetting: { label: 'Resetting', tone: 'busy' },
	expired: { label: 'Expired', tone: 'warn' },
	destroying: { label: 'Destroying', tone: 'busy' },
	error: { label: 'Error', tone: 'error' },
};

export const jobStates: Record<JobState, { label: string; tone: Tone }> = {
	queued: { label: 'Queued', tone: 'down' },
	running: { label: 'Running', tone: 'busy' },
	done: { label: 'Done', tone: 'up' },
	failed: { label: 'Failed', tone: 'error' },
};

/** How long a job took, "…" while it runs, or how long it has been waiting in the queue. */
export function tookLabel(job: Job, now: number): string {
	if (job.startedAt === null) return `waiting ${duration(now - job.queuedAt)}`;
	return job.finishedAt ? duration(job.finishedAt - job.startedAt) : '…';
}

/** "a day", "3 days", "12 hours", "90 min": a period in a sentence, e.g. the grace period. */
export function inWords(ms: number): string {
	const min = Math.round(ms / 60_000);
	if (min % 1440 === 0) return min === 1440 ? 'a day' : `${min / 1440} days`;
	if (min % 60 === 0) return min === 60 ? 'an hour' : `${min / 60} hours`;
	return duration(ms);
}

/** States a machine rests in; in any other, a job is working on it and actions must wait. As the
 * API's STABLE_STATES (backend/app/models.py). */
const STABLE: SingleMachineState[] = ['running', 'stopped', 'expired', 'error'];

export function isBusy(state: SingleMachineState): boolean {
	return !STABLE.includes(state);
}

/** "2 h", "1 d", "3 d" for the duration choices. */
export function hoursLabel(hours: number): string {
	return hours < 24 ? `${hours} h` : `${hours / 24} d`;
}
