import type { IconName } from '$lib/components/Icon.svelte';

export type Section = 'machines' | 'labs' | 'instances' | 'admin';

/** `soon`: not built yet; shown greyed out, and its pages say it's coming. */
export const sections: { id: Section; href: string; label: string; icon: IconName; soon?: boolean }[] = [
	{ id: 'machines', href: '/machines', label: 'Machines', icon: 'console' },
	{ id: 'labs', href: '/labs', label: 'Pro Labs', icon: 'labs' },
	{ id: 'instances', href: '/instances', label: 'Instances', icon: 'instances' },
	{ id: 'admin', href: '/admin', label: 'Admin', icon: 'admin' },
];

// Which section a page belongs to, so detail pages keep their section highlighted.
export function sectionFor(pathname: string): Section {
	if (pathname.startsWith('/machines')) return 'machines';
	if (pathname.startsWith('/instances')) return 'instances';
	if (pathname.startsWith('/admin')) return 'admin';
	if (pathname.startsWith('/labs')) return 'labs';
	return 'machines';
}

// Anchor id for a template category's heading on /machines; the sidebar links to it.
export const categorySlug = (category: string) => `cat-${category.toLowerCase().replace(/\W+/g, '-')}`;

// The admin page's sections, in page order; the sidebar links to them.
export const adminSections = [
	{ id: 'capacity', label: 'Capacity' },
	{ id: 'machines', label: 'Machines' },
	{ id: 'leftovers', label: 'Leftover VMs' },
	{ id: 'jobs', label: 'Jobs' },
	{ id: 'templates', label: 'Templates' },
];
