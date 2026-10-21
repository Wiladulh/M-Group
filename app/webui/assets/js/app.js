const $=id=>document.getElementById(id),money=n=>new Intl.NumberFormat('id-ID').format(Number(n)||0);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function formatDateTime(value){
  if(!value)return 'Belum ada interaksi';
  const m=String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  return m?m[3]+'/'+m[2]+'/'+m[1]+(m[4]?' '+m[4]+':'+m[5]: ''):String(value);
}
function table(rows,cols){if(!rows?.length)return '<p class="hint" style="padding:16px;">Belum ada data.</p>';return '<table><thead><tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c])+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
async function json(url,opt={}){
  const r=await fetch(url,{credentials:'same-origin',...opt});
  let d={};try{d=await r.json()}catch{}
  if(r.status===401 && !String(url).includes('/auth/'))showLogin('Sesi berakhir. Silakan masuk kembali.');
  return{r,d};
}

// Fungsi Kontrol Tab Aktif
function switchTab(tabName) {
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  const pane=$('tab-'+tabName); if(pane)pane.classList.add('active');
  const btn=document.querySelector('.tab-btn[data-tab="'+tabName+'"]'); if(btn)btn.classList.add('active');
  try { sessionStorage.setItem('m-group-active-tab', tabName); } catch (_) {}
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

let selectedAnalyticsPeriod='1w';
let dashboardAccounts=[],dashboardMembers=[],dashboardPayments=[],deviceDisplayNames={};
function renderAnalytics(d){
  const rows=d.analytics||[];
  const total=rows.reduce((n,x)=>n+Number(x.transactions||0),0);
  $('analyticsSummary').textContent='Periode '+(d.analytics_period||selectedAnalyticsPeriod)+' · '+total+' transaksi berhasil';
  if(!rows.length){$('analyticsChart').innerHTML='<p class="hint">Belum ada transaksi berhasil pada periode ini.</p>';return}
  const max=Math.max(1,...rows.map(x=>Number(x.transactions||0)));
  $('analyticsChart').innerHTML='<div class="analytics-bars">'+rows.map(x=>{
    const count=Number(x.transactions||0),height=Math.max(3,Math.round(count/max*140));
    return '<div class="analytics-bar-col"><span class="analytics-bar-value">'+count+'</span><div class="analytics-bar" style="height:'+height+'px"></div><span class="analytics-bar-label">'+esc(x.bucket)+'</span></div>';
  }).join('')+'</div>';
}
async function loadDashboard(period=selectedAnalyticsPeriod){
  const {r,d}=await json('/api/v1/dashboard?period='+encodeURIComponent(period));
  if(!r.ok)throw new Error(d.detail||'Gagal memuat dashboard');
  for(const key of ['members','accounts','payments','vending_transactions','loans','machines','products','devices','analytics','most_used_vending','payment_channels']){
    if(!Array.isArray(d[key]))throw new Error('Format respons dashboard tidak valid: '+key);
  }
  deviceDisplayNames=Object.fromEntries((d.devices||[]).map(x=>[x.device_id,x.display_name||x.device_type||'Perangkat']));
  const stats=d.stats||{};
  const totalBalance=d.accounts.reduce((n,x)=>n+Number(x.balance||0),0);
  $('summary').innerHTML=[
    ['Anggota',d.members.length],['Rekening',d.accounts.length],['Saldo member',money(totalBalance)],
    ['Pembayaran terbaru',d.payments.length],['Pinjaman',d.loans.length],['Mesin vending',d.machines.length],
    ['Perangkat',d.devices.length],['Cashier masuk hari ini',money(stats.cashier_money_in_today)],
    ['Cashier keluar hari ini',money(stats.cashier_money_out_today)],['Vending masuk hari ini',money(stats.vending_money_in_today)]
  ].map(x=>'<div class="card"><div class="label">'+esc(x[0])+'</div><div class="value">'+esc(x[1])+'</div></div>').join('');
  const recent=[
    ...d.payments.map(x=>({...x,source:x.transaction_source||'PAYMENT',transaction_type:'PAYMENT'})),
    ...d.vending_transactions.map(x=>({...x,source:'VENDING',transaction_type:'PURCHASE'}))
  ].sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||''))).slice(0,12);
  $('recentTransactions').innerHTML=table(recent.map(x=>({
    created_at:x.created_at,source:x.source,transaction_id:x.transaction_id,
    Perangkat:deviceDisplayNames[x.device_id]||x.machine_name||'Vending',account_id:x.account_id,
    transaction_type:x.transaction_type,amount:money(x.final_amount??x.amount),status:x.status
  })),['created_at','source','transaction_id','Perangkat','account_id','transaction_type','amount','status']);
  renderAnalytics(d);
  dashboardMembers=d.members;
  dashboardAccounts=d.accounts;
  const memberSelect=$('payMember'),currentMember=memberSelect.value;
  const activeMembers=dashboardMembers.filter(x=>x.status==='active');
  memberSelect.innerHTML='<option value="">Pilih Nasabah</option>'+activeMembers.map(x=>'<option value="'+esc(x.member_id)+'">'+esc(x.member_id)+' — '+esc(x.name)+'</option>').join('');
  if(activeMembers.some(x=>x.member_id===currentMember))memberSelect.value=currentMember;
  else if(activeMembers.length)memberSelect.value=activeMembers[0].member_id;
  await loadPaymentMemberData(memberSelect.value);
  $('mostUsedVending').innerHTML=table(d.most_used_vending.map(x=>({...x})),['name','machine_id','transactions']);
  $('paymentChannels').innerHTML=table(d.payment_channels.map(x=>({...x,amount:money(x.amount)})),['method','transactions','amount']);
  $('accounts').innerHTML=table(d.accounts.map(x=>({...x,balance:money(x.balance)})),['account_id','member_name','account_type','balance','status']);
  dashboardAccounts=d.accounts;
  const accountSelect=$('account'),currentAccount=accountSelect.value;
  accountSelect.innerHTML='<option value="">Pilih Nasabah</option>'+d.accounts.map(x=>'<option value="'+esc(x.account_id)+'">'+esc(x.member_name)+' — saldo Rp '+money(x.balance)+'</option>').join('');
  if(d.accounts.some(x=>x.account_id===currentAccount))accountSelect.value=currentAccount;
  else if(d.accounts.length)accountSelect.value=d.accounts[0].account_id;
  await loadFinancialLedger();
  await loadMemberList();
  dashboardPayments=d.payments;renderPaymentTransactions();
  $('loans').innerHTML=table(d.loans.map(x=>({...x,principal:money(x.principal),installment_amount:money(x.installment_amount),remaining_balance:money(x.remaining_balance)})),['loan_id','member_id','principal','installment_amount','remaining_balance','status']);
  $('machines').innerHTML=table(d.machines,['machine_id','name','status','last_seen']);
  $('devices').innerHTML=table(d.devices.map(x=>({location:x.display_name||'—',device_type:x.device_type,status:x.status,last_seen:x.last_seen})),['location','device_type','status','last_seen']);
  $('dashboardResult').textContent='Data dashboard berhasil dimuat.';
}
async function load(){
 try{
  const h=await fetch('/api/v1/health').then(r=>{if(!r.ok)throw new Error('health_http_'+r.status);return r.json()});
  $('status').textContent='● '+(h.status||'online');
  await loadDashboard(selectedAnalyticsPeriod);
 }catch(e){
  console.error('M-Group WebUI load failed:',e);
  $('status').textContent='● Gagal memuat WebUI/API';
  const result=$('dashboardResult');if(result)result.textContent=e.message||'Gagal memuat data.';
 }
}
$('dashboardForm').onsubmit=async e=>{e.preventDefault();await load()};
async function loadMembers(){
  const q={name:$('memberName').value.trim(),nik:$('memberNik').value.trim(),address:$('memberAddress').value.trim()||null,
    birth_place:$('memberBirthPlace').value.trim()||null,birth_date:$('memberBirthDate').value||null,sex:$('memberSex').value||null,
    rt:$('memberRt').value.trim()||null,rw:$('memberRw').value.trim()||null,village:$('memberVillage').value.trim()||null,
    district:$('memberDistrict').value.trim()||null,city_regency:$('memberCity').value.trim()||null,province:$('memberProvince').value.trim()||null,
    religion:$('memberReligion').value.trim()||null,marital_status:$('memberMarital').value.trim()||null,occupation:$('memberOccupation').value.trim()||null,
    citizenship:$('memberCitizenship').value.trim()||null,phone:$('memberPhone').value.trim()||null,email:$('memberEmail').value.trim()||null,
    registration_date:$('memberRegistrationDate').value||null};
  try{
    const id=$('memberId').value.trim();
    const url=id?'/api/v1/members/'+encodeURIComponent(id):'/api/v1/members';
    const {r,d}=await json(url,{method:id?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(id?{...q,status:$('memberStatus').value}:q)});
    if(!r.ok)throw new Error(d.detail||'Gagal menyimpan member');
    if(!id&&d.member_id)$('memberId').value=d.member_id;
    $('memberAuthResult').textContent='Member '+(d.member_id||id)+' berhasil disimpan.';
    await loadMemberList();
  }catch(e){$('memberAuthResult').textContent=e.message}
}
let memberListRows=[];
function renderMemberRows(){
  const search=($('memberSearch')?.value||'').trim().toLowerCase();
  const status=$('memberStatusFilter')?.value||'ALL';
  const rows=memberListRows.filter(x=>(status==='ALL'||String(x.status).toLowerCase()===status)&&(!search||[x.member_id,x.name,x.nik].some(v=>String(v||'').toLowerCase().includes(search))));
  $('members').innerHTML=rows.length?'<table><thead><tr><th>Member ID</th><th>Nama</th><th>NIK</th><th>No. HP</th><th>Credential NFC</th><th>Interaksi Terakhir</th><th>Status Akun</th><th>Aksi</th></tr></thead><tbody>'+rows.map(x=>'<tr><td>'+esc(x.member_id)+'</td><td>'+esc(x.name)+'</td><td>'+esc(x.nik||'—')+'</td><td>'+esc(x.phone||'—')+'</td><td>'+esc(x.nfc_credential_status||'—')+'</td><td>'+esc(formatDateTime(x.last_interaction_at))+'</td><td>'+esc(x.status)+'</td><td><button type="button" data-member-action="edit" data-member-id="'+esc(x.member_id)+'">Edit</button> <button type="button" data-member-action="nfc" data-member-id="'+esc(x.member_id)+'">Daftar/Ganti NFC</button> <button type="button" data-member-action="pin" data-member-id="'+esc(x.member_id)+'">Reset PIN</button> <button type="button" data-member-action="correction" data-member-id="'+esc(x.member_id)+'">Koreksi Top Up</button></td></tr>').join('')+'</tbody></table>':'<p class="hint" style="padding:16px;">Belum ada member terdaftar.</p>';
}
$('memberSearch').oninput=renderMemberRows;
$('memberStatusFilter').onchange=renderMemberRows;

