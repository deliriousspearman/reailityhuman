// Single-machine templates: the operating systems and appliances people can deploy on their own.
// Only the versions the API lists in /api/config (backend/templates.yaml) can be deployed yet; the
// rest show as "coming soon".
// Version numbers are the ones to build first; confirm each against its vendor when the template is
// made (end-of-life marks as of September 2026).
// Each version is a vSphere template with a 'clean' snapshot. Resource figures are what one copy
// reserves. Default credentials are the vendor's or the template builder's, shown so people can
// sign in the first time.
import type { MachineTemplate } from './types';

export const templates: MachineTemplate[] = [
	// Firewalls and routers
	{
		id: 'pfsense',
		name: 'pfSense CE',
		category: 'Firewalls and routers',
		os: 'FreeBSD',
		description: 'Firewall and router. Put it in front of your other machines to practise rules, NAT and VPNs.',
		versions: [{ version: '2.8.0' }, { version: '2.7.2' }],
		resources: { cpu: 2, memoryGB: 2, diskGB: 16 },
		access: ['web', 'ssh', 'console'],
		credentials: 'admin / pfsense',
	},
	{
		id: 'opnsense',
		name: 'OPNsense',
		category: 'Firewalls and routers',
		os: 'FreeBSD',
		description: 'Firewall and router forked from pfSense, with a newer web interface and a REST API.',
		versions: [{ version: '26.7' }],
		resources: { cpu: 2, memoryGB: 2, diskGB: 20 },
		access: ['web', 'ssh', 'console'],
		webUrl: 'https://{ip}/',
		credentials: 'root / set on first deploy',
	},
	{
		id: 'vyos',
		name: 'VyOS',
		category: 'Firewalls and routers',
		os: 'Linux',
		description: 'Command-line router: routing protocols, VPNs and firewalling configured like network gear.',
		versions: [{ version: '1.5 rolling' }],
		resources: { cpu: 2, memoryGB: 1, diskGB: 10 },
		access: ['ssh', 'console'],
		credentials: 'vyos / set on first deploy',
	},

	// Linux
	{
		id: 'ubuntu',
		name: 'Ubuntu Server',
		category: 'Linux',
		os: 'Linux',
		description: 'Ubuntu LTS releases, minimal server install with OpenSSH.',
		versions: [
			{ version: '26.04' },
			{ version: '24.04' },
			{ version: '22.04' },
			{ version: '20.04', eol: true },
			{ version: '18.04', eol: true },
			{ version: '16.04', eol: true },
		],
		resources: { cpu: 2, memoryGB: 2, diskGB: 20 },
		access: ['ssh', 'console'],
		credentials: 'ubuntu / a password made for each machine',
	},
	{
		id: 'debian',
		name: 'Debian',
		category: 'Linux',
		os: 'Linux',
		description: 'Debian stable releases, minimal install with OpenSSH.',
		versions: [
			{ version: '13' },
			{ version: '12' },
			{ version: '11', eol: true },
			{ version: '10', eol: true },
			{ version: '9', eol: true },
			{ version: '8', eol: true },
		],
		resources: { cpu: 1, memoryGB: 2, diskGB: 20 },
		access: ['ssh', 'console'],
		credentials: 'labuser / set on first deploy',
	},
	{
		id: 'centos',
		name: 'CentOS',
		category: 'Linux',
		os: 'Linux',
		description: 'Red Hat-style Linux. 6 to 8 are end of life; 9 is CentOS Stream.',
		versions: [{ version: 'Stream 9' }, { version: '8', eol: true }, { version: '7', eol: true }, { version: '6', eol: true }],
		resources: { cpu: 2, memoryGB: 2, diskGB: 20 },
		access: ['ssh', 'console'],
		credentials: 'labuser / set on first deploy',
	},

	// Windows
	{
		id: 'windows',
		name: 'Windows',
		category: 'Windows',
		os: 'Windows',
		description: 'Windows desktop editions, not joined to a domain.',
		versions: [{ version: '11' }, { version: '10', eol: true }, { version: '7', eol: true }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 64 },
		access: ['rdp', 'ssh', 'console'],
		credentials: 'labuser / set on first deploy',
		flags: ['licence'],
	},
	{
		id: 'windows-server',
		name: 'Windows Server',
		category: 'Windows Server',
		os: 'Windows',
		description: 'Windows Server with Desktop Experience, or as Server Core (no desktop, half the memory). Add roles yourself.',
		versions: [
			{ version: '2025' },
			{ version: '2025 Core' },
			{ version: '2022' },
			{ version: '2019' },
			{ version: '2016' },
			{ version: '2012 R2', eol: true },
			{ version: '2008 R2', eol: true },
		],
		resources: { cpu: 2, memoryGB: 4, diskGB: 60 },
		access: ['rdp', 'ssh', 'console'],
		credentials: 'labadmin / set on first deploy',
		flags: ['licence'],
	},

	// Hypervisors
	{
		id: 'proxmox',
		name: 'Proxmox VE',
		category: 'Hypervisors',
		os: 'Linux',
		description: 'Open-source hypervisor, running nested so you can create VMs and containers inside it.',
		versions: [{ version: '9' }, { version: '8' }, { version: '7', eol: true }],
		resources: { cpu: 4, memoryGB: 8, diskGB: 64 },
		access: ['web', 'ssh', 'console'],
		webUrl: 'https://{ip}:8006/',
		credentials: 'root / set on first deploy',
		flags: ['nested'],
	},
	{
		id: 'esxi',
		name: 'VMware ESXi',
		category: 'Hypervisors',
		os: 'Other',
		description: "VMware's hypervisor, running nested. Evaluation licence: 60 days from first boot.",
		versions: [{ version: '8.0 U3' }, { version: '7.0 U3', eol: true }, { version: '6.7', eol: true }, { version: '6.5', eol: true }],
		resources: { cpu: 4, memoryGB: 8, diskGB: 64 },
		access: ['web', 'ssh', 'console'],
		credentials: 'root / set on first deploy',
		flags: ['nested', 'licence'],
	},

	// Mail
	{
		id: 'exchange',
		name: 'Microsoft Exchange',
		category: 'Mail',
		os: 'Windows',
		description: 'The mail server behind Outlook. Needs Active Directory, so it comes with its own domain controller (two machines).',
		versions: [{ version: 'SE' }, { version: '2019', eol: true }, { version: '2016', eol: true }],
		resources: { cpu: 6, memoryGB: 20, diskGB: 180 },
		access: ['web', 'rdp', 'console'],
		credentials: 'LAB\\Administrator / set on first deploy',
		flags: ['licence', 'domain'],
	},

	// Storage
	{
		id: 'truenas-scale',
		name: 'TrueNAS SCALE',
		category: 'Storage',
		os: 'Linux',
		description: 'Linux-based NAS with ZFS, SMB/NFS shares and apps. Comes with two extra data disks.',
		versions: [{ version: '25.10' }, { version: '25.04' }],
		resources: { cpu: 2, memoryGB: 8, diskGB: 72 },
		access: ['web', 'ssh', 'console'],
		credentials: 'truenas_admin / set on first deploy',
	},
	{
		id: 'truenas-core',
		name: 'TrueNAS CORE',
		category: 'Storage',
		os: 'FreeBSD',
		description: 'FreeBSD-based NAS with ZFS. In maintenance mode; SCALE is its successor.',
		versions: [{ version: '13.3' }, { version: '13.0', eol: true }],
		resources: { cpu: 2, memoryGB: 8, diskGB: 72 },
		access: ['web', 'ssh', 'console'],
		credentials: 'root / set on first deploy',
	},

	// Security
	{
		id: 'kali',
		name: 'Kali Linux',
		category: 'Security',
		os: 'Linux',
		description: 'Attack box with the usual tools, and a desktop you can reach over RDP.',
		versions: [{ version: '2026.2' }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 60 },
		access: ['ssh', 'rdp', 'console'],
		credentials: 'kali / set on first deploy',
	},
	// Linux: Red Hat rebuilds
	{
		id: 'rocky',
		name: 'Rocky Linux',
		category: 'Linux',
		os: 'Linux',
		description: 'Free rebuild of Red Hat Enterprise Linux, one of the usual replacements for CentOS.',
		versions: [{ version: '10' }, { version: '9' }, { version: '8' }],
		resources: { cpu: 2, memoryGB: 2, diskGB: 20 },
		access: ['ssh', 'console'],
		credentials: 'labuser / set on first deploy',
	},
	{
		id: 'alma',
		name: 'AlmaLinux',
		category: 'Linux',
		os: 'Linux',
		description: 'Free Red Hat Enterprise Linux-compatible distribution, the other common CentOS replacement.',
		versions: [{ version: '10' }, { version: '9' }, { version: '8' }],
		resources: { cpu: 2, memoryGB: 2, diskGB: 20 },
		access: ['ssh', 'console'],
		credentials: 'labuser / set on first deploy',
	},

	// Windows Server: ready-made domain
	{
		id: 'ad-domain',
		name: 'Active Directory domain',
		category: 'Windows Server',
		os: 'Windows',
		description: 'Windows Server already promoted to a domain controller for lab.example, with sample users, groups and OUs.',
		versions: [{ version: '2025' }, { version: '2022' }, { version: '2019' }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 60 },
		access: ['rdp', 'console'],
		credentials: 'LAB\\Administrator / set on first deploy',
		flags: ['licence'],
	},

	// Firewalls and routers
	{
		id: 'mikrotik',
		name: 'MikroTik CHR',
		category: 'Firewalls and routers',
		os: 'Other',
		description: "MikroTik's RouterOS as a virtual router. The free licence caps each interface at 1 Mbit/s.",
		versions: [{ version: '7' }, { version: '6', eol: true }],
		resources: { cpu: 1, memoryGB: 1, diskGB: 1 },
		access: ['web', 'ssh', 'console'],
		webUrl: 'http://{ip}/',
		credentials: 'admin / (no password)',
	},

	// Security
	{
		id: 'parrot',
		name: 'Parrot Security',
		category: 'Security',
		os: 'Linux',
		description: 'Attack box based on Debian, an alternative to Kali, with a desktop over RDP.',
		versions: [{ version: '7' }, { version: '6' }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 40 },
		access: ['ssh', 'rdp', 'console'],
		credentials: 'labuser / set on first deploy',
	},
	{
		id: 'security-onion',
		name: 'Security Onion',
		category: 'Security',
		os: 'Linux',
		description: 'Network security monitoring and log analysis: IDS alerts, packet capture and hunting. Needs a lot of memory.',
		versions: [{ version: '2.4' }],
		resources: { cpu: 4, memoryGB: 12, diskGB: 200 },
		access: ['web', 'ssh', 'console'],
		credentials: 'set on first deploy',
		sshUser: 'labuser',
	},

	// Practice targets: vulnerable on purpose, only ever reachable inside personal networks.
	{
		id: 'metasploitable',
		name: 'Metasploitable',
		category: 'Practice targets',
		os: 'Linux',
		description: 'Deliberately vulnerable Linux server full of weak services. Version 3 is newer, on Ubuntu 14.04.',
		versions: [{ version: '3', eol: true }, { version: '2', eol: true }],
		resources: { cpu: 1, memoryGB: 2, diskGB: 20 },
		access: ['ssh', 'console'],
		credentials: 'msfadmin / msfadmin (2), vagrant / vagrant (3)',
		sshUser: 'msfadmin',
	},
	{
		id: 'metasploitable-windows',
		name: 'Metasploitable 3 (Windows)',
		category: 'Practice targets',
		os: 'Windows',
		description: 'Deliberately vulnerable Windows Server 2008 R2 with outdated services and weak settings.',
		versions: [{ version: '3', eol: true }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 60 },
		access: ['rdp', 'ssh', 'console'],
		credentials: 'vagrant / vagrant',
	},
];

