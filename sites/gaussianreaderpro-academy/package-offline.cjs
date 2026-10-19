/* Build a single HTML file, without remote resources or a frontend toolchain. */
const fs=require('node:fs');
const path=require('node:path');
const root=__dirname;
const read=name=>fs.readFileSync(path.join(root,'dist',name),'utf8');
let html=read('index.html');
html=html.replace('<link rel="stylesheet" href="styles.css">',()=>`<style>${read('styles.css')}</style>`);
const scripts=['model.js','curriculum.js','visuals.js','audio.js','app.js'];
for(const name of scripts)html=html.replace(`<script src="${name}" defer></script>`,'');
html=html.replace('</body>',()=>scripts.map(name=>`<script>\n${read(name).replace(/<\/script/gi,'<\\/script')}\n</script>`).join('\n')+'\n</body>');
fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
const output=path.join(root,'artifacts','GaussianReaderPro-Academy.html');
fs.writeFileSync(output,html,'utf8');
console.log(output);
