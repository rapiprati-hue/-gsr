import { build } from 'esbuild';
import { mkdir, copyFile, readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
const target = 'python/oriori_gsr';
await mkdir(`${target}/static/fonts`, {recursive:true});
await mkdir('public/downloads', {recursive:true});
await build({entryPoints:['src/portable.tsx'],bundle:true,outfile:`${target}/static/app.js`,minify:true,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},target:['es2020'],legalComments:'eof'});
await copyFile('src/app/workspace.css',`${target}/static/styles.css`);
await copyFile('public/icon.svg',`${target}/static/icon.svg`);
await copyFile('public/fonts/PretendardVariable.woff2',`${target}/static/fonts/PretendardVariable.woff2`);
await copyFile(`${target}/README.md`,'public/downloads/README.md');
await copyFile(`${target}/config.json`,`${target}/config.example.json`);
let notices = 'oriori_gsr portable web client — third-party license notices\n\n';
for (const name of ['react', 'react-dom', 'scheduler', 'lucide-react', 'qrcode', 'dijkstrajs']) {
  let found = false;
  for (const file of ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'license', 'license.md']) {
    try {
      const license = await readFile(`node_modules/${name}/${file}`, 'utf8');
      notices += `\n=== ${name} ===\n${license}\n`;
      found = true;
      break;
    } catch {}
  }
  if (!found) throw new Error(`Missing license for bundled package: ${name}`);
}
await writeFile(`${target}/assets/WEB-LICENSES.txt`, notices);
execFileSync('python3',['scripts/package.py'],{stdio:'inherit'});
console.log('oriori_gsr portable frontend and ZIP are ready.');
