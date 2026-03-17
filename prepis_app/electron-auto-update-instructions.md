# Electron Auto-Update via GitHub Releases — Implementation Instructions

## Context

I have an existing Electron app for Windows. Currently I manually replace the `.exe` file to update the client. The app has a **local database (SQLite or similar) that must NEVER be touched, deleted, or overwritten during updates**. I want to automate updates so the app checks GitHub Releases for a new version and updates itself.

---

## Critical Constraints

1. **The local database must survive all updates.** The database lives in the app's user data folder (`app.getPath('userData')`), NOT inside the app installation directory. If it's currently stored inside the installation directory, it must be migrated to `userData` first — updates replace the installation directory.
2. **Windows only.** No macOS or Linux targets needed.
3. **The GitHub repo can be public or private.** If private, a `GH_TOKEN` is needed at build time.
4. **The update should only replace the app code/exe, not user data.**

---

## Step-by-step Implementation

### Step 1: Install dependencies

Run in the project root:

```bash
npm install electron-updater --save
npm install electron-builder --save-dev
```

### Step 2: Configure electron-builder

In `package.json`, add or update the `build` config:

```json
{
  "name": "your-app-name",
  "version": "1.0.0",
  "main": "main.js",
  "build": {
    "appId": "com.yourname.yourapp",
    "productName": "YourAppName",
    "win": {
      "target": "nsis",
      "publisherName": "Your Name"
    },
    "nsis": {
      "oneClick": true,
      "perMachine": false,
      "allowToChangeInstallationDirectory": false
    },
    "publish": {
      "provider": "github",
      "owner": "YOUR_GITHUB_USERNAME",
      "repo": "YOUR_REPO_NAME",
      "releaseType": "release"
    },
    "files": [
      "**/*",
      "!**/node_modules/*/{CHANGELOG.md,README.md,README,readme.md,readme}",
      "!**/node_modules/.cache/**"
    ],
    "extraResources": []
  },
  "scripts": {
    "build": "electron-builder --win --publish never",
    "release": "electron-builder --win --publish always"
  }
}
```

**IMPORTANT:** Replace `YOUR_GITHUB_USERNAME` and `YOUR_REPO_NAME` with real values.

### Step 3: Ensure the database is stored in the safe location

The database must live in `app.getPath('userData')`, which is typically:
```
C:\Users\<username>\AppData\Roaming\<YourAppName>\
```

This folder is NEVER touched by updates. The installation folder (`C:\Program Files\...` or `C:\Users\...\AppData\Local\Programs\...`) IS replaced on update.

In your main process code, the database path should be:

```javascript
const path = require('path');
const { app } = require('electron');

const DB_PATH = path.join(app.getPath('userData'), 'database.db');
```

**If the database is currently stored inside the app/installation folder, you must add migration logic:**

```javascript
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

const safeDbPath = path.join(app.getPath('userData'), 'database.db');
const oldDbPath = path.join(__dirname, 'database.db'); // or wherever it currently lives

// Migration: run once, move DB to safe location
if (!fs.existsSync(safeDbPath) && fs.existsSync(oldDbPath)) {
  fs.copyFileSync(oldDbPath, safeDbPath);
  console.log('Database migrated to userData folder.');
}

// From now on, ALWAYS use safeDbPath for all database operations
```

### Step 4: Add auto-update logic to the main process

In your `main.js` (or wherever your main process entry point is), add:

```javascript
const { app, BrowserWindow, dialog } = require('electron');
const { autoUpdater } = require('electron-updater');
const log = require('electron-log');

// Optional: configure logging so you can debug update issues
autoUpdater.logger = log;
autoUpdater.logger.transports.file.level = 'info';

// Disable auto-download so you can control the flow
autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = true;

function checkForUpdates() {
  autoUpdater.checkForUpdates();
}

// --- Update event handlers ---

autoUpdater.on('update-available', (info) => {
  dialog.showMessageBox({
    type: 'info',
    title: 'Update Available',
    message: `Version ${info.version} is available. Download now?`,
    buttons: ['Yes', 'Later']
  }).then((result) => {
    if (result.response === 0) {
      autoUpdater.downloadUpdate();
    }
  });
});

autoUpdater.on('update-not-available', () => {
  // No update needed, do nothing
  log.info('No update available.');
});

autoUpdater.on('download-progress', (progress) => {
  log.info(`Download speed: ${progress.bytesPerSecond} - Downloaded ${progress.percent}%`);
  // Optionally send progress to renderer via mainWindow.webContents.send()
});

autoUpdater.on('update-downloaded', () => {
  dialog.showMessageBox({
    type: 'info',
    title: 'Update Ready',
    message: 'Update downloaded. The app will restart to install it.',
    buttons: ['Restart Now', 'Later']
  }).then((result) => {
    if (result.response === 0) {
      autoUpdater.quitAndInstall();
    }
  });
});

autoUpdater.on('error', (error) => {
  log.error('Update error:', error);
  // Silently fail — don't crash the app because of an update error
});

// --- App lifecycle ---

app.whenReady().then(() => {
  // ... your existing window creation code ...

  // Check for updates after the app has loaded (with a small delay)
  setTimeout(() => {
    checkForUpdates();
  }, 3000);
});
```

