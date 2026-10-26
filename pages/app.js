const $=id=>document.getElementById(id);
const format=(value,digits=2)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:digits,minimumFractionDigits:digits}):'—';
const unit=(value,name)=>`${format(value)} ${name}`;
let data;
function show(view){
  document.querySelectorAll('[data-page]').forEach(el=>el.hidden=el.dataset.page!==view);
  document.querySelectorAll('[data-view]').forEach(el=>{if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.view)));
function draw(){
  const selected=data.strategies.find(s=>s.id===$('strategy').value);
  $('total-cost').textContent=unit(selected.total_cost,'示例元');
  $('peak-grid').textContent=unit(selected.peak_grid_kw,'kW');
  $('clip-energy').textContent=unit(selected.clip_kwh,'kWh');
  $('comparison').textContent=selected.comparison_valid?'可比较':'不可公平比较';
  const values=data.points.flatMap(p=>[p.actual_kw,p.forecast_kw,p.strategies[selected.id].grid_kw]).filter(Number.isFinite);
  const maximum=Math.max(...values)*1.1;
  const xy=(value,i)=>[50+i/(data.points.length-1)*920,230-value/maximum*200];
  const NS='http://www.w3.org/2000/svg',svg=$('chart');svg.replaceChildren();
  const element=(tag,attributes,text)=>{const el=document.createElementNS(NS,tag);for(const [key,value]of Object.entries(attributes))el.setAttribute(key,value);if(text)el.textContent=text;svg.append(el);return el;};
  for(let i=0;i<5;i++){
    const y=230-i*50;element('line',{x1:50,x2:970,y1:y,y2:y,stroke:'#e4eaf0','stroke-dasharray':'3 5'});
    element('text',{x:42,y:y+4,'text-anchor':'end',fill:'#7d8995','font-size':11},format(maximum*i/4,0));
  }
  for(const [key,color]of [['actual_kw','#557eaa'],['forecast_kw','#c5a46a'],['grid_kw','#168d91']]){
    element('polyline',{points:data.points.map((p,i)=>xy(key==='grid_kw'?p.strategies[selected.id].grid_kw:p[key],i).join(',')).join(' '),fill:'none',stroke:color,'stroke-width':key==='grid_kw'?2.8:1.8,'stroke-dasharray':key==='forecast_kw'?'5 4':'0'});
  }
  const index=Number($('time').value),point=data.points[index],actual=point.strategies[selected.id];
  element('line',{x1:xy(0,index)[0],x2:xy(0,index)[0],y1:20,y2:235,stroke:'#526b82','stroke-width':1,'stroke-dasharray':'3 3'});
  $('timestamp').textContent=point.timestamp;
  $('tick-load').textContent=unit(point.actual_kw,'kW');$('tick-grid').textContent=unit(actual.grid_kw,'kW');
  $('tick-soc').textContent=unit(actual.soc_kwh,'kWh');$('tick-actions').textContent=`${format(actual.charge_kw)} / ${format(actual.discharge_kw)} kW`;
}
try{
  const response=await fetch(new URL('./case.json',import.meta.url));if(!response.ok)throw Error('公开案例文件暂不可读');data=await response.json();
  if(data.mode!=='read-only-precomputed-public-case'||data.dataset.public_data!==true)throw Error('案例身份未通过公开边界检查');
  $('dataset-name').textContent=data.dataset.name;$('period').textContent=`${data.summary.period_start.slice(0,10)} · 历史单日回放`;
  $('interval').textContent=`原生 ${data.dataset.interval_minutes} 分钟 · ${data.points.length} 时段`;
  $('time').max=data.points.length-1;
  for(const strategy of data.strategies){const option=document.createElement('option');option.value=strategy.id;option.textContent=`${strategy.id} · ${strategy.name}`;$('strategy').append(option);}
  $('strategy').value='B2';$('strategy').addEventListener('change',draw);$('time').addEventListener('input',draw);
  $('case-warning').textContent=data.summary.warnings.join(' ');
  $('source-warning').textContent=data.provenance.warning;
  for(const text of data.limitations){const li=document.createElement('li');li.textContent=text;$('limitations').append(li);}
  $('dataset-source').href=data.provenance.source_url;$('run-id').textContent=data.runId;$('result-hash').textContent=data.sourceResultSha256;
  for(const strategy of data.strategies){const row=document.createElement('tr');for(const text of [`${strategy.id} · ${strategy.name}`,format(strategy.energy_cost),format(strategy.demand_cost),format(strategy.degradation_cost),format(strategy.total_cost),strategy.id==='O1'?'不可部署诊断':strategy.comparison_valid?'可比较':'不可比']){const cell=document.createElement('td');cell.textContent=text;row.append(cell);}$('strategy-costs').append(row);}
  draw();$('case-content').hidden=false;$('load-status').textContent='';
}catch(error){$('load-status').textContent=`案例未加载：${error.message}。请通过 README 下载本地版本。`;}
