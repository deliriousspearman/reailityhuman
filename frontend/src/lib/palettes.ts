// The colour themes in the header's theme menu, as on the course site (docu-codex:
// src/lib/palettes.ts). Hacklab Night and Hacklab Day are this panel's own dark and light
// (styles/tokens.css); every other palette sets the same tokens over a dark or light base
// (styles/palettes.css). A new one: add it here, its block to palettes.css, and to app.html's list
// of light palettes if it's light.

export type Base = 'dark' | 'light';
export type Palette = { id: string; label: string; base: Base };

/** In menu order: the panel's own two, then the others, darks first. */
export const PALETTES: readonly Palette[] = [
	{ id: 'dark', label: 'Hacklab Night', base: 'dark' },
	{ id: 'light', label: 'Hacklab Day', base: 'light' },
	{ id: 'dracula', label: 'Dracula', base: 'dark' },
	{ id: 'mocha', label: 'Catppuccin Mocha', base: 'dark' },
	{ id: 'tokyo', label: 'Tokyo Night', base: 'dark' },
	{ id: 'nord', label: 'Nord', base: 'dark' },
	{ id: 'gruvbox', label: 'Gruvbox Dark', base: 'dark' },
	{ id: 'onedark', label: 'One Dark', base: 'dark' },
	{ id: 'solardark', label: 'Solarized Dark', base: 'dark' },
	{ id: 'contrast', label: 'High Contrast', base: 'dark' },
	{ id: 'latte', label: 'Catppuccin Latte', base: 'light' },
	{ id: 'solarlight', label: 'Solarized Light', base: 'light' },
];

export function paletteById(id: string): Palette | undefined {
	return PALETTES.find((palette) => palette.id === id);
}
