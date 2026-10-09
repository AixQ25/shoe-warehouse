import { compactLabelSettings, createLabelLayout } from './labelLayout'
import type { EditableLabel, LabelSettings } from './labelLayout'

export function downloadLabelFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename
  document.body.append(link); link.click(); link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function rasterize(svg: string, width: number, height: number): Promise<HTMLCanvasElement> {
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }))
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = Math.ceil(width * 300 / 25.4); canvas.height = Math.ceil(height * 300 / 25.4)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法生成 PDF 图像')
    context.fillStyle = 'white'; context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return canvas
  } finally { URL.revokeObjectURL(url) }
}

export async function labelPdf(labels: EditableLabel[], settings: LabelSettings) {
  await document.fonts?.ready
  const { jsPDF } = await import('jspdf')
  const engine = createLabelLayout(), plan = engine.paginate(labels.length, settings)
  if (!plan.pages.length) throw new Error('请先生成标签预览')
  const orientation = plan.pageWidth > plan.pageHeight ? 'landscape' : 'portrait'
  const pdf = new jsPDF({ unit: 'mm', format: [plan.pageWidth, plan.pageHeight], orientation, compress: true, precision: 6 })
  pdf.viewerPreferences({ PrintScaling: 'None', PickTrayByPDFSize: true })
  pdf.setProperties({ title: `Warehouse labels ${settings.width}x${settings.height}mm`, subject: 'Print at actual size / 100%' })
  for (let pageIndex = 0; pageIndex < plan.pages.length; pageIndex++) {
    if (pageIndex) pdf.addPage([plan.pageWidth, plan.pageHeight], orientation)
    for (const position of plan.pages[pageIndex].positions) {
      const canvas = await rasterize(engine.labelSvg(labels[position.index], settings), settings.width, settings.height)
      pdf.addImage(canvas, 'PNG', position.x, position.y, settings.width, settings.height, undefined, 'FAST')
    }
  }
  return pdf.output('blob')
}

