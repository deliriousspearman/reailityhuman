// The colour theme: "auto" (the system's light or dark, as Hacklab Day or Night) or one of the
// palettes in palettes.ts. The choice is saved per browser; app.html applies it before the first
// paint. <html> gets data-theme (the palette's light or dark base, which light and dark rules key on)
// and, for palettes other than the panel's own two, data-palette (styles/palettes.css).
import { paletteById } from './palettes';

export type ThemeChoice = 'auto' | string;

const KEY = 'labs-theme';

function saved(): ThemeChoice {
	try {
		const value = localStorage.getItem(KEY);
		return value && paletteById(value) ? value : 'auto';
	} catch {
		return 'auto';
	}
}

class Theme {
	choice = $state<ThemeChoice>(typeof window === 'undefined' ? 'auto' : saved());

	constructor() {
		if (typeof window === 'undefined') return;
		matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => this.#apply());
	}

	/** The base showing: what the icon and anything else light/dark goes by. */
	get base(): 'dark' | 'light' {
		const palette = paletteById(this.choice);
		if (palette) return palette.base;
		return typeof window !== 'undefined' && !matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark';
	}

	set(choice: ThemeChoice) {
		this.choice = paletteById(choice) ? choice : 'auto';
		try {
			if (this.choice === 'auto') localStorage.removeItem(KEY);
			else localStorage.setItem(KEY, this.choice);
		} catch {}
		this.#apply();
	}

	#apply() {
		const root = document.documentElement;
		root.dataset.theme = this.base;
		if (this.choice !== 'auto' && this.choice !== 'dark' && this.choice !== 'light') root.dataset.palette = this.choice;
		else delete root.dataset.palette;
	}
}

export const theme = new Theme();