async function loadMemberList(){
  const {r,d}=await json('/api/v1/members',{});
  if(r.ok){
    memberListRows=d.members||[];
    renderMemberRows();
    await loadNfcCashiers();
  }
}
$('memberForm').onsubmit=async e=>{e.preventDefault();await loadMembers()};
$('members').addEventListener('click',async e=>{
  const b=e.target.closest('button[data-member-action]');if(!b)return;
  const memberId=b.dataset.memberId,action=b.dataset.memberAction;
  try{
    if(action==='edit'){
      const {r,d}=await json('/api/v1/members/'+encodeURIComponent(memberId),{});
      if(!r.ok)throw new Error(d.detail||'Gagal membaca anggota');
      const m=d;$('memberId').value=m.member_id;$('memberName').value=m.name||'';$('memberNik').value=m.nik||'';
      $('memberAddress').value=m.address||'';$('memberBirthPlace').value=m.birth_place||'';$('memberBirthDate').value=m.birth_date||'';
      $('memberSex').value=m.sex||'';$('memberRt').value=m.rt||'';$('memberRw').value=m.rw||'';$('memberVillage').value=m.village||'';
      $('memberDistrict').value=m.district||'';$('memberCity').value=m.city_regency||'';$('memberProvince').value=m.province||'';
      $('memberReligion').value=m.religion||'';$('memberMarital').value=m.marital_status||'';$('memberOccupation').value=m.occupation||'';
      $('memberCitizenship').value=m.citizenship||'WNI';$('memberPhone').value=m.phone||'';$('memberEmail').value=m.email||'';
      $('memberRegistrationDate').value=m.registration_date||'';$('memberStatus').value=m.status||'active';
      $('memberAuthResult').textContent='Mode edit: '+memberId+'. Simpan perubahan melalui tombol Simpan Member.';
      $('memberForm').scrollIntoView({behavior:'smooth',block:'start'});
    }else if(action==='pin'){
      const operator_id=prompt('ID petugas yang melakukan reset PIN:');if(!operator_id)return;
      if(!confirm('Pastikan identitas anggota sudah diverifikasi sesuai prosedur M-Group. Lanjut reset PIN?'))return;
      const pin=prompt('Masukkan PIN transaksi baru (4–6 digit):');if(!pin)return;
      const reason=prompt('Alasan reset PIN:');if(!reason)return;
      const {r,d}=await json('/api/v1/members/'+encodeURIComponent(memberId)+'/pin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin,operator_id,reason,identity_verified:true})});
      if(!r.ok)throw new Error(d.detail||'Reset PIN gagal');
      $('memberAuthResult').textContent='Reset PIN berhasil. PIN tidak ditampilkan atau disimpan di WebUI.';
    }else if(action==='nfc'){
      const {r,d}=await json('/api/v1/members/'+encodeURIComponent(memberId),{});
      if(!r.ok)throw new Error(d.detail||'Gagal membaca member');
      const m=d;
      $('memberId').value=m.member_id;$('memberName').value=m.name||'';$('memberNik').value=m.nik||'';
      $('memberAddress').value=m.address||'';$('memberBirthPlace').value=m.birth_place||'';$('memberBirthDate').value=m.birth_date||'';
      $('memberSex').value=m.sex||'';$('memberRt').value=m.rt||'';$('memberRw').value=m.rw||'';$('memberVillage').value=m.village||'';
      $('memberDistrict').value=m.district||'';$('memberCity').value=m.city_regency||'';$('memberProvince').value=m.province||'';
      $('memberReligion').value=m.religion||'';$('memberMarital').value=m.marital_status||'';$('memberOccupation').value=m.occupation||'';
      $('memberCitizenship').value=m.citizenship||'WNI';$('memberPhone').value=m.phone||'';$('memberEmail').value=m.email||'';
      $('memberRegistrationDate').value=m.registration_date||'';$('memberStatus').value=m.status||'active';
      $('nfcRegistrationResult').textContent='Member terpilih. Pilih Cashier, lalu tekan “Scan / Ganti Kartu NFC”.';
      $('memberForm').scrollIntoView({behavior:'smooth',block:'start'});
    }else if(action==='correction'){
      const operator_id=prompt('ID petugas yang melakukan koreksi:');if(!operator_id)return;
      const original_transaction_id=prompt('Referensi/ID transaksi Top Up asli:');if(!original_transaction_id)return;
      const corrected_amount=Number(prompt('Nominal Top Up yang benar (rupiah):'));if(!Number.isSafeInteger(corrected_amount)||corrected_amount<=0)throw new Error('Nominal koreksi tidak valid');
      const reason=prompt('Alasan koreksi (minimal 5 karakter):');if(!reason)return;
      if(!confirm('Konfirmasi koreksi transaksi Top Up '+original_transaction_id+' ke nominal '+money(corrected_amount)+'?'))return;
      const idempotency_key='member-correction-'+(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+Math.random().toString(36).slice(2));
      const {r,d}=await json('/api/v1/members/'+encodeURIComponent(memberId)+'/topup-corrections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operator_id,original_transaction_id,corrected_amount,reason,idempotency_key})});
      if(!r.ok)throw new Error(d.detail||'Koreksi Top Up gagal');
      $('memberAuthResult').textContent='Koreksi tercatat. Nominal sebelum: '+money(d.original_amount)+'; sesudah: '+money(d.corrected_amount)+'.';
      await load();
    }
  }catch(err){$('memberAuthResult').textContent=err.message}
});

let nfcPollTimer=null;
async function loadNfcCashiers(){
  const sel=$('nfcCashierDevice');
  if(!sel)return;
  const {r,d}=await json('/api/v1/devices',{});
  if(!r.ok){sel.innerHTML='<option value="">Gagal memuat Cashier</option>';return}
  const rows=(d.devices||[]).filter(x=>x.device_type==='esp32-cashier'&&x.status==='active');
  sel.innerHTML=rows.length?'<option value="">Pilih Cashier</option>'+rows.map(x=>'<option value="'+esc(x.device_id)+'">'+esc(x.display_name||'Lokasi belum ditentukan')+'</option>').join(''):'<option value="">Tidak ada Cashier aktif</option>';
}
async function pollNfcRegistration(memberId,sessionId){
  clearInterval(nfcPollTimer);
  const check=async()=>{
    const {r,d}=await json('/api/v1/members/'+encodeURIComponent(memberId)+'/nfc-registration/'+encodeURIComponent(sessionId),{});
    if(!r.ok){$('nfcRegistrationResult').textContent=d.detail||'Gagal membaca status registrasi NFC';clearInterval(nfcPollTimer);return}
    if(d.status==='scan_pending')$('nfcRegistrationResult').textContent='Cashier terpilih: silakan scan kartu NFC, lalu Nasabah memasukkan PIN transaksi 4 digit. Menunggu hasil...';
    else if(d.status==='completed'){
      $('nfcRegistrationResult').textContent='Registrasi NFC berhasil. UID kartu dan verifikasi PIN telah diproses server.';
      clearInterval(nfcPollTimer);
      await loadMemberList();
    }else{
      $('nfcRegistrationResult').textContent='Status registrasi NFC: '+d.status;
      if(d.status==='expired'||d.status==='failed')clearInterval(nfcPollTimer);
    }
  };
  await check();
  nfcPollTimer=setInterval(check,2000);
}
$('nfcStart').onclick=async()=>{
  try{
  const memberId=$('memberId').value.trim(),deviceId=$('nfcCashierDevice').value.trim();
    if(!memberId)throw new Error('Simpan atau pilih member terlebih dahulu');
    if(!deviceId)throw new Error('Pilih Cashier aktif terlebih dahulu');
    const memberResponse=await json('/api/v1/members/'+encodeURIComponent(memberId),{});
    if(!memberResponse.r.ok)throw new Error(memberResponse.d.detail||'Member belum tersimpan di server');
    const hasActiveCard=(memberResponse.d.nfc_cards||[]).some(card=>card.status==='active');
    let endpoint='/api/v1/members/'+encodeURIComponent(memberId)+'/nfc-registration/start';
    let body={cashier_device_id:deviceId};
    if(hasActiveCard){
      const operator_id=prompt('ID petugas yang melakukan penggantian kartu:');if(!operator_id)return;
      if(!confirm('Kartu lama akan dicabut setelah kartu baru berhasil didaftarkan. Lanjutkan?'))return;
      endpoint='/api/v1/members/'+encodeURIComponent(memberId)+'/nfc-replacement/start';
      body={cashier_device_id:deviceId,operator_id};
    }
    const {r,d}=await json(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok)throw new Error(d.detail||'Gagal memulai registrasi NFC');
    $('nfcRegistrationResult').textContent='Sesi registrasi dimulai. Cashier terpilih akan meminta member scan kartu dan memasukkan PIN 4 digit.';
    await pollNfcRegistration(memberId,d.session_id);
  }catch(e){$('nfcRegistrationResult').textContent=e.message}
};

async function loadDevices(){
  try{
    const {r,d}=await json('/api/v1/devices',{});
    if(!r.ok)throw new Error(d.detail||'Gagal memuat perangkat');
    $('deviceAuthResult').textContent='Data perangkat berhasil dimuat.';
    const rows=(d.devices||[]);
    if(!rows.length){$('devices').innerHTML='<p class="hint" style="padding:16px;">Belum ada perangkat terdaftar.</p>';return}
    $('devices').innerHTML='<table><thead><tr><th>Device Location</th><th>Jenis perangkat</th><th>Status</th><th>Last Seen</th><th>Aksi</th></tr></thead><tbody>'+
      rows.map(x=>'<tr>'+
        '<td><input data-device-name="'+esc(x.device_id)+'" value="'+esc(x.display_name||'')+'" placeholder="Contoh: Depan sekolah" aria-label="Device Location"></td>'+
        '<td>'+esc(x.device_type==='esp32-cashier'?'Cashier':x.device_type.includes('vending')?'Vending':x.device_type)+'</td>'+
        '<td><select data-device-status="'+esc(x.device_id)+'">'+['pending','active','offline','maintenance','unassigned','disabled'].map(s=>'<option value="'+s+'"'+(x.status===s?' selected':'')+'>'+s+'</option>').join('')+'</select></td>'+
        '<td>'+esc(x.last_seen||'—')+'</td>'+
        '<td><button type="button" data-device-save="'+esc(x.device_id)+'">Simpan</button></td>'+
      '</tr>').join('')+'</tbody></table>';
    document.querySelectorAll('[data-device-save]').forEach(b=>b.onclick=()=>saveDevice(b.dataset.deviceSave));
  }catch(e){$('deviceAuthResult').textContent=e.message}
}
async function saveDevice(deviceId){
  const name=document.querySelector('[data-device-name="'+CSS.escape(deviceId)+'"]').value.trim();
  const status=document.querySelector('[data-device-status="'+CSS.escape(deviceId)+'"]').value;
  if(!name){$('deviceAuthResult').textContent='Nama perangkat wajib diisi';return}
  try{
    const current=await json('/api/v1/devices/'+encodeURIComponent(deviceId),{});
    if(!current.r.ok)throw new Error(current.d.detail||'Gagal membaca perangkat');
    const q={device_type:current.d.device_type,status:status,display_name:name};
    const {r,d}=await json('/api/v1/devices/'+encodeURIComponent(deviceId),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(q)});
    if(!r.ok)throw new Error(d.detail||'Gagal menyimpan perangkat');
    $('deviceAuthResult').textContent='Perangkat berhasil diperbarui.';
    await loadDevices();
  }catch(e){$('deviceAuthResult').textContent=e.message}
}
$('deviceAuthForm').onsubmit=async e=>{e.preventDefault();await loadDevices()};
$('deviceProvisionForm').onsubmit=async e=>{
  e.preventDefault();
  const deviceType=$('provisionDeviceType').value;
  const result=$('deviceProvisionResult');
  const displayName=$('provisionDeviceLocation').value.trim();
  if(!displayName){result.textContent='Device Location wajib diisi sebelum membuat key.';return}
  if(!confirm('Generate key autentikasi untuk '+(deviceType==='esp32-cashier'?'Cashier':'Vending')+' di lokasi "'+displayName+'"?'))return;
  const {r,d}=await json('/api/v1/devices/provision',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({device_type:deviceType,display_name:displayName})
  });
  if(!r.ok){result.textContent=d.detail||'Gagal membuat device key.';return}
  $('provisionedDeviceKey').value=d.device_key;
  $('provisionedDeviceKey').type='password';
  result.textContent='Key autentikasi dibuat untuk lokasi '+displayName+'. Salin key ke WebUI perangkat; key hanya ditampilkan satu kali.';
  await loadDevices();
};
$('toggleDeviceKey').onclick=()=>{
  const input=$('provisionedDeviceKey');
  input.type=input.type==='password'?'text':'password';
};
$('copyDeviceKey').onclick=async()=>{
  const input=$('provisionedDeviceKey');
  if(!input.value){$('deviceProvisionResult').textContent='Belum ada key untuk disalin.';return}
  try{
    if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(input.value);
    else {input.type='text';input.select();document.execCommand('copy');input.type='password'}
    $('deviceProvisionResult').textContent='Device key disalin. Simpan di tempat rahasia.';
  }catch(e){input.type='text';input.select();$('deviceProvisionResult').textContent='Pilih dan salin key secara manual.'}
};

