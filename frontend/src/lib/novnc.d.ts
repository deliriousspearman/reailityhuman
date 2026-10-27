// The parts of noVNC's RFB class (docs/API.md in @novnc/novnc) the console page uses; the package
// has no types of its own.
declare module '@novnc/novnc' {
	export default class RFB extends EventTarget {
		constructor(target: HTMLElement, url: string, options?: { wsProtocols?: string[] });
		scaleViewport: boolean;
		clipViewport: boolean;
		background: string;
		focusOnClick: boolean;
		disconnect(): void;
		sendCtrlAltDel(): void;
		sendKey(keysym: number, code: string | null, down?: boolean): void;
		focus(): void;
	}
}