**OPTION B: Silent auto-update (no prompts, installs on next restart):**

If you prefer no dialog boxes at all:

```javascript
const { autoUpdater } = require('electron-updater');

autoUpdater.autoDownload = true;
autoUpdater.autoInstallOnAppQuit = true;

app.whenReady().then(() => {
  // ... your window code ...
  autoUpdater.checkForUpdatesAndNotify();
});
```

This will silently download updates in the background and install them next time the user closes and reopens the app.

### Step 5: How to build and publish a release

**First time setup:**

1. Create a GitHub Personal Access Token:
   - Go to GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
   - Generate a new token with `repo` scope (full access to private repos)
   - Copy the token

2. Set the token as an environment variable before building:
   ```bash
   # In PowerShell:
   $env:GH_TOKEN = "your_github_token_here"

   # In CMD:
   set GH_TOKEN=your_github_token_here
   ```

**Every time you want to release an update:**

1. **Bump the version** in `package.json`:
   ```json
   "version": "1.1.0"
   ```
   The version MUST be higher than the previous release. Use semantic versioning (major.minor.patch).

2. **Run the release command:**
   ```bash
   npm run release
   ```

3. **What this does automatically:**
   - Builds the `.exe` installer
   - Generates a `latest.yml` file containing the version, filename, file hash, and download URL
   - Creates a new GitHub Release tagged with the version
   - Uploads the `.exe` and `latest.yml` to that release

4. **That's it.** Next time any client opens the app, it will detect the new version and update.

### Step 6: What the client experiences

1. Client opens the app normally
2. App checks GitHub Releases in the background (reads `latest.yml`)
3. If a new version exists:
   - **With dialog (Option A):** They see "Update available" → click Yes → download happens → "Restart to install" → app restarts with new version
   - **Silent (Option B):** Download happens invisibly. Next time they close and reopen the app, they have the new version
4. Their database and all user data in `AppData\Roaming\YourAppName\` is completely untouched

---

## File/Folder Summary

```
YOUR PROJECT/
├── main.js                  ← Main process (add auto-updater here)
├── package.json             ← Version number + build config here
├── src/                     ← Your app code
├── ...
└── dist/                    ← Built output (created by electron-builder)
    ├── YourAppName Setup 1.0.0.exe
    └── latest.yml

CLIENT'S MACHINE:
├── C:\Users\X\AppData\Local\Programs\YourAppName\   ← App installation (REPLACED on update)
│   ├── YourAppName.exe
│   ├── resources/
│   └── ...
└── C:\Users\X\AppData\Roaming\YourAppName\           ← User data (NEVER touched)
    └── database.db
```

---

## Checklist Before First Release

- [ ] `electron-updater` is installed as a dependency (not devDependency)
- [ ] `electron-builder` is installed as a devDependency
- [ ] `package.json` has `build.publish` configured with correct GitHub owner/repo
- [ ] Database path uses `app.getPath('userData')`, NOT `__dirname` or the app folder
- [ ] Migration logic exists if database was previously in the app folder
- [ ] `autoUpdater.checkForUpdates()` is called in the main process after app is ready
- [ ] `GH_TOKEN` environment variable is set before running `npm run release`
- [ ] Version in `package.json` is bumped before each release

---

## Troubleshooting

- **"Cannot find update info"** → The `latest.yml` file is missing from the GitHub Release. Re-run `npm run release`.
- **"Update downloaded but nothing happens"** → Make sure `autoUpdater.quitAndInstall()` is being called, or that `autoInstallOnAppQuit` is `true`.
- **"Database is gone after update"** → The database was stored in the installation directory. Move it to `app.getPath('userData')` immediately.
- **"404 when checking for updates"** → Check that the GitHub repo name and owner are correct in `package.json`. If the repo is private, the client app also needs a token configured in the updater.
- **Updates work in dev but not in production** → Auto-updater only works in packaged/built apps, not in `electron .` dev mode. Test with a built `.exe`.
