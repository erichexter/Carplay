import { app, BrowserWindow, ipcMain, screen } from "electron";
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

// Width of the gauge strip in production. Wide enough for a 3-digit large
// gauge value (RPM peaks around 3300, speed sub-100). Bumping the gauge
// font sizes? Bump this too.
const PANEL_W = 360;

function createWindow(): void {
  let prodOpts: Electron.BrowserWindowConstructorOptions | null = null;

  if (!DEV_MODE) {
    // Size the overlay to a vertical strip on the right edge instead of
    // fullscreen. setIgnoreMouseEvents is unreliable on labwc/Wayland —
    // labwc doesn't honor wl_surface.set_input_region for non-layer-shell
    // surfaces, so a fullscreen overlay swallows every click meant for
    // CarPlay underneath. A right-strip window means only the gauge area
    // is dead to clicks, and the rest of the screen passes through
    // naturally. Phase 5's compositor work replaces this with a real
    // wlr-layer-shell surface; until then this is the workaround.
    // TODO: respect cfg.overlay.position to pick the corner; right now we
    // assume top-right which is what config/gauges.toml ships with.
    const { width: scrW, height: scrH } = screen.getPrimaryDisplay().workAreaSize;
    prodOpts = {
      x: scrW - PANEL_W,
      y: 0,
      width: PANEL_W,
      height: scrH,
      title: "TruckDash overlay",
      show: false,
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
    };
  }

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
      : prodOpts!,
  );

  if (!DEV_MODE) {
    // Defense in depth — if the strip ever covers a clickable region, the
    // gauges are read-only so we still want clicks to fall through. Drops
    // through on X11; on labwc/Wayland support is patchy but this is a
    // no-op when unsupported.
    mainWindow.setIgnoreMouseEvents(true);

    // 'screen-saver' is Electron's stickiest alwaysOnTop level. Without
    // this, labwc raises whichever window the user just focused (CarPlay)
    // above us — clicking the CarPlay UI hides the overlay. Combined with
    // the moveTop() poll below, this keeps the gauges visible.
    mainWindow.setAlwaysOnTop(true, "screen-saver");

    // Wayland (xdg-shell) doesn't let clients position their own
    // surfaces — the constructor x/y are X11-era hints labwc may ignore
    // (we've been seeing the window land centered). setBounds() after
    // map sometimes wins where the constructor doesn't, because it's a
    // configure_request from the client; labwc honors it more often.
    // If this still doesn't anchor reliably, the durable fix is a
    // labwc windowRule keyed on title="TruckDash overlay".
    const { width: scrW, height: scrH } = screen.getPrimaryDisplay().workAreaSize;
    mainWindow.once("ready-to-show", () => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      mainWindow.setBounds({ x: scrW - PANEL_W, y: 0, width: PANEL_W, height: scrH });
      mainWindow.show();
    });

    // Backstop: even at level=screen-saver, labwc occasionally restacks on
    // focus events. A 1Hz moveTop() costs nothing and pulls us back to the
    // top within a second of any z-order disturbance. Phase 5's
    // wlr-layer-shell migration deletes this whole dance.
    setInterval(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.moveTop();
    }, 1000);
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
