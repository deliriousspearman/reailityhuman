import type { InstanceState, MachineState } from './types';

/** "45 s", "12 min", "2 h 40 min", "3 d 4 h": the same style as LMS lesson lengths ("1 h 5 min"). */
export function duration(ms: number): string {
	const s = Math.max(0, Math.round(ms / 1000));
	if (s < 60) return `${s} s`;
	const min = Math.floor(s / 60);
	if (min < 60) return `${min} min`;
	const h = Math.floor(min / 60);
	if (h < 24) return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
	const d = Math.floor(h / 24);
	return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
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

export const machineStates: Record<MachineState, { label: string; tone: Tone }> = {
	running: { label: 'Running', tone: 'up' },
	booting: { label: 'Starting', tone: 'busy' },
	resetting: { label: 'Resetting', tone: 'busy' },
	stopped: { label: 'Off', tone: 'down' },
	error: { label: 'Not responding', tone: 'error' },
};

export const instanceStates: Record<InstanceState, { label: string; tone: Tone }> = {
	running: { label: 'Running', tone: 'up' },
	deploying: { label: 'Starting', tone: 'busy' },
	resetting: { label: 'Resetting', tone: 'busy' },
	stopping: { label: 'Stopping', tone: 'busy' },
	stopped: { label: 'Stopped', tone: 'down' },
	destroying: { label: 'Destroying', tone: 'busy' },
	error: { label: 'Error', tone: 'error' },
};