async function loadFinancialLedger(){
  const accountId=$('account')?.value;
  const {r,d}=await json('/api/v1/accounts/'+encodeURIComponent(accountId)+'/ledger?limit=100',{});
  $('financialLedger').innerHTML=r.ok?table((d.entries||[]).map(x=>({...x,amount:money(x.amount)})),['created_at','direction','amount','reference','id']):'<p class="hint" style="padding:12px">'+esc(d.detail||'Gagal memuat ledger')+'</p>';
}
$('account').onchange=loadFinancialLedger;
$('financialForm').onsubmit=async e=>{
  e.preventDefault();
  const accountId=$('account').value,amount=Number($('amount').value),direction=$('direction').value,reference=$('reference').value.trim();
  if(!accountId){$('financialResult').textContent='Pilih rekening terlebih dahulu.';return}
  if(!Number.isSafeInteger(amount)||amount<=0){$('financialResult').textContent='Nominal harus berupa rupiah bulat lebih besar dari 0.';return}
  if(!reference){$('financialResult').textContent='Referensi transaksi wajib diisi.';return}
  const action=direction==='credit'?'KREDIT / TOP-UP':'DEBIT / PENARIKAN';
  const nonce=window.crypto?.randomUUID?.()||(Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
  const selectedAccount=dashboardAccounts.find(x=>x.account_id===accountId);
  const memberLabel=selectedAccount?.member_name||accountId;
  if(!confirm('Konfirmasi '+action+' sebesar Rp '+money(amount)+' untuk '+memberLabel+'?'))return;
  const q={amount,reference,idempotency_key:'webui-financial:'+nonce};
  const {r,d}=await json('/api/v1/accounts/'+encodeURIComponent(accountId)+'/'+direction,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(q)
  });
  $('financialResult').textContent=JSON.stringify(d,null,2);
  if(r.ok){await load();await loadFinancialLedger()}
};
async function loadPaymentMemberData(memberId){
  const credentialSelect=$('credential'),accountSelect=$('payaccount');
  if(!memberId){credentialSelect.innerHTML='<option value="">Pilih Nasabah terlebih dahulu</option>';accountSelect.innerHTML='<option value="">Pilih Nasabah terlebih dahulu</option>';return}
  const accounts=dashboardAccounts.filter(x=>x.member_id===memberId&&x.status==='active');
  const currentAccount=accountSelect.value;
  accountSelect.innerHTML=accounts.length?accounts.map(x=>'<option value="'+esc(x.account_id)+'">'+esc(x.account_id)+' · '+money(x.balance)+'</option>').join(''):'<option value="">Tidak ada rekening aktif</option>';
  if(accounts.some(x=>x.account_id===currentAccount))accountSelect.value=currentAccount;
  const {r,d}=await json('/api/v1/members/'+encodeURIComponent(memberId),{});
  if(!r.ok){credentialSelect.innerHTML='<option value="">Gagal memuat kartu</option>';return}
  const cards=(d.nfc_cards||[]).filter(x=>x.status==='active'&&x.credential_id);
  credentialSelect.innerHTML=cards.length?cards.map(x=>'<option value="'+esc(x.credential_id)+'">'+esc(x.credential_id)+' · '+esc(x.card_uid||'NFC')+'</option>').join(''):'<option value="">Tidak ada kartu NFC aktif</option>';
}
$('payMember').onchange=()=>loadPaymentMemberData($('payMember').value);
function renderPaymentTransactions(){
  if(!$('payments'))return;
  const search=($('paymentSearch')?.value||'').trim().toLowerCase();
  const method=$('paymentMethodFilter')?.value||'ALL',statusFilter=$('paymentStatusFilter')?.value||'ALL';
  const rows=dashboardPayments.filter(x=>(method==='ALL'||String(x.method||'').toUpperCase()===method)&&(statusFilter==='ALL'||String(x.status||'').toLowerCase()===statusFilter)&&(!search||[x.transaction_id,x.account_id,x.device_id,x.credential_id].some(v=>String(v||'').toLowerCase().includes(search))));
  $('payments').innerHTML=table(rows.map(x=>({...x,perangkat:deviceDisplayNames[x.device_id]||'—',amount:money(x.final_amount??x.amount)})),['transaction_id','account_id','amount','method','provider','perangkat','status','created_at']);
}
$('paymentSearch').oninput=renderPaymentTransactions;
$('paymentMethodFilter').onchange=renderPaymentTransactions;
$('paymentStatusFilter').onchange=renderPaymentTransactions;
$('paymentForm').onsubmit=async e=>{
  e.preventDefault();
  const method=$('method').value,pin=$('paypin').value;
  if(method==='NFC'&&!pin){$('paymentResult').textContent='PIN Nasabah wajib diisi untuk pembayaran NFC';return}
  const accountId=$('payaccount').value,credentialId=$('credential').value,amount=Number($('payamount').value);
  if(!accountId||!credentialId){$('paymentResult').textContent='Pilih Nasabah, kartu NFC aktif, dan rekening.';return}
  if(!Number.isSafeInteger(amount)||amount<=0){$('paymentResult').textContent='Nominal harus berupa rupiah bulat lebih besar dari 0.';return}
  if(!confirm('Konfirmasi pembayaran '+money(amount)+' dari rekening '+accountId+' melalui '+method+'?'))return;
  let idem=$('idem').value.trim();
  if(!idem){idem='webui-payment:'+(window.crypto?.randomUUID?.()||(Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)));$('idem').value=idem}
  const q={credential_id:credentialId,account_id:accountId,amount,method,provider:$('provider').value||'local',idempotency_key:idem,pin:pin||null};
  const {r,d}=await json('/api/v1/payments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(q)});
  $('paymentResult').textContent=JSON.stringify(d,null,2);
  if(r.ok){$('paypin').value='';$('idem').value='';await load()}
};
let vendingCatalog=[];
async function loadVendingCatalog(machineId){
  if(!machineId)return;
  const {r,d}=await json('/api/v1/vending/'+encodeURIComponent(machineId)+'/products',{});
  if(!r.ok)throw new Error(d.detail||'Gagal memuat katalog vending');
  vendingCatalog=d.products||[];
  $('products').innerHTML='<table><thead><tr><th>Gambar</th><th>Product ID</th><th>Nama</th><th>Harga</th><th>Stok</th><th>Kapasitas</th><th>Aktif</th></tr></thead><tbody>'+vendingCatalog.map(x=>'<tr><td>'+(x.image_url?'<img src="'+esc(x.image_url)+'" alt="Gambar '+esc(x.name||'produk')+'" style="width:64px;height:64px;object-fit:contain">':'—')+'</td><td>'+esc(x.product_id)+'</td><td>'+esc(x.name||'')+'</td><td>'+esc(money(x.price))+'</td><td>'+esc(x.stock)+'</td><td>'+esc(x.capacity)+'</td><td>'+(x.enabled?'ya':'tidak')+'</td></tr>').join('')+'</tbody></table>';
  $('productId').dispatchEvent(new Event('change'));
}
async function loadVendingMachines(){
  try{
    const {r,d}=await json('/api/v1/vending',{});
    if(!r.ok)throw new Error(d.detail||'Gagal memuat daftar mesin');
    const rows=d.machines||[],sel=$('machineId'),current=sel.value;
    sel.innerHTML='<option value="">Pilih mesin</option>'+rows.map(x=>'<option value="'+esc(x.machine_id)+'">'+esc(x.location||x.name||'Lokasi belum ditentukan')+' ('+esc(x.status)+')</option>').join('');
    if(rows.some(x=>x.machine_id===current))sel.value=current;
    else if(rows.length)sel.value=rows[0].machine_id;
    if(sel.value){await loadVendingCatalog(sel.value);await loadVendingTransactions(sel.value)}
    $('productResult').textContent=rows.length?'Daftar mesin berhasil dimuat.':'Belum ada vending machine terdaftar.';
  }catch(e){$('productResult').textContent=e.message}
}
$('loadVendingMachines').onclick=loadVendingMachines;
$('machineId').onchange=async()=>{try{await loadVendingCatalog($('machineId').value);await loadVendingTransactions($('machineId').value)}catch(e){$('productResult').textContent=e.message}};
let productImageObjectUrl=null;
function renderProductImage(item){
  if(productImageObjectUrl){URL.revokeObjectURL(productImageObjectUrl);productImageObjectUrl=null}
  const file=$('productImage').files?.[0];
  if(file){
    productImageObjectUrl=URL.createObjectURL(file);
    $('productImagePreview').innerHTML='<img alt="Pratinjau gambar produk" src="'+productImageObjectUrl+'" style="max-width:180px;max-height:180px;object-fit:contain">';
  }else if(item?.image_url){
    $('productImagePreview').innerHTML='<img alt="Gambar produk saat ini" src="'+esc(item.image_url)+'" style="max-width:180px;max-height:180px;object-fit:contain">';
  }else{
    $('productImagePreview').textContent='Belum ada gambar produk.';
  }
}
$('productId').onchange=()=>{
  const item=vendingCatalog.find(x=>String(x.product_id)===$('productId').value);
  $('productName').value=item?.name||'';
  $('productPrice').value=item?.price??'';
  $('productStock').value=item?.stock??0;
  $('productCapacity').value=item?.capacity??0;
  $('productEnabled').checked=item?!!item.enabled:true;
  $('productImage').value='';
  renderProductImage(item);
};
$('productImage').onchange=()=>{
  const file=$('productImage').files?.[0];
  if(file && file.size>2*1024*1024){$('productImage').value='';$('productResult').textContent='Ukuran gambar maksimum 2 MB.';}
  renderProductImage(vendingCatalog.find(x=>String(x.product_id)===$('productId').value));
};
$('removeProductImage').onclick=async()=>{
  const mid=$('machineId').value.trim(),pid=$('productId').value.trim();
  if(!mid||!pid){$('productResult').textContent='Pilih mesin dan produk terlebih dahulu.';return}
  const item=vendingCatalog.find(x=>String(x.product_id)===pid);
  if(!item?.image_url){$('productImage').value='';renderProductImage(item);$('productResult').textContent='Produk ini belum memiliki gambar.';return}
  if(!confirm('Hapus gambar produk ini?'))return;
  const {r,d}=await json('/api/v1/vending/'+encodeURIComponent(mid)+'/products/'+encodeURIComponent(pid)+'/image',{method:'DELETE'});
  $('productResult').textContent=r.ok?'Gambar produk dihapus.':(d.detail||'Gagal menghapus gambar.');
  if(r.ok)await loadVendingCatalog(mid);
};
$('productForm').onsubmit=async e=>{
  e.preventDefault();
  const mid=$('machineId').value.trim(),pid=$('productId').value.trim();
  if(!mid||!pid){$('productResult').textContent='Muat daftar mesin lalu pilih mesin dan Product ID';return}
  const q={product_id:pid,name:$('productName').value.trim(),price:+$('productPrice').value,stock:+$('productStock').value,enabled:$('productEnabled').checked,capacity:+$('productCapacity').value};
  const {r,d}=await json('/api/v1/vending/'+encodeURIComponent(mid)+'/products/'+encodeURIComponent(pid),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(q)});
  if(!r.ok){$('productResult').textContent=d.detail||'Gagal menyimpan produk';return}
  const file=$('productImage').files?.[0];
  if(file){
    if(file.size>2*1024*1024){$('productResult').textContent='Ukuran gambar maksimum 2 MB.';return}
    const form=new FormData();form.append('image',file);
    const upload=await json('/api/v1/vending/'+encodeURIComponent(mid)+'/products/'+encodeURIComponent(pid)+'/image',{method:'PUT',body:form});
    if(!upload.r.ok){$('productResult').textContent='Data produk tersimpan, tetapi gambar gagal diunggah: '+(upload.d.detail||'kesalahan upload');return}
  }
  $('productImage').value='';
  $('productResult').textContent=file?'Produk dan gambar berhasil disimpan.':'Produk berhasil disimpan.';
  await loadVendingCatalog(mid);await load();
};
let vendingTransactions=[];
async function loadVendingTransactions(machineId){
  const {r,d}=await json('/api/v1/vending/'+encodeURIComponent(machineId)+'/transactions?limit=100',{
    
  });
  if(!r.ok){$('vendingTxnResult').textContent=d.detail||'Gagal memuat riwayat transaksi vending';return}
  vendingTransactions=d.transactions||[];
  renderVendingTransactions();
}
function renderVendingTransactions(){
  const statusFilter=$('vendingTxnStatus').value,productFilter=$('vendingTxnProduct').value;
  const rows=vendingTransactions.filter(x=>(statusFilter==='ALL'||String(x.status).toLowerCase()===statusFilter)&&(productFilter==='ALL'||String(x.product_id)===productFilter));
  $('vendingTxnResult').innerHTML=table(rows.map(x=>({...x,amount:money(x.amount),dispense_status:x.dispense_status||'—'})),['created_at','transaction_id','product_id','account_id','amount','status','dispense_status','completed_at']);
}
$('loadVendingTransactions').onclick=()=>loadVendingTransactions($('machineId').value);
$('vendingTxnStatus').onchange=renderVendingTransactions;
$('vendingTxnProduct').onchange=renderVendingTransactions;

