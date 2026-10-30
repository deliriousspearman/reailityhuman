// Packet captures (backend/app/capture.py): building filters from what people pick, and showing sizes.
// The panel always limits a capture to its machines' MAC addresses; these only narrow it further.

/** Quick filters for what labs usually carry, ANDed with the hosts or subnet. */
export const presets: { id: string; label: string; filter: string }[] = [
	{ id: 'icmp', label: 'ICMP', filter: 'icmp or icmp6' },
	{ id: 'arp', label: 'ARP', filter: 'arp' },
	{ id: 'dns', label: 'DNS', filter: 'port 53' },
	{ id: 'http', label: 'HTTP', filter: 'tcp port 80 or tcp port 8080' },
	{ id: 'tls', label: 'TLS', filter: 'tcp port 443' },
	{ id: 'ssh', label: 'SSH', filter: 'tcp port 22' },
	{ id: 'smb', label: 'SMB', filter: 'tcp port 445 or tcp port 139' },
	{ id: 'kerberos', label: 'Kerberos', filter: 'port 88 or port 464' },
	{ id: 'ldap', label: 'LDAP', filter: 'port 389 or port 636 or tcp port 3268 or tcp port 3269' },
	{ id: 'rdp', label: 'RDP', filter: 'tcp port 3389' },
];

export type CaptureMode = 'hosts' | 'subnet' | 'custom';

/** Traffic between these addresses: one host's, two hosts' with each other, or any of a few among
 * themselves. */
export function hostsFilter(ips: string[]): string {
	const list = [...new Set(ips.filter(Boolean))];
	if (list.length === 0) return '';
	if (list.length === 1) return `host ${list[0]}`;
	if (list.length === 2) return `host ${list[0]} and host ${list[1]}`;
	const any = (dir: string) => list.map((ip) => `${dir} host ${ip}`).join(' or ');
	return `(${any('src')}) and (${any('dst')})`;
}

/** The /24 an address is in, as a starting point for the subnet. */
export function subnetOf(ip: string): string {
	const parts = ip.split('.');
	return parts.length === 4 ? `${parts.slice(0, 3).join('.')}.0/24` : '';
}

const CIDR = /^(\d{1,3}\.){3}\d{1,3}\/(\d|[12]\d|3[0-2])$/;
export const validSubnet = (cidr: string) => CIDR.test(cidr.trim()) && cidr.split('/')[0].split('.').every((o) => Number(o) <= 255);

/** Joins parts with "and", bracketing any that has an "or" of its own. */
export function allOf(...parts: string[]): string {
	const list = parts.map((p) => p.trim()).filter(Boolean);
	return list.map((p) => (list.length > 1 && /\bor\b/.test(p) && !(p.startsWith('(') && p.endsWith(')')) ? `(${p})` : p)).join(' and ');
}

export function size(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
	if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
	return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

/** How long a capture may run: these choices, up to the panel's limit. */
export function durations(maxSeconds: number): { seconds: number; label: string }[] {
	return [30, 60, 120, 300, 600, 900, 1800]
		.filter((s) => s <= maxSeconds)
		.map((s) => ({ seconds: s, label: s < 60 ? `${s} seconds` : `${s / 60} minute${s === 60 ? '' : 's'}` }));
}

export function liveUrl(id: string): string {
	return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/captures/${id}/live`;
}
