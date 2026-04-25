import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("truckdash", {
  getConfig: (): Promise<{ config: unknown; wsUrl: string }> =>
    ipcRenderer.invoke("truckdash:get-config"),
});