async function loadCashierTransactions(){
  const period=$('cashierPeriod').value;
  const {r,d}=await json('/api/v1/audit/report?source=CASHIER&period='+encodeURIComponent(period),{
    
  });
  if(!r.ok){$('cashierResult').textContent=d.detail||'Gagal memuat transaksi Cashier';return}
  const rows=d.transactions||[];
  const deviceSelect=$('cashierDevice');
  if(deviceSelect){
    const current=deviceSelect.value;
    const devices=[...new Set(rows.map(x=>x.device_id).filter(Boolean))].sort();
    deviceSelect.innerHTML='<option value="ALL">Semua Cashier</option>'+devices.map(x=>'<option value="'+esc(x)+'">'+esc(deviceDisplayNames[x]||'Cashier')+'</option>').join('');
    if(devices.includes(current))deviceSelect.value=current;
  }
  const device=deviceSelect?.value||'ALL',type=$('cashierType').value,statusFilter=$('cashierStatus').value;
  const filtered=rows.filter(x=>(device==='ALL'||x.device_id===device)&&(type==='ALL'||x.transaction_type===type)&&(statusFilter==='ALL'||String(x.status).toLowerCase()===statusFilter));
  const completed=filtered.filter(x=>String(x.status).toLowerCase()==='completed');
  const incoming=completed.filter(x=>x.transaction_type==='DEPOSIT').reduce((n,x)=>n+Number(x.amount||0),0);
  const outgoing=completed.filter(x=>x.transaction_type==='PAYMENT').reduce((n,x)=>n+Number(x.amount||0),0);
  $('cashierMetrics').innerHTML=[['Transaksi',filtered.length],['Penerimaan berhasil',money(incoming)],['Pembayaran berhasil',money(outgoing)],['Netto',money(incoming-outgoing)]].map(x=>'<div class="card"><div class="label">'+esc(x[0])+'</div><div class="value">'+esc(x[1])+'</div></div>').join('');
  $('cashierResult').innerHTML=table(filtered.map(x=>({...x,perangkat:deviceDisplayNames[x.device_id]||'Cashier',amount:money(x.amount)})),['created_at','transaction_id','perangkat','member_id','account_id','transaction_type','amount','status']);
  $('cashierDetail').textContent='Sumber: server M-Group. Nilai netto dihitung hanya dari transaksi berstatus completed.';
}
$('cashierForm').onsubmit=async e=>{e.preventDefault();await loadCashierTransactions()};
$('cashierDevice').onchange=loadCashierTransactions;
$('cashierType').onchange=loadCashierTransactions;
$('cashierStatus').onchange=loadCashierTransactions;
$('cashierPeriod').onchange=loadCashierTransactions;

