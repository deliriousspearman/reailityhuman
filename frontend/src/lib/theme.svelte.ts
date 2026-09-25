// Light/dark/auto theme, like the LMS's Starlight selector. The choice is saved per browser; app.html
// applies it before the first paint.
export type ThemeChoice = 'auto' | 'dark' | 'light';

const KEY = 'labs-theme';

function saved(): ThemeChoice {
	try {
		const value = localStorage.getItem(KEY);
		return value === 'dark' || value === 'light' ? value : 'auto';
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

	set(choice: ThemeChoice) {
		this.choice = choice;
		try {
			if (choice === 'auto') localStorage.removeItem(KEY);
			else localStorage.setItem(KEY, choice);
		} catch {}
		this.#apply();
	}

	#apply() {
		const dark = matchMedia('(prefers-color-scheme: dark)').matches;
		document.documentElement.dataset.theme = this.choice === 'auto' ? (dark ? 'dark' : 'light') : this.choice;
	}
}

export const theme = new Theme();