// This file is portable and self-contained: no CDN, project server or installed tool is required.
export function labelEditorHtml(labels: EditableLabel[], settings: LabelSettings) {
  const data = JSON.stringify({ labels, settings }).replace(/[<>&\u2028\u2029]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`)
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>标签排版编辑 · ${settings.width} × ${settings.height} mm</title>
<style>
*{box-sizing:border-box}body{margin:0;font:14px system-ui,'Microsoft YaHei',sans-serif;background:#edf2ef;color:#203c2d}header{padding:20px 28px;background:white;border-bottom:1px solid #d7e2da}h1{font-size:22px;margin:0 0 8px}p{line-height:1.6;margin:6px 0;color:#567061}main{display:grid;grid-template-columns:300px minmax(0,1fr);gap:20px;padding:20px}aside{background:white;padding:20px;border:1px solid #d7e2da;border-radius:12px;align-self:start}fieldset{border:0;padding:0;margin:0 0 18px}legend{font-weight:700;margin-bottom:12px}label{display:grid;grid-template-columns:1fr 105px;gap:8px;align-items:center;margin:9px 0}input,select,button{font:inherit;padding:7px;border:1px solid #b9cdbf;border-radius:6px;min-width:0}button{background:#176545;color:white;cursor:pointer;margin:4px 4px 4px 0}button:disabled{opacity:.4;cursor:default}select{max-width:100%}input:read-only{background:#eef3ef;color:#75867d}.field{grid-template-columns:1fr}.label-text-editor{margin-top:18px;padding:18px;background:white;border:1px solid #d7e2da;border-radius:12px}#text-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}.stage{overflow:auto;min-height:260px;padding:18px;background:#dfe8e2;border-radius:12px}.stage svg{display:block;max-width:none;box-shadow:0 3px 16px #0001}.summary{font-weight:600;margin:0 0 12px}#error{color:#a42424}#print-pages{display:none}.hint{font-size:12px}.actions{margin:14px 0}.page-nav{display:flex;align-items:center;gap:8px;margin-bottom:12px}@media(max-width:760px){main{grid-template-columns:1fr}#text-fields{grid-template-columns:1fr}}@media print{html,body{margin:0;padding:0;background:white}body>:not(#print-pages){display:none!important}#print-pages{display:block}.print-page{break-after:page;break-inside:avoid}.print-page:last-child{break-after:auto}.print-page svg{display:block}}
</style><style id="page-style"></style></head><body><header><h1>标签排版编辑</h1><p>毫米标尺与纸张边界用于核对大小和位置。橙色虚线是标签边界，蓝色虚线是二维码范围；辅助线不会打印。</p><p class="hint">此文件可离线编辑。修改只影响当前文件，仓库资料和二维码身份不会改变。修改后请保存副本。打印选择实际大小 / 100%，关闭适应页面与页眉页脚。</p></header><main><aside><fieldset><legend>纸张与标签 · mm</legend><label class="field">纸张<select id="paper"><option value="label">标签纸 · 一页一张</option><option value="a4">A4 · 210 × 297</option></select></label><div id="size-fields"></div><label class="field">标签外框<select id="border"><option value="off">无外框</option><option value="on">有外框 · 黑色细线</option></select></label></fieldset><button id="compact">使用 60 × 25 紧凑排版</button><button id="save">保存编辑文件</button><button id="svg">导出当前页 SVG</button><button id="print">打印 / 另存 PDF</button><p class="hint">SVG 保留独立文字与二维码图形，可在矢量编辑软件中调整。首次导出已由仓库记录请求；本文件离线打印不会新增记录。</p></aside><section><p id="error" role="alert"></p><div id="summary" class="summary"></div><div class="page-nav"><button id="prev">上一页</button><span id="page-count"></span><button id="next">下一页</button><label>预览缩放<select id="zoom"><option value="0.6">60%</option><option value="0.8">80%</option><option value="1">100%</option><option value="1.25">125%</option></select></label></div><div id="stage" class="stage"></div><p id="position" class="hint"></p><fieldset class="label-text-editor"><legend>当前标签文字</legend><label class="field">选择标签<select id="selected-label"></select></label><div id="text-fields"></div><p class="hint">款号、类别、码数和二维码身份保持一致；可编辑其余文字。</p></fieldset></section></main><div id="print-pages"></div><script id="label-data" type="application/json">${data}</script><script>
const engine=(${createLabelLayout.toString()})();
const data=JSON.parse(document.getElementById('label-data').textContent),labels=data.labels,settings=data.settings;
const fields=[['width','标签宽',35,150],['height','标签高',25,100],['marginX','页面左右边距',0,50],['marginY','页面上下边距',0,50],['gap','标签间距',0,15],['padding','标签内边距',1,10],['qrSize','二维码宽高',12,96],['textGap','图文间距',1,10],['fontSize','字号 · pt',5.5,24]];
let page=0,valid=false;const get=id=>document.getElementById(id);
function download(text,type,name){const url=URL.createObjectURL(new Blob([text],{type})),link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
fields.forEach(([key,name,min,max])=>{const label=document.createElement('label');label.append(name);const input=document.createElement('input');input.type='number';input.min=min;input.max=max;input.step='0.5';input.value=settings[key];input.id=key;input.oninput=()=>{settings[key]=Number(input.value);render()};label.append(input);get('size-fields').append(label)});
get('border').value=settings.border?'on':'off';get('border').onchange=()=>{settings.border=get('border').value==='on';render()};
get('compact').onclick=()=>{Object.assign(settings,${JSON.stringify(compactLabelSettings)});fields.forEach(([key])=>get(key).value=settings[key]);page=0;render()};
get('paper').value=settings.paper;get('paper').onchange=()=>{settings.paper=get('paper').value;page=0;render()};
labels.forEach((label,index)=>{const option=document.createElement('option');option.value=index;option.textContent=label.code;get('selected-label').append(option)});
function textFields(){const selected=labels[Number(get('selected-label').value)];get('text-fields').replaceChildren();selected.rows.forEach((value,index)=>{const label=document.createElement('label');label.className='field';const input=document.createElement('input');input.value=value;input.maxLength=300;input.readOnly=[7,8].includes(selected.rows.length)?[1,2,3].includes(index):index===0;input.setAttribute('aria-label','文字第 '+(index+1)+' 行');input.oninput=()=>{selected.rows[index]=input.value;render()};label.append(input);get('text-fields').append(label)})}
get('selected-label').onchange=()=>{try{page=Math.floor(Number(get('selected-label').value)/engine.geometry(settings).perPage)}catch{page=0}textFields();render()};textFields();
function render(){document.title='标签排版编辑 · '+settings.width+' × '+settings.height+' mm';valid=false;get('error').textContent='';get('stage').replaceChildren();get('summary').textContent='';get('position').textContent='';get('page-count').textContent='';get('print-pages').replaceChildren();try{const plan=engine.paginate(labels.length,settings);labels.forEach(label=>engine.fontFor(label,settings));page=Math.max(0,Math.min(page,plan.pages.length-1));get('summary').textContent='纸张 '+plan.pageWidth+' × '+plan.pageHeight+' mm · 标签 '+settings.width+' × '+settings.height+' mm · 每页 '+plan.columns+' 列 × '+plan.rows+' 行 · 实际最小字号 '+Math.min(...labels.map(label=>engine.fontFor(label,settings))).toFixed(1)+' pt';get('page-count').textContent='第 '+(page+1)+' / '+plan.pages.length+' 页';get('stage').innerHTML=engine.pageSvg(labels,settings,page,true);const svg=get('stage').firstElementChild,zoom=Number(get('zoom').value);svg.style.width=((plan.pageWidth+20)*96/25.4*zoom)+'px';svg.style.height=((plan.pageHeight+20)*96/25.4*zoom)+'px';get('position').textContent=plan.pages[page].positions.map(p=>labels[p.index].code+'：左 '+p.x+' mm，上 '+p.y+' mm').join('；');plan.pages.forEach((_,i)=>{const div=document.createElement('div');div.className='print-page';div.innerHTML=engine.pageSvg(labels,settings,i);get('print-pages').append(div)});get('page-style').textContent='@page{size:'+plan.pageWidth+'mm '+plan.pageHeight+'mm;margin:0}';valid=true}catch(error){get('error').textContent=error.message}fields.filter(f=>['marginX','marginY','gap'].includes(f[0])).forEach(([key])=>get(key).disabled=settings.paper==='label');get('save').disabled=!valid;get('svg').disabled=!valid;get('print').disabled=!valid;get('prev').disabled=page===0;get('next').disabled=!valid||page>=engine.paginate(labels.length,settings).pages.length-1}
get('zoom').onchange=render;get('prev').onclick=()=>{page--;render()};get('next').onclick=()=>{page++;render()};get('svg').onclick=()=>{if(valid)download(engine.pageSvg(labels,settings,page),'image/svg+xml;charset=utf-8','labels-'+(settings.paper==='a4'?'a4-':'')+settings.width+'x'+settings.height+'mm-page-'+(page+1)+'.svg')};get('print').onclick=()=>{if(valid)window.print()};get('save').onclick=()=>{if(!valid)return;const copy=document.documentElement.cloneNode(true);copy.querySelector('#label-data').textContent=JSON.stringify({labels,settings}).replace(/[<>&\\u2028\\u2029]/g,char=>'\\\\u'+char.charCodeAt(0).toString(16).padStart(4,'0'));['size-fields','selected-label','text-fields','stage','print-pages'].forEach(id=>copy.querySelector('#'+id).replaceChildren());download('<!doctype html>'+copy.outerHTML,'text/html;charset=utf-8','labels-editor-'+(settings.paper==='a4'?'a4-':'')+settings.width+'x'+settings.height+'mm.html')};render();
</script></body></html>`
}