$('accountSettings').onsubmit=async e=>{
  e.preventDefault();
  const currentPassword=$('currentAdminPassword').value;
  const username=$('newAdminUsername').value.trim();
  const newPassword=$('newAdminPassword').value;
  const confirmPassword=$('confirmAdminPassword').value;
  const result=$('accountSettingsResult');
  if(newPassword && newPassword!==confirmPassword){result.textContent='Konfirmasi password baru tidak cocok.';return}
  if(!newPassword && confirmPassword){result.textContent='Isi password baru atau kosongkan kedua kolom password baru.';return}
  const {r,d}=await json('/api/v1/auth/account',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({current_password:currentPassword,username,new_password:newPassword||null})
  });
  if(!r.ok){result.textContent=d.detail==='invalid_current_password'?'Password saat ini salah.':d.detail==='password_too_short'?'Password baru minimal 8 karakter.':d.detail==='invalid_admin_username'?'Username harus 3–64 karakter (huruf, angka, titik, garis bawah, atau tanda hubung).':d.detail||'Gagal menyimpan akun.';return}
  $('activeUsername').textContent=d.username;
  $('newAdminUsername').value=d.username;
  $('currentAdminPassword').value='';
  $('newAdminPassword').value='';
  $('confirmAdminPassword').value='';
  result.textContent=d.password_changed?'Akun dan password berhasil diperbarui. Sesi admin lain sudah dicabut.':'Username berhasil diperbarui. Sesi admin lain sudah dicabut.';
};
$('settingsLogout').onclick=()=>$('logoutButton').click();

