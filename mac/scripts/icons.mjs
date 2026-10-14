// Regenerate the rounded Mac app icon and a monochrome template tray icon
// from the dashboard's checked-in SVG. Run `npm run icons` in mac/.
import { readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import sharp from 'sharp';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = await readFile(path.join(root, '../web/public/static/icon.svg'), 'utf8');
const shapes = source.match(/<path\b[^>]*\/>/g);
if (!shapes?.length) throw new Error('Dashboard icon has no SVG paths.');
const square = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<rect x="72" y="72" width="880" height="880" rx="196" fill="#16120c"/>
<g transform="translate(51.2 51.2) scale(.9)">${shapes.join('\n')}</g>
</svg>\n`;
const tray = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="160 180 704 664">
${shapes.join('\n').replace(/fill="[^"]*"/g, 'fill="#000"')}
</svg>\n`;
const icons = path.join(root, 'src-tauri/icons');
await mkdir(icons, { recursive: true });
await writeFile(path.join(icons, 'mac-icon.svg'), square);
await writeFile(path.join(icons, 'tray.svg'), tray);
await writeFile(path.join(root, 'setup/icon.svg'), square);
await sharp(Buffer.from(tray)).resize(44, 44).png().toFile(path.join(icons, 'tray.png'));
execFileSync(path.join(root, 'node_modules/.bin/tauri'), ['icon', path.join(icons, 'mac-icon.svg'), '--output', icons], { cwd: root, stdio: 'inherit' });
// The CLI also emits icons for platforms this wrapper doesn't target.
for (const entry of ['android', 'ios', 'icon.ico', 'StoreLogo.png',
  ...[30, 44, 71, 89, 107, 142, 150, 284, 310].map(size => `Square${size}x${size}Logo.png`)]) {
  await rm(path.join(icons, entry), { recursive: true, force: true });
}
