import { app, BrowserWindow, ipcMain } from "electron";
import * as fs from "node:fs";
import * as path from "node:path";
import * as toml from "smol-toml";

const CONFIG_PATH =
  process.env.TRUCKDASH_GAUGES_CONFIG ||
  "/opt/truckdash/config/gauges.toml";

const WS_URL =
  process.env.TRUCKDASH_OBD2_WS ||
  "ws://127.0.0.1:8765";

function loadGaugesConfig(): Record<string, unknown> {
  try {
    const text = fs.readFileSync(CONFIG_PATH, "utf-8");
    return toml.parse(text) as Record<string, unknown>;
  } catch (err) {
    console.error("[overlay] failed to load gauges.toml:", err);
    return {
      overlay: { position: "top-right", opacity: 0.85, render_hz: 10, margin_px: 16, background: "rgba(0,0,0,0.5)" },
      gauges: [],
    };
  }
}

let mainWindow: BrowserWindow | null = null;

// TRUCKDASH_OVERLAY_DEV=1 gives a normal framed window on the dev box so
// we can actually see the gauges while iterating. In production on the Pi
// this is unset and the window is the real transparent always-on-top
// overlay that stacks over CarPlay.
const DEV_MODE = process.env.TRUCKDASH_OVERLAY_DEV === "1";

function createWindow(): void {
  mainWindow = new BrowserWindow(
    DEV_MODE
      ? {
          width: 800,
          height: 600,
          title: "TruckDash overlay (dev)",
          backgroundColor: "#222",
          webPreferences: {
            preload: path.join(__dirname, "preload.js"),
            contextIsolation: true,
            nodeIntegration: false,
          },
        }
      : {
          fullscreen: true,
          frame: false,
          transparent: true,
          backgroundColor: "#00000000",
          hasShadow: false,
          alwaysOnTop: true,
          skipTaskbar: true,
          focusable: false,
          webPreferences: {
            preload: path.join(__dirname, "preload.js"),
            contextIsolation: true,
            nodeIntegration: false,
          },
        },
  );

  if (!DEV_MODE) {
    // Pass all pointer events through to whatever's below. The gauges are
    // read-only in Phase 2 so this is the right default. When tappable
    // elements are added later, flip to setIgnoreMouseEvents(false) via IPC
    // on pointerenter / back to (true, {forward:true}) on pointerleave.
    mainWindow.setIgnoreMouseEvents(true, { forward: true });
  }

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    mainWindow.loadURL(devUrl);
    if (DEV_MODE) mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("truckdash:get-config", () => ({
  config: loadGaugesConfig(),
  wsUrl: WS_URL,
}));

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => app.quit());
