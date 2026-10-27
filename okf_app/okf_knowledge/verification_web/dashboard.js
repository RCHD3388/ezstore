function node(tag, cls, text) {
  const element=document.createElement(tag);
  if(cls) element.className=cls;
  if(text!==undefined) element.textContent=text;
  return element;
}
function badge(passed) {return node('span','badge '+(passed?'pass':'fail'),passed?'PASS':'FAIL');}
function explanation(check) {
  const d=check.detail;
  switch(check.id) {
    case 'bundle': return `${d.parsed_documents ?? 0} documents · ${d.parsed_concepts ?? 0} concepts · ${(d.issues || []).length} issues`;
    case 'concepts': return `${d.concepts_read} concepts discovered with readable content and metadata`;
    case 'answers': return `${d.passed_cases}/${d.total_cases} cases passed; returned text checked against its source`;
    case 'unsupported': return `${d.refused_cases}/${d.total_cases} unsupported or live-data questions declined`;
    case 'readonly': return `${d.file_reads} reads · ${d.write_attempts.length} write attempts · ${d.network_attempts.length} network attempts`;
    case 'protected': return `${d.files} tracked files compared · ${d.changed.length} changed · ${d.changes_outside_scope.length} changes outside scope`;
    case 'agents': return Object.entries(d).map(([name,value])=>`${name}/: ${value.files} files, ${value.changed.length} changes`).join(' · ');
    case 'stage3': return `${d.preserved_files} files preserved · port 8020 PID ${d.pid_before} → ${d.pid_after} · HTTP ${d.http_status}`;
    case 'tests': return `${d.tests} tests · ${d.failures} failures · ${d.errors} errors`;
    default: return 'See recorded evidence.';
  }
}
async function load() {
  const response=await fetch('/api/report',{cache:'no-store'});
  const report=await response.json();
  if(!response.ok) throw new Error(report.error || 'Verification evidence is unavailable.');
  const allPassed=report.checks.every(check=>check.passed);
  const overall=document.querySelector('#overall');
  overall.className='badge '+(allPassed?'pass':'fail');
  overall.textContent=allPassed?'PASS':'FAIL';
  document.querySelector('#overall-label').textContent=`${report.checks.filter(c=>c.passed).length} of ${report.checks.length} checks passed`;
  document.querySelector('#timestamp').textContent=new Date(report.created_at).toISOString().replace('T',' ').replace(/\.\d+Z$/,' UTC');
  document.querySelector('#concept-count').textContent=report.knowledge.concepts.length;
  document.querySelector('#case-count').textContent=`${report.knowledge.cases.filter(c=>c.passed).length} / ${report.knowledge.cases.length}`;
  document.querySelector('#test-count').textContent=report.unit_tests.tests-report.unit_tests.failures-report.unit_tests.errors-report.unit_tests.skipped;
  document.querySelector('#protected-count').textContent=report.protected.files;
  for(const check of report.checks) {
    const card=node('article','check');card.dataset.check=check.id;
    const top=node('div','check-top');top.append(node('h3','',check.label),badge(check.passed));
    const detail=node('details');detail.append(node('summary','','Supporting evidence'),node('pre','',JSON.stringify(check.detail,null,2)));
    card.append(top,node('p','',explanation(check)),detail);document.querySelector('#checks').append(card);
  }
  report.knowledge.cases.forEach((result,index)=>{
    const card=node('article','case');
    const top=node('div','case-top');top.append(node('h3','',`${index+1}. ${result.question}`),badge(result.passed));
    const detail=node('details');detail.append(node('summary','','Read returned OKF knowledge'),node('pre','',result.markdown));
    card.append(top,node('code','case-source',result.document || 'No supplying concept'),detail);
    document.querySelector('#cases').append(card);
  });
  for(const result of report.knowledge.unsupported) {
    const row=node('div','unsupported-row');row.append(node('p','',result.question),node('p','',result.markdown),badge(result.passed));
    document.querySelector('#unsupported').append(row);
  }
  document.querySelector('#loading').hidden=true;document.querySelector('#report').hidden=false;
}
load().catch(error=>{const loading=document.querySelector('#loading');loading.className='load-error';loading.textContent=error.message;});
