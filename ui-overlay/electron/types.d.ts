// Shared types the renderer sees on `window.truckdash`.

import type { GaugesConfig } from "../src/types";

declare global {
  interface Window {
    truckdash: {
      getConfig(): Promise<{ config: GaugesConfig; wsUrl: string }>;
    };
  }
}

export {};
