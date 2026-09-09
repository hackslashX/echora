import { readFile, writeFile } from "node:fs/promises";

const increment = process.argv[2];
if (!["major", "minor", "patch"].includes(increment)) {
  throw new Error("Usage: node .github/scripts/bump-version.mjs <major|minor|patch>");
}

const packagePath = "apps/web/package.json";
const lockPath = "package-lock.json";
const footerPath = "apps/web/components/shell/CopyrightFooter.tsx";
const packageJson = JSON.parse(await readFile(packagePath, "utf8"));
const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(packageJson.version);

if (!match) {
  throw new Error(`Invalid current version: ${packageJson.version}`);
}

let [, major, minor, patch] = match.map((part, index) => index === 0 ? part : BigInt(part));
if (increment === "major") {
  major += 1n;
  minor = 0n;
  patch = 0n;
} else if (increment === "minor") {
  minor += 1n;
  patch = 0n;
} else {
  patch += 1n;
}

const version = `${major}.${minor}.${patch}`;
packageJson.version = version;
await writeFile(packagePath, `${JSON.stringify(packageJson, null, 2)}\n`);

const packageLock = JSON.parse(await readFile(lockPath, "utf8"));
const workspace = packageLock.packages?.["apps/web"];
if (!workspace) {
  throw new Error("apps/web is missing from package-lock.json");
}
workspace.version = version;
await writeFile(lockPath, `${JSON.stringify(packageLock, null, 2)}\n`);

const footer = await readFile(footerPath, "utf8");
if (!/OSS v\d+\.\d+\.\d+/.test(footer)) {
  throw new Error("Could not find the version identifier in CopyrightFooter.tsx");
}
await writeFile(footerPath, footer.replace(/OSS v\d+\.\d+\.\d+/, `OSS v${version}`));

process.stdout.write(version);
