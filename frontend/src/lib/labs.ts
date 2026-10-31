// Lab definitions, matching the LMS pages lms/src/content/docs/labs/<slug>.md (same slug, title,
// description, machines and picture). Network ranges: public-looking addresses use documentation
// ranges (RFC 5737), internal ones use private ranges, as the LMS conventions require.
import type { Lab } from './types';

export const labs: Lab[] = [
	{
		slug: 'meridian',
		title: 'Meridian',
		description:
			"Break in through Meridian Logistics' web portal and take over their Active Directory domain — two replicating controllers, a certificate authority, a SQL Server and a workstation, chained through a certificate relay.",
		image: '/images/labs/meridian.svg',
		level: 'Advanced',
		environment: 'domain',
		domain: 'meridian.corp',
		// Flat LAN with DHCP for now; the DMZ/Internal split comes with Networks.
		networks: [{ name: 'LAN', cidr: '198.51.100.0/24', entry: true }],
		machines: [
			{
				name: 'DC01',
				os: 'Windows',
				role: 'First domain controller (with AD CS)',
				nics: [{ network: 'LAN', ip: '198.51.100.10' }],
				domainJoined: true,
				bootOrder: 1,
			},
			{
				name: 'DC02',
				os: 'Windows',
				role: 'Second domain controller (replica)',
				nics: [{ network: 'LAN', ip: '198.51.100.11' }],
				domainJoined: true,
				bootOrder: 2,
			},
			{
				name: 'SQL01',
				os: 'Windows',
				role: 'SQL Server',
				nics: [{ network: 'LAN', ip: '198.51.100.20' }],
				domainJoined: true,
				bootOrder: 3,
			},
			{
				name: 'WS01',
				os: 'Windows',
				role: 'Staff workstation',
				nics: [{ network: 'LAN', ip: '198.51.100.101' }],
				domainJoined: true,
				bootOrder: 3,
			},
			{
				name: 'WEB01',
				os: 'Linux',
				role: 'Public web portal (domain-joined)',
				nics: [{ network: 'LAN', ip: '198.51.100.5' }],
				domainJoined: true,
				bootOrder: 3,
			},
		],
		resources: { cpu: 10, memoryGB: 18, diskGB: 120 },
		templateVersion: 'v4',
		resetScope: 'lab',
		resetSchedule: 'Every night at 02:00',
	},
	{
		slug: 'harbourside',
		title: 'Harbourside',
		description:
			'A small business with no domain, just separate hosts. Find the weak spots in its shop, developer server, backups and office devices, one machine at a time.',
		image: '/images/labs/harbourside.svg',
		level: 'Intermediate',
		environment: 'standalone',
		networks: [
			{ name: 'Perimeter', cidr: '203.0.113.0/24', entry: true },
			{ name: 'Office', cidr: '10.30.20.0/24' },
		],
		machines: [
			{
				name: 'GATE',
				os: 'Linux',
				role: 'Edge router and VPN gateway',
				nics: [
					{ network: 'Perimeter', ip: '203.0.113.1' },
					{ network: 'Office', ip: '10.30.20.1' },
				],
				bootOrder: 1,
			},
			{ name: 'SHOP', os: 'Linux', role: 'Online shop', nics: [{ network: 'Perimeter', ip: '203.0.113.20' }], bootOrder: 2 },
			{
				name: 'DEV',
				os: 'Linux',
				role: 'Developer server (Git and CI)',
				nics: [{ network: 'Office', ip: '10.30.20.15' }],
				bootOrder: 2,
			},
			{ name: 'NAS', os: 'FreeBSD', role: 'Backup storage', nics: [{ network: 'Office', ip: '10.30.20.40' }], bootOrder: 2 },
			{
				name: 'POS01',
				os: 'Windows',
				role: 'Point-of-sale terminal',
				nics: [{ network: 'Office', ip: '10.30.20.60' }],
				bootOrder: 3,
			},
			{ name: 'NVR', os: 'Other', role: 'CCTV video recorder', nics: [{ network: 'Office', ip: '10.30.20.80' }], bootOrder: 3 },
		],
		resources: { cpu: 12, memoryGB: 22, diskGB: 120 },
		templateVersion: 'v5',
		resetScope: 'machine',
		resetSchedule: 'Every night at 02:00',
	},
];

export function findLab(slug: string): Lab | undefined {
	return labs.find((lab) => lab.slug === slug);
}
