const fs = require('node:fs');
const ts = require('typescript');
for (const name of fs.readdirSync('src/components').filter(n=>n.endsWith('.tsx')).map(n=>'src/components/'+n).concat(['src/App.tsx','src/ui.tsx'])) {
  let source = fs.readFileSync(name, 'utf8').replace(/></g, '>\n<');
  const ast = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  if (ast.parseDiagnostics.length) throw new Error('Formatting parse failure: '+name);
  fs.writeFileSync(name, ts.createPrinter({newLine:ts.NewLineKind.LineFeed}).printFile(ast));
}
const css = fs.readFileSync('src/styles.css','utf8');
let result = '', indent = 0;
for (const character of css) {
  if (character === '{') { indent++; result += ' {\n' + '  '.repeat(indent); }
  else if (character === '}') { indent--; result = result.trimEnd() + '\n' + '  '.repeat(indent) + '}\n' + '  '.repeat(indent); }
  else if (character === ';') result += ';\n' + '  '.repeat(indent);
  else if (character === '\n') { if (!result.endsWith('\n')) result += '\n'; }
  else result += character;
}
fs.writeFileSync('src/styles.css',result.trim()+'\n');
