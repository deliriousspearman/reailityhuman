// Lab definitions, matching the LMS pages lms/src/content/docs/labs/<slug>.md (same slug, title,
// description, machines and picture). Network ranges: public-looking addresses use documentation
// ranges (RFC 5737), internal ones use private ranges, as the LMS conventions require.
import type { Lab } from '../types';

export const labs: Lab[] = [
	{
		slug: 'meridian',
		title: 'Meridian',
		description:
			"Break in through Meridian Logistics' public web portal, pivot out of the DMZ and take over their Active Directory domain.",
		image: '/images/labs/meridian.svg',
		level: 'Advanced',
		environment: 'domain',
		domain: 'meridian.example',
		networks: [
			{ name: 'DMZ', cidr: '198.51.100.0/24', entry: true },
			{ name: 'Internal', cidr: '10.20.10.0/24' },
		],
		machines: [
			{
				name: 'WEB01',
				os: 'Linux',
				role: 'Public web portal',
				nics: [
					{ network: 'DMZ', ip: '198.51.100.10' },
					{ network: 'Internal', ip: '10.20.10.5' },
				],
				bootOrder: 3,
			},
			{ name: 'MAIL01', os: 'Linux', role: 'Mail relay', nics: [{ network: 'DMZ', ip: '198.51.100.25' }], bootOrder: 3 },
			{
				name: 'DC01',
				os: 'Windows',
				role: 'Domain controller',
				nics: [{ network: 'Internal', ip: '10.20.10.10' }],
				domainJoined: true,
				bootOrder: 1,
			},
			{
				name: 'CA01',
				os: 'Windows',
				role: 'Certificate authority (AD CS)',
				nics: [{ network: 'Internal', ip: '10.20.10.11' }],
				domainJoined: true,
				bootOrder: 2,
			},
			{
				name: 'SQL01',
				os: 'Windows',
				role: 'Database server',
				nics: [{ network: 'Internal', ip: '10.20.10.20' }],
				domainJoined: true,
				bootOrder: 2,
			},
			{
				name: 'FS01',
				os: 'Windows',
				role: 'File server',
				nics: [{ network: 'Internal', ip: '10.20.10.30' }],
				domainJoined: true,
				bootOrder: 2,
			},
			{
				name: 'WS01',
				os: 'Windows',
				role: 'Staff workstation',
				nics: [{ network: 'Internal', ip: '10.20.10.101' }],
				domainJoined: true,
				bootOrder: 3,
			},
		],
		resources: { cpu: 18, memoryGB: 40, diskGB: 180 },
		templateVersion: 'v3',
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
