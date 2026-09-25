// Single-machine templates: the operating systems and appliances people can deploy on their own.
// Version numbers are the ones to build first; confirm each against its vendor when the template is
// made (end-of-life marks as of September 2026).
// Each version is a vSphere template with a 'clean' snapshot. Resource figures are what one copy
// reserves. Default credentials are the vendor's or the template builder's, shown so people can
// sign in the first time.
import type { MachineTemplate } from '../types';

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
		versions: [{ version: '26.7' }, { version: '26.1' }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 20 },
		access: ['web', 'ssh', 'console'],
		credentials: 'root / opnsense',
	},
	{
		id: 'vyos',
		name: 'VyOS',
		category: 'Firewalls and routers',
		os: 'Linux',
		description: 'Command-line router: routing protocols, VPNs and firewalling configured like network gear.',
		versions: [{ version: '1.5 rolling' }, { version: '1.4 LTS' }],
		resources: { cpu: 1, memoryGB: 1, diskGB: 8 },
		access: ['ssh', 'console'],
		credentials: 'vyos / vyos',
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
		resources: { cpu: 2, memoryGB: 2, diskGB: 25 },
		access: ['ssh', 'console'],
		credentials: 'labuser / set on first deploy',
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
		access: ['rdp', 'console'],
		credentials: 'labuser / set on first deploy',
		flags: ['licence', 'vtpm'],
	},
	{
		id: 'windows-server',
		name: 'Windows Server',
		category: 'Windows Server',
		os: 'Windows',
		description: 'Windows Server with Desktop Experience. Add roles yourself, or promote it to a domain controller.',
		versions: [{ version: '2022' }, { version: '2016' }, { version: '2012 R2', eol: true }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 60 },
		access: ['rdp', 'console'],
		credentials: 'Administrator / set on first deploy',
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
		webPort: 8006,
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
		id: 'zimbra',
		name: 'Zimbra',
		category: 'Mail',
		os: 'Linux',
		description: 'Mail and collaboration server with webmail, on Ubuntu.',
		versions: [{ version: '10' }, { version: '9' }, { version: '8.8.15', eol: true }],
		resources: { cpu: 4, memoryGB: 8, diskGB: 60 },
		access: ['web', 'ssh', 'console'],
		credentials: 'admin@mail.example / set on first deploy',
	},
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

	// Apps
	{
		id: 'nextcloud',
		name: 'Nextcloud',
		category: 'Apps',
		os: 'Linux',
		description: 'Self-hosted file sharing and collaboration, on Ubuntu with Apache and MariaDB.',
		versions: [{ version: '33' }, { version: '32' }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 40 },
		access: ['web', 'ssh', 'console'],
		credentials: 'admin / set on first deploy',
	},

	// Security
	{
		id: 'kali',
		name: 'Kali Linux',
		category: 'Security',
		os: 'Linux',
		description: 'Attack box with the usual tools, and a desktop you can reach over RDP.',
		versions: [{ version: '2026.2' }, { version: '2026.1' }],
		resources: { cpu: 2, memoryGB: 4, diskGB: 60 },
		access: ['ssh', 'rdp', 'console'],
		credentials: 'kali / kali',
	},
];

export function findTemplate(id: string): MachineTemplate | undefined {
	return templates.find((t) => t.id === id);
}

export const categories = [...new Set(templates.map((t) => t.category))];

/** What each flag means for the person deploying, in their words. */
export const flagNotes: Record<NonNullable<MachineTemplate['flags']>[number], { label: string; note: string }> = {
	nested: { label: 'Nested', note: 'Runs its own VMs inside this one, so they are slower than normal.' },
	licence: { label: 'Licence', note: 'Uses an evaluation or volume licence that an admin manages.' },
	vtpm: { label: 'vTPM', note: 'Needs a virtual TPM (Windows 11), which the admin must enable in vCenter.' },
	domain: { label: '2 machines', note: 'Comes with its own domain controller, which counts towards your machines.' },
};
