import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import test from 'node:test';

const components = fileURLToPath(new URL('../components/', import.meta.url));
function styles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? styles(path) : entry.name.endsWith('.module.css') ? [path] : [];
  });
}

test('component panels use shared surfaces instead of fixed dark colors', () => {
  for (const path of styles(components)) {
    const source = readFileSync(path, 'utf8');
    for (const match of source.matchAll(/background(?:-color)?\s*:\s*#([\da-f]{6}|[\da-f]{3})\s*[;}]/gi)) {
      const hex = match[1].length === 3 ? [...match[1]].map(c => c + c).join('') : match[1];
      const rgb = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
      const neutralDark = Math.max(...rgb) <= 58 && Math.max(...rgb) - Math.min(...rgb) <= 25;
      assert.equal(neutralDark, false, `${path} has a fixed panel background: ${match[0]}`);
    }
    assert.ok(!source.includes('--art-panel,'), `${path} bypasses shared surfaces`);
    assert.doesNotMatch(source, /--[\w-]*surface[\w-]*\s*:\s*#/, `${path} has a fixed surface alias`);
  }
});

test('full-page layers stay translucent so the backdrop remains visible', () => {
  const shell = readFileSync(join(components, 'shell/AppShell.module.css'), 'utf8');
  const login = readFileSync(join(components, 'Login.module.css'), 'utf8');
  const tokens = readFileSync(new URL('./theme.css', import.meta.url), 'utf8');
  assert.match(shell, /\.frame\{[^}]*background:var\(--surface-shell\)/);
  assert.match(login, /\.page\{[^}]*background:var\(--surface-shell\)/);
  assert.match(tokens, /--surface-shell:\s*rgb\(var\(--surface-rgb\)\s*\/\s*\.14\)/);
});

test('card headers do not mix bright artwork accents into their backgrounds', () => {
  const header = readFileSync(join(components, 'ui/CardHeader.module.css'), 'utf8');
  assert.match(header, /background: var\(--surface-raised\)/);
  assert.doesNotMatch(header, /background:\s*color-mix/);
});

test('success messages do not use the changing artwork accent as status text', () => {
  for (const name of ['settings/SettingsView.module.css', 'settings/ExternalAISettings.module.css']) {
    const source = readFileSync(join(components, name), 'utf8');
    assert.match(source, /background:\s*var\(--status-success-surface\);\s*color:\s*var\(--status-success-text\)/);
  }
});

test('palette publication changes only the shared surface hue', () => {
  const provider = readFileSync(join(components, 'player/PlayerProvider.tsx'), 'utf8');
  assert.match(provider, /setProperty\("--surface-rgb", panelColorFromPalette/);
  assert.match(provider, /removeProperty\("--surface-rgb"\)/);
  assert.doesNotMatch(provider, /setProperty\("--(?:glass|art-panel)"/);
});
