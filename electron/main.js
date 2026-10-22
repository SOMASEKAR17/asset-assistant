const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const PACKED = app.isPackaged;
const RES = PACKED ? process.resourcesPath : ROOT;
const HINT = PACKED ? "Reinstall Creator Asset Assistant." : "Run scripts\\setup.ps1 first.";
const DEFAULT_PORT = 8765;
let win = null;
let engine = null;
let quitting = false;
let logPath = "";

function pythonExe() {
  if (process.env.CAA_PYTHON) return process.env.CAA_PYTHON;
  if (PACKED) {
    const bundled = path.join(RES, "python", process.platform === "win32" ? "python.exe" : path.join("bin", "python3"));
    if (fs.existsSync(bundled)) return bundled;
  }
  const winPy = path.join(ROOT, ".venv", "Scripts", "python.exe");
  const posixPy = path.join(ROOT, ".venv", "bin", "python");
  if (process.platform === "win32" && fs.existsSync(winPy)) return winPy;
  if (fs.existsSync(posixPy)) return posixPy;
  return process.platform === "win32" ? "python" : "python3";
}

function getJSON(url, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try {
          resolve(res.statusCode === 200 ? JSON.parse(body) : null);
        } catch {
          resolve(null);
        }
      });
    });
    req.on("timeout", () => {
      req.destroy();
      resolve(null);
    });
    req.on("error", () => resolve(null));
  });
}

function portFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.once("listening", () => srv.close(() => resolve(true)));
    srv.listen(port, "127.0.0.1");
  });
}

async function pickPort() {
  for (let p = DEFAULT_PORT; p < DEFAULT_PORT + 20; p++) {
    if (await portFree(p)) return p;
  }
  throw new Error("No free port between 8765 and 8784");
}

async function runningEngine() {
  const st = await getJSON(`http://127.0.0.1:${DEFAULT_PORT}/api/status`);
  return st && st.version ? DEFAULT_PORT : null;
}

function showSplash(params = {}) {
  if (!win || win.isDestroyed()) return;
  win.loadFile(path.join(__dirname, "splash.html"), { query: PACKED ? { ...params, packaged: "1" } : params });
}

function fail(message) {
  showSplash({ error: message, log: logPath });
}

function startEngine(port) {
  logPath = path.join(app.getPath("userData"), "engine.log");
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const log = fs.createWriteStream(logPath, { flags: "a" });
  log.write(`\n--- ${new Date().toISOString()} starting engine on port ${port} with ${pythonExe()}\n`);
  const env = { ...process.env, PYTHONPATH: path.join(RES, "engine"), PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" };
  if (PACKED) {
    env.PYTHONNOUSERSITE = "1";
    delete env.PYTHONHOME;
  }
  engine = spawn(pythonExe(), ["-m", "caa", "serve", "--no-browser", "--port", String(port)], {
    cwd: PACKED ? app.getPath("userData") : ROOT,
    env,
    windowsHide: true,
  });
  engine.stdout.on("data", (d) => log.write(d));
  engine.stderr.on("data", (d) => log.write(d));
  engine.on("error", (err) => fail(`Could not start the engine (${err.message}). ${HINT}`));
  engine.on("exit", (code) => {
    engine = null;
    log.write(`--- engine exited with code ${code}\n`);
    if (!quitting) fail(`The engine stopped (exit code ${code}).`);
  });
}

async function waitForEngine(port, spawned, ms = 90000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (quitting) return "quit";
    const st = await getJSON(`http://127.0.0.1:${port}/api/status`);
    if (st && st.version) return "ready";
    if (spawned && !engine) return "exited";
    await new Promise((r) => setTimeout(r, 300));
  }
  return "timeout";
}

async function boot() {
  showSplash();
  try {
    let port = await runningEngine();
    const spawned = !port;
    if (spawned) {
      port = await pickPort();
      startEngine(port);
    }
    const result = await waitForEngine(port, spawned);
    if (result === "ready") win.loadURL(`http://127.0.0.1:${port}/`);
    else if (result === "timeout") fail("The engine did not start within 90 seconds.");
  } catch (err) {
    fail(err.message);
  }
}

function sendState() {
  if (!win || win.isDestroyed()) return;
  win.webContents.send("win:state", { focused: win.isFocused(), maximized: win.isMaximized() });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    frame: false,
    show: false,
    title: "Creator Asset Assistant",
    backgroundColor: "#e4e4e4",
    icon: path.join(__dirname, "assets", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.once("ready-to-show", () => win.show());
  for (const ev of ["focus", "blur", "maximize", "unmaximize"]) win.on(ev, sendState);
  win.webContents.on("did-finish-load", sendState);
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith("http://127.0.0.1:") && !url.startsWith("file://")) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });
  win.on("closed", () => (win = null));
}

ipcMain.on("win:minimize", () => win?.minimize());
ipcMain.on("win:maximize", () => {
  if (!win) return;
  if (win.isMaximized()) win.unmaximize();
  else win.maximize();
});
ipcMain.on("win:close", () => win?.close());
ipcMain.handle("dialog:folder", async () => {
  const r = await dialog.showOpenDialog(win, { title: "Add a folder to your library", properties: ["openDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("app:retry", () => boot());
ipcMain.handle("app:open-log", () => (logPath ? shell.openPath(logPath) : null));

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  });
  app.whenReady().then(() => {
    createWindow();
    boot();
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", () => {
    quitting = true;
    if (engine) engine.kill();
  });
}
