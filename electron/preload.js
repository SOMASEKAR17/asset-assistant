const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("caaDesktop", {
  platform: process.platform,
  minimize: () => ipcRenderer.send("win:minimize"),
  toggleMaximize: () => ipcRenderer.send("win:maximize"),
  close: () => ipcRenderer.send("win:close"),
  pickFolder: () => ipcRenderer.invoke("dialog:folder"),
  retry: () => ipcRenderer.invoke("app:retry"),
  openLog: () => ipcRenderer.invoke("app:open-log"),
  onWindowState: (cb) => ipcRenderer.on("win:state", (_e, s) => cb(s)),
});