async function loadAudit(){
  try{
    const source=$('auditSource').value, period=$('auditPeriod').value, date=$('auditDate').value, method=$('auditMethod').value;
    const q='?source='+encodeURIComponent(source)+'&period='+encodeURIComponent(period)+'&method='+encodeURIComponent(method)+(date?'&date='+encodeURIComponent(date):'');
    const {r,d}=await json('/api/v1/audit/report'+q,{});
    $('auditResult').innerHTML=r.ok?table((d.transactions||[]).map(x=>({...x,amount:money(x.amount)})),['transaction_id','created_at','source','member_id','account_id','transaction_type','payment_method','payment_provider','amount','status']):'<p class="hint" style="padding:16px">'+esc(d.detail||'Audit gagal')+'</p>';
  }catch(e){$('auditResult').textContent=e.message}
}
$('auditForm').onsubmit=async e=>{e.preventDefault();await loadAudit()};
$('auditExport').onclick=async()=>{
  try{
    const source=$('auditSource').value,period=$('auditPeriod').value,date=$('auditDate').value,method=$('auditMethod').value;
    const q='?source='+encodeURIComponent(source)+'&period='+encodeURIComponent(period)+'&method='+encodeURIComponent(method)+(date?'&date='+encodeURIComponent(date):'');
    const r=await fetch('/api/v1/audit/export.xlsx'+q,{});
    if(!r.ok)throw new Error('Export gagal: '+r.status);
    const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='M-Group-audit-'+source.toLowerCase()+'-'+method.toLowerCase()+'-'+period+'.xlsx';a.click();URL.revokeObjectURL(a.href);
  }catch(e){$('auditResult').textContent=e.message}
};
$('operatorPinForm').onsubmit=async e=>{
  e.preventDefault();
  try{
    const {r,d}=await json('/api/v1/cashier/operator-pin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:$('newOperatorPin').value})});
    $('operatorPinResult').textContent=JSON.stringify(d,null,2);
    if(r.ok)$('newOperatorPin').value='';
  }catch(e){$('operatorPinResult').textContent=e.message}
};
$('backupCreate').onclick=async()=>{
  try{
  const r=await fetch('/api/v1/backup',{method:'POST'});
    if(!r.ok)throw new Error('Backup gagal: '+r.status);
    const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='M-Group_BACKUP.mgroup.zip';a.click();URL.revokeObjectURL(a.href);
    $('backupResult').textContent='Backup berhasil dibuat.';
  }catch(e){$('backupResult').textContent=e.message}
};
$('backupRestore').onclick=async()=>{
  try{
  const file=$('restoreFile').files[0];
    if(!file)throw new Error('Pilih file .mgroup.zip terlebih dahulu');
    if(!confirm('Restore akan mengganti database aktif. Lanjutkan?'))return;
    const fd=new FormData();fd.append('file',file);
    const {r,d}=await json('/api/v1/backup/restore',{method:'POST',body:fd});
    $('backupResult').textContent=JSON.stringify(d,null,2);
    if(r.ok)setTimeout(()=>location.reload(),1000);
  }catch(e){$('backupResult').textContent=e.message}
};
document.querySelectorAll('.tab-btn').forEach(btn=>btn.addEventListener('click',()=>switchTab(btn.dataset.tab)));
const validTabs=['dashboard','member','financial','payment','vending','cashier','devices','audit','settings'];
try {
  const savedTab=sessionStorage.getItem('m-group-active-tab');
  if(validTabs.includes(savedTab)) switchTab(savedTab);
} catch (_) {}
document.querySelectorAll('[data-analytics-period]').forEach(btn=>btn.addEventListener('click',async()=>{
  selectedAnalyticsPeriod=btn.dataset.analyticsPeriod;
  document.querySelectorAll('[data-analytics-period]').forEach(x=>x.classList.toggle('active',x===btn));
  await loadDashboard(selectedAnalyticsPeriod);
}));


function showLogin(message=''){
  const screen=$('loginScreen'),shell=$('appShell');
  if(screen)screen.hidden=false;
  if(shell)shell.hidden=true;
  const error=$('loginError');if(error)error.textContent=message;
  const password=$('loginPassword');if(password)password.value='';
}
function unlockApp(username){
  $('loginScreen').hidden=true;
  $('appShell').hidden=false;
  $('activeUsername').textContent=username||'Admin';
  if($('newAdminUsername'))$('newAdminUsername').value=username||'admin';
  $('loginError').textContent='';
  load();
}
$('loginForm').onsubmit=async e=>{
  e.preventDefault();
  const error=$('loginError');
  error.textContent='Memeriksa akun...';
  const {r,d}=await json('/api/v1/auth/login',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:$('loginUsername').value.trim(),password:$('loginPassword').value})
  });
  if(!r.ok){error.textContent=d.detail==='admin_login_not_configured'?'Login belum dikonfigurasi di server.':d.detail==='login_rate_limited'?'Terlalu banyak percobaan. Coba lagi nanti.':'Username atau password salah.';return}
  $('loginPassword').value='';
  unlockApp(d.username);
};
$('logoutButton').onclick=async()=>{
  const {r,d}=await json('/api/v1/auth/logout',{method:'POST'});
  if(r.ok){showLogin('Anda sudah keluar.');$('loginUsername').focus()}
  else showLogin(d.detail||'Gagal mengakhiri sesi.');
};
async function restoreSession(){
  const {r,d}=await json('/api/v1/auth/session');
  if(r.ok)unlockApp(d.username);
  else showLogin('');
}
restoreSession();