export function findTemplate(id: string): MachineTemplate | undefined {
	return templates.find((t) => t.id === id);
}

/** A machine's template, or a plain stand-in when the catalogue no longer has it (renamed or
 * removed), so machines deployed from it can still be seen and controlled. */
export function templateFor(id: string): MachineTemplate {
	return (
		findTemplate(id) ?? {
			id,
			name: id,
			category: 'Linux',
			os: 'Other',
			description: '',
			versions: [],
			resources: { cpu: 0, memoryGB: 0, diskGB: 0 },
			access: ['ssh'],
		}
	);
}

/** Categories in the order the catalogue shows them. */
export const categories: MachineTemplate['category'][] = [
	'Firewalls and routers',
	'Linux',
	'Windows',
	'Windows Server',
	'Hypervisors',
	'Mail',
	'Storage',
	'Security',
	'Practice targets',
];

/** What each flag means for the person deploying, in their words. */
export const flagNotes: Record<NonNullable<MachineTemplate['flags']>[number], { label: string; note: string }> = {
	nested: { label: 'Nested', note: 'Runs its own VMs inside this one, so they are slower than normal.' },
	licence: { label: 'Licence', note: 'Uses an evaluation or volume licence that an admin manages.' },
	vtpm: { label: 'vTPM', note: 'Needs a virtual TPM, which the admin must enable in vCenter.' },
	domain: { label: '2 machines', note: 'Comes with its own domain controller, which counts towards your machines.' },
};
