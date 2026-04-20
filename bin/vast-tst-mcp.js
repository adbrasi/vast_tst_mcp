#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const packageRoot = path.resolve(__dirname, "..");
const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8"));
const cacheRoot = resolveCacheRoot();
const runtimeRoot = path.join(cacheRoot, packageJson.version);
const venvDir = path.join(runtimeRoot, "venv");
const stampPath = path.join(runtimeRoot, "install-stamp.json");
const sourceHash = computeSourceHash();
const packageStamp = {
  version: packageJson.version,
  sourceHash,
};

main();

function main() {
  fs.mkdirSync(runtimeRoot, { recursive: true });

  if (!isRuntimeReady()) {
    bootstrapRuntime();
  }

  const command = pythonScriptPath("vast-ai-mcp");
  const child = spawn(command, process.argv.slice(2), {
    stdio: "inherit",
    env: process.env,
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 0);
  });

  child.on("error", (error) => {
    console.error(`[vast-tst-mcp] Failed to start MCP server: ${error.message}`);
    process.exit(1);
  });
}

function resolveCacheRoot() {
  if (process.env.VAST_TST_MCP_HOME) {
    return path.resolve(process.env.VAST_TST_MCP_HOME);
  }
  if (process.env.XDG_CACHE_HOME) {
    return path.join(process.env.XDG_CACHE_HOME, "vast_tst_mcp");
  }
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Caches", "vast_tst_mcp");
  }
  return path.join(os.homedir(), ".cache", "vast_tst_mcp");
}

function isRuntimeReady() {
  if (!fs.existsSync(pythonScriptPath("vast-ai-mcp"))) {
    return false;
  }
  if (!fs.existsSync(stampPath)) {
    return false;
  }

  try {
    const currentStamp = JSON.parse(fs.readFileSync(stampPath, "utf8"));
    return currentStamp.version === packageStamp.version && currentStamp.sourceHash === packageStamp.sourceHash;
  } catch {
    return false;
  }
}

function bootstrapRuntime() {
  const python = resolvePython();
  console.error(`[vast-tst-mcp] Bootstrapping runtime in ${runtimeRoot}`);
  run(python, ["-m", "venv", venvDir], "creating virtualenv");
  run(
    pythonExecutable(),
    ["-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet", "--upgrade", packageRoot],
    "installing MCP package"
  );

  fs.writeFileSync(stampPath, JSON.stringify(packageStamp, null, 2));
}

function resolvePython() {
  for (const candidate of ["python3", "python"]) {
    const result = spawnSync(candidate, ["--version"], {
      stdio: "ignore",
      env: process.env,
    });
    if (result.status === 0) {
      return candidate;
    }
  }

  console.error("[vast-tst-mcp] Python 3 was not found in PATH.");
  console.error("[vast-tst-mcp] Install Python 3.11+ and run the command again.");
  process.exit(1);
}

function pythonExecutable() {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", "python.exe");
  }
  return path.join(venvDir, "bin", "python");
}

function pythonScriptPath(name) {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", `${name}.exe`);
  }
  return path.join(venvDir, "bin", name);
}

function run(command, args, label) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    env: process.env,
  });

  if (result.status !== 0) {
    if (result.stdout) {
      process.stderr.write(result.stdout);
    }
    if (result.stderr) {
      process.stderr.write(result.stderr);
    }
    console.error(`[vast-tst-mcp] Failed while ${label}.`);
    process.exit(result.status ?? 1);
  }

  if (process.env.VAST_TST_MCP_DEBUG_BOOTSTRAP === "1") {
    if (result.stdout) {
      process.stderr.write(result.stdout);
    }
    if (result.stderr) {
      process.stderr.write(result.stderr);
    }
  }
}

function computeSourceHash() {
  const hash = crypto.createHash("sha256");
  const roots = [
    path.join(packageRoot, "package.json"),
    path.join(packageRoot, "pyproject.toml"),
    path.join(packageRoot, "bin"),
    path.join(packageRoot, "src"),
  ];

  for (const entry of collectFiles(roots)) {
    const relativePath = path.relative(packageRoot, entry);
    hash.update(relativePath);
    hash.update("\0");
    hash.update(fs.readFileSync(entry));
    hash.update("\0");
  }

  return hash.digest("hex");
}

function collectFiles(entries) {
  const files = [];

  for (const entry of entries) {
    if (!fs.existsSync(entry)) {
      continue;
    }

    const stat = fs.statSync(entry);
    if (stat.isDirectory()) {
      const children = fs.readdirSync(entry).map((child) => path.join(entry, child));
      files.push(...collectFiles(children));
      continue;
    }

    if (stat.isFile()) {
      files.push(entry);
    }
  }

  return files.sort();
}
