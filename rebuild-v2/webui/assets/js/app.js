/* M-Group clean-room v2 WebUI: real API wiring, no simulated business success. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const api = window.MGroupApiV2;
  const state = { username: "admin", members: [], accounts: [], devices: [], vending: [], products: [], activeTab: "dashboard", nfcTimer: null, imageUrl: null };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
  const money = (v) => new Intl.NumberFormat("id-ID", { style:"currency", currency:"IDR", maximumFractionDigits:0 }).format(Number(v || 0));
  const fmt = (v) => v ? String(v).replace("T"," ").replace("Z"," UTC") : "—";
  const errorText = (error) => {
    const value = error?.data?.detail?.code || error?.data?.detail || error?.message || "Permintaan gagal";
    return String(value);
  };
  const show = (id, message, bad=false) => {
    const el=$(id); if(!el)return;
    el.textContent=message || "";
    el.dataset.state=bad?"error":"ok";
  };
  async function request(path, options) { return api.request(path, options || {}); }
  function table(rows, columns, empty="Tidak ada data.") {
    if(!rows || !rows.length) return '<p class="hint" style="padding:14px">'+esc(empty)+'</p>';
    return '<table><thead><tr>'+columns.map(c=>'<th>'+esc(c.label)+'</th>').join('')+'</tr></thead><tbody>'+
      rows.map(row=>'<tr>'+columns.map(c=>'<td>'+ (c.render ? c.render(row) : esc(row[c.key])) +'</td>').join('')+'</tr>').join('')+
      '</tbody></table>';
  }
  function statusPill(value) {
    const v=String(value||"unknown");
    return '<span class="pill '+(v==="succeeded"||v==="active"||v==="completed"?"ok":v==="pending"?"warn":"bad")+'">'+esc(v)+'</span>';
  }
  function downloadBlob(blob, filename) {
    const url=URL.createObjectURL(blob), a=document.createElement("a");
    a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1500);
  }
  function showLogin(message="") {
    if($("loginScreen"))$("loginScreen").hidden=false;
    if($("appShell"))$("appShell").hidden=true;
    if($("loginError"))$("loginError").textContent=message;
    if($("loginPassword"))$("loginPassword").value="";
  }
  function unlockApp(username) {
    state.username=username||"admin";
    $("loginScreen").hidden=true; $("appShell").hidden=false;
    $("activeUsername").textContent=state.username;
    $("loginError").textContent="";
    loadAll();
  }
  async function loadDashboard(period="1w") {
    try {
      const {data:d}=await request("/admin/dashboard?period="+encodeURIComponent(period));
      const s=d.summary||{};
      $("summary").innerHTML=[
        ["Anggota",s.members||0],["Perangkat aktif",s.active_devices||0],
        ["Saldo anggota",money(s.member_balance_minor)],["Transaksi berhasil",s.successful_transactions||0]
      ].map(([label,value])=>'<div class="card"><div class="label">'+esc(label)+'</div><div class="value">'+esc(value)+'</div></div>').join("");
      const points=d.analytics||[],max=Math.max(1,...points.map(x=>Number(x.count||0)));
      $("analyticsSummary").textContent=points.reduce((n,x)=>n+Number(x.count||0),0)+" transaksi berhasil pada periode "+period+". Zona waktu laporan: Asia/Jakarta.";
      $("analyticsChart").innerHTML=points.length?points.map(p=>'<div class="chart-row" style="display:grid;grid-template-columns:100px 1fr 40px;gap:8px;align-items:center;margin:8px 0"><span>'+esc(p.date)+'</span><div style="background:var(--line);height:10px;border-radius:8px;overflow:hidden"><div style="height:100%;width:'+Math.round(Number(p.count||0)/max*100)+'%;background:var(--accent,#3b82f6)"></div></div><b>'+esc(p.count)+'</b></div>').join(""):'<p class="hint">Belum ada transaksi berhasil pada periode ini.</p>';
      $("mostUsedVending").innerHTML=table(d.most_used_vending||[],[
        {key:"device_name",label:"Mesin"},{key:"hardware_id",label:"Hardware ID"},{key:"transactions",label:"Transaksi berhasil"}
      ]);
      $("paymentChannels").innerHTML=table(d.payment_channels||[],[
        {key:"channel",label:"Kanal"},{key:"transactions",label:"Transaksi"},{key:"amount_minor",label:"Nominal",render:r=>esc(money(r.amount_minor))}
      ]);
      $("recentTransactions").innerHTML=table((d.recent_transactions||[]).map(x=>({...x,amount:money(x.amount_minor)})),[
        {key:"created_at",label:"Waktu"},{key:"transaction_id",label:"ID transaksi"},{key:"member_name",label:"Anggota"},
        {key:"device_name",label:"Perangkat"},{key:"transaction_type",label:"Jenis"},{key:"amount",label:"Nominal"},
        {key:"status",label:"Status",render:r=>statusPill(r.status)}
      ]);
      const {data:recon}=await request("/admin/finance/reconciliation");
      const pending=(recon.pending_purchases||[]).length;
      show("dashboardResult",recon.status==="ok"?"Ringkasan dimuat. Rekonsiliasi ledger seimbang.":"Perhatian rekonsiliasi: "+(recon.transaction_imbalances||[]).length+" transaksi tidak seimbang, "+(recon.account_mismatches||[]).length+" saldo akun berbeda, "+pending+" pembelian masih pending.");
    } catch(e) { show("dashboardResult",errorText(e),true); }
  }
  function memberPayload() {
    return {
      display_name:$("memberName").value.trim(), nik:$("memberNik").value.trim(),
      phone:$("memberPhone").value.trim()||null,email:$("memberEmail").value.trim()||null,
      address:$("memberAddress").value.trim()||null,birth_place:$("memberBirthPlace").value.trim()||null,
      birth_date:$("memberBirthDate").value||null,sex:$("memberSex").value||null,
      rt:$("memberRt").value.trim()||null,rw:$("memberRw").value.trim()||null,
      village:$("memberVillage").value.trim()||null,district:$("memberDistrict").value.trim()||null,
      city_regency:$("memberCity").value.trim()||null,province:$("memberProvince").value.trim()||null,
      religion:$("memberReligion").value.trim()||null,marital_status:$("memberMarital").value.trim()||null,
      occupation:$("memberOccupation").value.trim()||null,citizenship:$("memberCitizenship").value.trim()||"WNI",
      registration_date:$("memberRegistrationDate").value||null,status:$("memberStatus").value
    };
  }
  async function loadMembers() {
    try {
      const {data:d}=await request("/members");
      state.members=d.items||[];
      renderMembers();
    } catch(e) { show("memberAuthResult",errorText(e),true); }
  }
  function renderMembers() {
    const q=($("memberSearch")?.value||"").trim().toLowerCase(), status=$("memberStatusFilter")?.value||"ALL";
    const rows=state.members.filter(m=>(status==="ALL"||m.status===status)&&(!q||[m.member_id,m.display_name,m.nik].some(v=>String(v||"").toLowerCase().includes(q))));
    $("members").innerHTML=table(rows,[
      {key:"member_id",label:"Member ID"},{key:"display_name",label:"Nama"},{key:"nik",label:"NIK"},
      {key:"phone",label:"No. HP"},{key:"balance_minor",label:"Saldo",render:r=>esc(money(r.balance_minor))},
      {key:"active_cards",label:"Kartu aktif",render:r=>esc(r.active_cards??"—")},
      {key:"status",label:"Status",render:r=>statusPill(r.status)},
      {key:"actions",label:"Aksi",render:r=>'<button type="button" data-member-action="edit" data-member-id="'+esc(r.member_id)+'">Edit</button> <button type="button" data-member-action="nfc" data-member-id="'+esc(r.member_id)+'">NFC</button> <button type="button" data-member-action="pin" data-member-id="'+esc(r.member_id)+'">Reset PIN</button> <button type="button" data-member-action="cards" data-member-id="'+esc(r.member_id)+'">Kartu</button>'}
    ],"Belum ada anggota.");
  }
  function clearMemberForm() {
    $("memberForm").reset(); $("memberId").value="";
    $("memberCitizenship").value="WNI"; $("memberStatus").value="active";
  }
  function fillMemberForm(m) {
    $("memberId").value=m.member_id||"";$("memberName").value=m.display_name||"";$("memberNik").value=m.nik||"";
    $("memberPhone").value=m.phone||"";$("memberEmail").value=m.email||"";$("memberAddress").value=m.address||"";
    $("memberBirthPlace").value=m.birth_place||"";$("memberBirthDate").value=m.birth_date||"";$("memberSex").value=m.sex||"";
    $("memberRt").value=m.rt||"";$("memberRw").value=m.rw||"";$("memberVillage").value=m.village||"";
    $("memberDistrict").value=m.district||"";$("memberCity").value=m.city_regency||"";$("memberProvince").value=m.province||"";
    $("memberReligion").value=m.religion||"";$("memberMarital").value=m.marital_status||"";$("memberOccupation").value=m.occupation||"";
    $("memberCitizenship").value=m.citizenship||"WNI";$("memberRegistrationDate").value=m.registration_date||"";
    $("memberStatus").value=m.status||"active";
  }
  async function saveMember(event) {
    event.preventDefault();
    try {
      const id=$("memberId").value.trim(), payload=memberPayload();
      if(!payload.display_name||!payload.nik)throw new Error("Nama dan NIK wajib diisi.");
      const path=id?"/admin/members/"+encodeURIComponent(id):"/members";
      const {data:d}=await request(path,{method:id?"PATCH":"POST",body:payload});
      if(!id&&d.member_id)$("memberId").value=d.member_id;
      show("memberAuthResult","Data anggota tersimpan. ID: "+(d.member_id||id));
      await loadMembers(); await loadAccounts();
    } catch(e) { show("memberAuthResult",errorText(e),true); }
  }
  async function loadCashierChoices() {
    try {
      const {data:d}=await request("/admin/devices");
      state.devices=d.items||[];
      const active=state.devices.filter(x=>x.device_type==="cashier"&&x.status==="active");
      const selector=$("nfcCashier");
      if(selector)selector.innerHTML='<option value="">Pilih terminal Cashier</option>'+active.map(x=>'<option value="'+esc(x.registry_id)+'">'+esc(x.display_name||x.hardware_id||x.registry_id)+' · '+esc(x.hardware_id||"belum terdaftar")+'</option>').join("");
      const config=$("cashierConfigDevice");
      if(config)config.innerHTML='<option value="">Pilih terminal Cashier</option>'+active.map(x=>'<option value="'+esc(x.registry_id)+'">'+esc(x.display_name||x.hardware_id||x.registry_id)+'</option>').join("");
      const history=$("cashierDevice");
      if(history)history.innerHTML='<option value="ALL">Semua Cashier</option>'+active.map(x=>'<option value="'+esc(x.hardware_id||"")+'">'+esc(x.display_name||x.hardware_id||x.registry_id)+'</option>').join("");
      return active;
    } catch(e) { show("nfcRegistrationResult",errorText(e),true); return []; }
  }
  async function startNfcRegistration(memberId) {
    try {
      if(!memberId)throw new Error("Simpan atau pilih anggota terlebih dahulu.");
      const registryId=$("nfcCashier").value;
      if(!registryId)throw new Error("Pilih terminal Cashier aktif.");
      const replace=Boolean($("nfcReplaceExisting").checked);
      const {data:d}=await request("/admin/members/"+encodeURIComponent(memberId)+"/nfc-registration",{
        method:"POST",body:{registry_id:registryId,replace_existing:replace}
      });
      clearTimeout(state.nfcTimer);
      show("nfcRegistrationResult","Sesi "+d.session_id+" dibuat. Silakan gunakan terminal Cashier yang dipilih.");
      const poll=async()=>{
        try {
          const {data:s}=await request("/admin/nfc-registration/"+encodeURIComponent(d.session_id));
          const messages={scan_pending:"Menunggu Cashier memulai scan.",waiting_nfc:"Silakan tempelkan kartu NFC.",pin_pending:"Kartu terbaca. Silakan masukkan PIN anggota pada terminal.",processing:"Mendaftarkan kartu dan PIN.",completed:"Registrasi NFC berhasil.",failed:"Registrasi NFC gagal.",expired:"Sesi registrasi kedaluwarsa."};
          show("nfcRegistrationResult",(messages[s.status]||s.status)+" · "+d.session_id);
          if(["completed","failed","expired"].includes(s.status)){await loadMembers();return;}
          state.nfcTimer=setTimeout(poll,1800);
        } catch(e) { show("nfcRegistrationResult",errorText(e),true); }
      };
      await poll();
    } catch(e) { show("nfcRegistrationResult",errorText(e),true); }
  }
  async function resetMemberPin(memberId) {
    const pin=prompt("PIN anggota baru (6–12 digit):"); if(pin===null)return;
    const reason=prompt("Alasan reset PIN (minimal 5 karakter):"); if(!reason)return;
    try {
      await request("/admin/members/"+encodeURIComponent(memberId)+"/reset-pin",{method:"POST",body:{pin,reason}});
      show("memberAuthResult","PIN anggota berhasil diperbarui.");
    } catch(e) { show("memberAuthResult",errorText(e),true); }
  }
  async function loadAccounts() {
    try {
      const {data:d}=await request("/admin/accounts");
      state.accounts=d.items||[];
      const members=state.accounts.filter(a=>a.account_type==="member");
      $("accounts").innerHTML=table(state.accounts,[
        {key:"account_id",label:"Rekening"},{key:"member_name",label:"Anggota"},{key:"account_type",label:"Jenis"},
        {key:"balance_minor",label:"Saldo",render:r=>esc(money(r.balance_minor))},{key:"status",label:"Status",render:r=>statusPill(r.status)}
      ]);
      $("account").innerHTML='<option value="">Pilih anggota</option>'+members.map(a=>'<option value="'+esc(a.member_id)+'">'+esc(a.member_id+' · '+(a.member_name||""))+' · '+esc(money(a.balance_minor))+'</option>').join("");
      $("cashierSettlementAccount").innerHTML='<option value="">Pilih rekening merchant</option>'+state.accounts.filter(a=>a.account_type==="merchant"&&a.status==="active").map(a=>'<option value="'+esc(a.account_id)+'">'+esc(a.label||a.account_id)+' · '+esc(money(a.balance_minor))+'</option>').join("");
    } catch(e) { show("financialResult",errorText(e),true); }
  }
  async function loadLedger() {
    const memberId=$("account").value, account=state.accounts.find(a=>a.member_id===memberId&&a.account_type==="member");
    if(!account){$("financialLedger").innerHTML="";return;}
    try {
      const {data:d}=await request("/admin/accounts/"+encodeURIComponent(account.account_id)+"/ledger?limit=100");
      $("financialLedger").innerHTML=table(d.items||[],[
        {key:"created_at",label:"Waktu"},{key:"transaction_id",label:"ID transaksi"},{key:"request_id",label:"Request"},
        {key:"direction",label:"Arah"},{key:"amount_minor",label:"Nominal",render:r=>esc(money(r.amount_minor))},
        {key:"transaction_type",label:"Jenis"},{key:"status",label:"Status"}
      ]);
    } catch(e) { show("financialResult",errorText(e),true); }
  }
  async function submitFinancial(event) {
    event.preventDefault();
    try {
      const memberId=$("account").value, amount=Number($("amount").value), direction=$("direction").value, reference=$("reference").value.trim();
      if(!memberId||!Number.isSafeInteger(amount)||amount<=0)throw new Error("Pilih anggota dan nominal yang valid.");
      if(reference.length<8)throw new Error("Referensi wajib minimal 8 karakter untuk idempotensi.");
      const path=direction==="credit"?"/finance/top-ups":"/finance/withdrawals";
      const {data:d}=await request(path,{method:"POST",body:{request_id:reference,member_id:memberId,amount_minor:amount,description:reference}});
      show("financialResult","Transaksi "+d.transaction_id+" berstatus "+d.status+(d.idempotent_replay?" (replay idempoten).":" tersimpan."));
      await loadAccounts();await loadLedger();await loadDashboard();
    } catch(e) { show("financialResult",errorText(e),true); }
  }
  async function loadTransactions(opts={}) {
    const params=new URLSearchParams();
    params.set("period",opts.period||"week");
    params.set("source",opts.source||"ALL");
    params.set("status",opts.status||"ALL");
    params.set("transaction_type",opts.transaction_type||"ALL");
    if(opts.member_id)params.set("member_id",opts.member_id);
    if(opts.hardware_id)params.set("hardware_id",opts.hardware_id);
    if(opts.transaction_id)params.set("transaction_id",opts.transaction_id);
    if(opts.start_date) {params.set("period","custom");params.set("start_date",opts.start_date);params.set("end_date",opts.end_date);}
    const {data:d}=await request("/admin/transactions?"+params.toString());
    return d.items||[];
  }
  async function loadPayments() {
    try {
      const rows=await loadTransactions({
        period:$("paymentPeriod").value,source:$("paymentMethodFilter").value,status:$("paymentStatusFilter").value,
        transaction_id:$("paymentSearch").value.trim()
      });
      $("payments").innerHTML=table(rows,[
        {key:"created_at",label:"Waktu"},{key:"transaction_id",label:"Transaksi"},{key:"request_id",label:"Request"},
        {key:"member_name",label:"Anggota"},{key:"device_name",label:"Perangkat"},{key:"transaction_type",label:"Jenis"},
        {key:"amount_minor",label:"Nominal",render:r=>esc(money(r.amount_minor))},{key:"status",label:"Status",render:r=>statusPill(r.status)}
      ]);
      show("paymentResult",rows.length+" transaksi ditemukan.");
    } catch(e) { show("paymentResult",errorText(e),true); }
  }
  async function loadVendingDevices() {
    try {
      const {data:d}=await request("/vending/devices");
      state.vending=d.items||[];
      $("machines").innerHTML=table(state.vending,[
        {key:"display_name",label:"Mesin"},{key:"registry_id",label:"Registry ID"},{key:"hardware_id",label:"Hardware ID"},
        {key:"mac_address",label:"MAC"},{key:"last_seen_at",label:"Last seen"},{key:"status",label:"Status",render:r=>statusPill(r.status)}
      ]);
      $("machineId").innerHTML='<option value="">Pilih mesin</option>'+state.vending.map(m=>'<option value="'+esc(m.registry_id)+'">'+esc(m.display_name||m.hardware_id||m.registry_id)+'</option>').join("");
    } catch(e) { show("productResult",errorText(e),true); }
  }
  async function loadProducts() {
    const registryId=$("machineId").value;
    if(!registryId){$("products").innerHTML="";return;}
    try {
      const {data:d}=await request("/vending/devices/"+encodeURIComponent(registryId)+"/products");
      state.products=d.items||[];
      $("products").innerHTML=table(state.products,[
        {key:"product_id",label:"Product ID"},{key:"name",label:"Nama"},{key:"price_minor",label:"Harga",render:r=>esc(money(r.price_minor))},
        {key:"stock",label:"Stok"},{key:"capacity",label:"Kapasitas"},{key:"enabled",label:"Aktif",render:r=>statusPill(r.enabled?"active":"disabled")},
        {key:"nfc_promo_percent",label:"Promo NFC"},{key:"qris_promo_percent",label:"Promo QRIS"},
        {key:"image_sha256",label:"Hash gambar",render:r=>esc(r.image_sha256||"—")}
      ]);
      const id=Number($("productId").value||1),p=state.products.find(x=>x.product_id===id);
      if(p) {
        $("productName").value=p.name||"";$("productPrice").value=p.price_minor||"";$("productStock").value=p.stock??0;
        $("productCapacity").value=p.capacity??p.stock??0;$("productEnabled").checked=Boolean(p.enabled);
        await showProductImage(p);
      }
    } catch(e) { show("productResult",errorText(e),true); }
  }
  async function showProductImage(product) {
    if(state.imageUrl){URL.revokeObjectURL(state.imageUrl);state.imageUrl=null;}
    const el=$("productImagePreview");
    if(!product?.image_sha256||!el){if(el)el.textContent="Belum ada gambar tersimpan.";return;}
    try {
      const {data:blob}=await request("/admin/vending/devices/"+encodeURIComponent($("machineId").value)+"/products/"+product.product_id+"/image",{responseType:"blob"});
      state.imageUrl=URL.createObjectURL(blob);
      el.innerHTML='<img alt="Gambar produk" style="max-width:160px;max-height:120px;object-fit:contain" src="'+state.imageUrl+'"><p class="hint">SHA-256: '+esc(product.image_sha256)+'</p>';
    } catch(e) { el.textContent="Gambar tersimpan tetapi gagal dimuat: "+errorText(e); }
  }
  async function saveProduct(event) {
    event.preventDefault();
    try {
      const registryId=$("machineId").value, productId=Number($("productId").value);
      if(!registryId||!productId)throw new Error("Pilih mesin dan Product ID.");
      const payload={name:$("productName").value.trim(),price_minor:Number($("productPrice").value),
        stock:Number($("productStock").value),capacity:Number($("productCapacity").value),enabled:$("productEnabled").checked};
      await request("/vending/devices/"+encodeURIComponent(registryId)+"/products/"+productId,{method:"PUT",body:payload});
      const file=$("productImageFile").files[0];
      if(file) {
        if(file.size>2*1024*1024)throw new Error("Gambar maksimal 2 MiB.");
        const fd=new FormData();fd.append("file",file);
        await request("/admin/vending/devices/"+encodeURIComponent(registryId)+"/products/"+productId+"/image",{method:"POST",body:fd});
        $("productImageFile").value="";
      }
      show("productResult","Produk tersimpan; promo NFC/QRIS tetap 0% dan nonaktif sampai implementasi promo disetujui.");
      await loadProducts();
    } catch(e) { show("productResult",errorText(e),true); }
  }
  async function loadVendingTransactions() {
    try {
      const registryId=$("machineId").value, productId=$("vendingTxnProduct").value, status=$("vendingTxnStatus").value;
      let rows=await loadTransactions({period:"all",source:"VENDING",status:status==="ALL"?"ALL":status});
      rows=rows.filter(r=>!registryId||(r.metadata||{}).registry_id===registryId);
      if(productId!=="ALL")rows=rows.filter(r=>String((r.metadata||{}).product_id)===productId);
      $("vendingTxnResult").innerHTML=table(rows,[
        {key:"created_at",label:"Waktu"},{key:"transaction_id",label:"Transaksi"},{key:"member_name",label:"Anggota"},
        {key:"metadata",label:"Produk",render:r=>esc(r.metadata?.product_name||r.metadata?.product_id||"—")},
        {key:"amount_minor",label:"Nominal",render:r=>esc(money(r.amount_minor))},{key:"status",label:"Status",render:r=>statusPill(r.status)},
        {key:"metadata",label:"Dispense",render:r=>esc(r.metadata?.dispense_status||"pending")}
      ]);
    } catch(e) { show("vendingTxnResult",errorText(e),true); }
  }
  async function loadDevices() {
    try {
      const {data:d}=await request("/admin/devices");state.devices=d.items||[];
      $("devices").innerHTML=table(state.devices,[
        {key:"display_name",label:"Nama"},{key:"registry_id",label:"Registry ID"},{key:"hardware_id",label:"Hardware ID"},
        {key:"device_type",label:"Jenis"},{key:"status",label:"Status",render:r=>statusPill(r.status)},
        {key:"last_seen_at",label:"Last seen"},{key:"device_key_hint",label:"Key hint"},
        {key:"actions",label:"Aksi",render:r=>'<button type="button" data-device-action="rotate" data-registry-id="'+esc(r.registry_id)+'">Rotasi key</button> <button type="button" data-device-action="revoke" data-registry-id="'+esc(r.registry_id)+'">Cabut</button>'}
      ]);
      show("deviceAuthResult",state.devices.length+" perangkat dimuat.");
      await loadCashierChoices();
    } catch(e) { show("deviceAuthResult",errorText(e),true); }
  }
  async function provisionDevice(event) {
    event.preventDefault();
    try {
      const {data:d}=await request("/admin/devices",{method:"POST",body:{
        device_type:$("provisionDeviceType").value,display_name:$("provisionDeviceName").value.trim()
      }});
      $("provisionedDeviceKey").value=d.device_key;
      $("provisionedDeviceKey").type="password";
      show("deviceProvisionResult","Perangkat dibuat: "+d.registry_id+". Key hanya ditampilkan sekali. Catat dan masukkan pada WebUI lokal perangkat.");
      await loadDevices();
    } catch(e) { show("deviceProvisionResult",errorText(e),true); }
  }
  async function deviceAction(event) {
    const button=event.target.closest("[data-device-action]");if(!button)return;
    const id=button.dataset.registryId,action=button.dataset.deviceAction;
    try {
      if(action==="revoke"&&!confirm("Cabut key perangkat ini? Semua request dengan key lama akan ditolak."))return;
      const {data:d}=await request("/admin/devices/"+encodeURIComponent(id)+"/"+(action==="rotate"?"rotate-key":"revoke"),{method:"POST"});
      if(action==="rotate") {
        $("provisionedDeviceKey").value=d.device_key;$("provisionedDeviceKey").type="password";
        show("deviceProvisionResult","Key baru dibuat. Perbarui key pada perangkat sekarang; key lama langsung tidak berlaku.");
      } else show("deviceAuthResult","Key perangkat dicabut.");
      await loadDevices();
    } catch(e) { show("deviceAuthResult",errorText(e),true); }
  }
  async function loadCashierHistory() {
    try {
      let rows=await loadTransactions({period:$("cashierPeriod").value,source:"CASHIER",status:$("cashierStatus").value});
      const hardware=$("cashierDevice").value,type=$("cashierType").value;
      if(hardware!=="ALL")rows=rows.filter(r=>r.hardware_id===hardware);
      if(type==="DEPOSIT")rows=rows.filter(r=>r.transaction_type==="top_up");
      if(type==="PAYMENT")rows=rows.filter(r=>r.transaction_type==="cashier_payment");
      const succeeded=rows.filter(r=>r.status==="succeeded");
      $("cashierMetrics").innerHTML=[
        ["Transaksi",rows.length],["Berhasil",succeeded.length],["Nominal berhasil",money(succeeded.reduce((n,r)=>n+r.amount_minor,0))]
      ].map(([label,value])=>'<div class="card"><div class="label">'+esc(label)+'</div><div class="value">'+esc(value)+'</div></div>').join("");
      $("cashierResult").innerHTML=table(rows,[
        {key:"created_at",label:"Waktu"},{key:"transaction_id",label:"Transaksi"},{key:"request_id",label:"Request"},
        {key:"hardware_id",label:"Hardware"},{key:"member_name",label:"Anggota"},{key:"transaction_type",label:"Jenis"},
        {key:"amount_minor",label:"Nominal",render:r=>esc(money(r.amount_minor))},{key:"status",label:"Status",render:r=>statusPill(r.status)}
      ]);
    } catch(e) { show("cashierDetail",errorText(e),true); }
  }
  async function saveCashierConfig(event) {
    event.preventDefault();
    try {
      const id=$("cashierConfigDevice").value;
      if(!id)throw new Error("Pilih terminal Cashier.");
      const {data:d}=await request("/admin/cashier-devices/"+encodeURIComponent(id)+"/configuration",{method:"PUT",body:{
        operator_id:$("cashierOperatorId").value.trim(),operator_name:$("cashierOperatorName").value.trim(),
        operator_pin:$("cashierOperatorPin").value,settlement_account_id:$("cashierSettlementAccount").value
      }});
      $("cashierOperatorPin").value="";
      show("cashierConfigResult","Konfigurasi tersimpan untuk operator "+d.operator_name+".");
    } catch(e) { show("cashierConfigResult",errorText(e),true); }
  }
  async function createMerchantAccount() {
    const label=prompt("Nama rekening merchant/settlement:");if(!label)return;
    try {
      const {data:d}=await request("/admin/merchant-accounts",{method:"POST",body:{label}});
      show("cashierConfigResult","Rekening merchant dibuat: "+d.account_id);
      await loadAccounts();
    } catch(e) { show("cashierConfigResult",errorText(e),true); }
  }
  async function loadAudit() {
    try {
      const params=new URLSearchParams();
      params.set("period",$("auditPeriod").value);params.set("source",$("auditSource").value);
      params.set("status",$("auditStatus").value);params.set("transaction_type",$("auditType").value);
      params.set("member_id",$("auditMemberId").value.trim());params.set("hardware_id",$("auditHardwareId").value.trim());
      params.set("transaction_id",$("auditTransactionId").value.trim());
      if($("auditPeriod").value==="custom"){
        params.set("start_date",$("auditStartDate").value);params.set("end_date",$("auditEndDate").value);
      } else if($("auditDate").value)params.set("date",$("auditDate").value);
      const {data:d}=await request("/admin/transactions?"+params.toString());
      $("auditResult").innerHTML=table(d.items||[],[
        {key:"created_at",label:"Waktu"},{key:"transaction_id",label:"Transaksi"},{key:"request_id",label:"Request"},
        {key:"member_id",label:"Member"},{key:"hardware_id",label:"Perangkat"},{key:"transaction_type",label:"Jenis"},
        {key:"amount_minor",label:"Nominal",render:r=>esc(money(r.amount_minor))},{key:"status",label:"Status",render:r=>statusPill(r.status)}
      ]);
      const {data:a}=await request("/admin/audit?limit=100");
      if($("auditEvents"))$("auditEvents").innerHTML=table(a.items||[],[
        {key:"created_at",label:"Waktu"},{key:"action",label:"Aksi"},{key:"entity_type",label:"Entitas"},
        {key:"entity_id",label:"ID entitas"},{key:"request_id",label:"Request"},{key:"detail",label:"Detail",render:r=>esc(JSON.stringify(r.detail||{}))}
      ]);
      show("backupResult",(d.items||[]).length+" transaksi ditampilkan; audit event dimuat.");
    } catch(e) { show("auditResult",errorText(e),true); }
  }
  async function exportAudit() {
    try {
      const params=new URLSearchParams();
      params.set("period",$("auditPeriod").value);params.set("source",$("auditSource").value);
      params.set("status",$("auditStatus").value);params.set("transaction_type",$("auditType").value);
      params.set("member_id",$("auditMemberId").value.trim());params.set("hardware_id",$("auditHardwareId").value.trim());
      params.set("transaction_id",$("auditTransactionId").value.trim());
      if($("auditPeriod").value==="custom"){
        if(!$("auditStartDate").value||!$("auditEndDate").value)throw new Error("Tanggal mulai dan akhir wajib diisi.");
        params.set("start_date",$("auditStartDate").value);params.set("end_date",$("auditEndDate").value);
      } else if($("auditDate").value)params.set("date",$("auditDate").value);
      const {response,data}=await request("/admin/reports/transactions.xlsx?"+params.toString(),{responseType:"blob"});
      const disposition=response.headers.get("content-disposition")||"", match=disposition.match(/filename="([^"]+)"/i);
      downloadBlob(data,match?match[1]:"M-Group_Transactions.xlsx");
      show("backupResult","Laporan XLSX berhasil dibuat.");
    } catch(e) { show("backupResult",errorText(e),true); }
  }
  async function createBackup() {
    try {
      const {response,data}=await request("/admin/backup",{method:"POST",responseType:"blob"});
      const match=(response.headers.get("content-disposition")||"").match(/filename="([^"]+)"/i);
      downloadBlob(data,match?match[1]:"M-Group_BACKUP.mgroup.zip");
      show("backupResult","Backup native berhasil diunduh.");
    } catch(e) { show("backupResult",errorText(e),true); }
  }
  async function restoreBackup() {
    const file=$("restoreFile").files[0];if(!file){show("backupResult","Pilih file backup .mgroup.zip.",true);return;}
    if(!confirm("Restore mengganti database aktif setelah validasi checksum, integritas, dan foreign key. Lanjutkan?"))return;
    try {
      const fd=new FormData();fd.append("file",file);
      const {data:d}=await request("/admin/backup/restore",{method:"POST",body:fd});
      show("backupResult","Restore selesai. Status: "+d.status+"; integrity: "+d.integrity_check+".");
      setTimeout(()=>location.reload(),1200);
    } catch(e) { show("backupResult",errorText(e),true); }
  }
  async function loadAll() {
    $("status").textContent="● Terhubung";
    if($("loans"))$("loans").innerHTML='<p class="hint">Modul pinjaman belum diaktifkan karena kebijakan bunga, tenor, jadwal angsuran, dan pencatatan pencairan/pelunasan belum ditetapkan dalam kontrak v2. Tidak ada transaksi pinjaman simulasi yang dibuat.</p>';
    await Promise.allSettled([loadDashboard(),loadMembers(),loadAccounts(),loadDevices(),loadVendingDevices(),loadAudit()]);
  }
  function loadTab(tab) {
    state.activeTab=tab;
    if(tab==="dashboard")loadDashboard();
    if(tab==="member"){loadMembers();loadCashierChoices();}
    if(tab==="financial"){loadAccounts();loadLedger();}
    if(tab==="payment")loadPayments();
    if(tab==="vending"){loadVendingDevices();loadVendingTransactions();}
    if(tab==="cashier"){loadCashierChoices();loadAccounts();loadCashierHistory();}
    if(tab==="devices")loadDevices();
    if(tab==="audit")loadAudit();
  }
  function switchTab(tab) {
    document.querySelectorAll(".tab-btn[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
    document.querySelectorAll(".tab-pane").forEach(p=>p.classList.toggle("active",p.id==="tab-"+tab));
    const btn=document.querySelector('.tab-btn[data-tab="'+tab+'"]');
    const title=document.querySelector(".top-title");if(title&&btn)title.textContent=btn.textContent.trim();
    loadTab(tab);
  }

  $("loginForm").addEventListener("submit",async event=>{
    event.preventDefault();
    const token=$("loginPassword").value;
    $("loginError").textContent="Memverifikasi token admin...";
    try {
      await api.verifyToken(token);
      $("loginPassword").value="";
      unlockApp($("loginUsername").value.trim()||"admin");
    } catch(e) { showLogin("Token admin ditolak atau API belum siap: "+errorText(e)); }
  });
  $("logoutButton").addEventListener("click",()=>{api.clearToken();showLogin("Token dihapus dari sesi browser.");});
  if($("settingsLogout"))$("settingsLogout").addEventListener("click",()=>{api.clearToken();showLogin("Token dihapus dari sesi browser.");});
  $("dashboardForm").addEventListener("submit",e=>{e.preventDefault();loadDashboard();});
  document.querySelectorAll("[data-analytics-period]").forEach(btn=>btn.addEventListener("click",()=>{
    document.querySelectorAll("[data-analytics-period]").forEach(b=>b.classList.toggle("active",b===btn));
    loadDashboard(btn.dataset.analyticsPeriod);
  }));
  $("memberForm").addEventListener("submit",saveMember);
  $("memberSearch").addEventListener("input",renderMembers);
  $("memberStatusFilter").addEventListener("change",renderMembers);
  $("nfcStart").addEventListener("click",()=>startNfcRegistration($("memberId").value.trim()));
  $("members").addEventListener("click",async event=>{
    const b=event.target.closest("[data-member-action]");if(!b)return;
    const id=b.dataset.memberId, member=state.members.find(m=>m.member_id===id);
    if(b.dataset.memberAction==="edit"&&member)fillMemberForm(member);
    if(b.dataset.memberAction==="nfc"){ $("memberId").value=id; await loadCashierChoices(); $("nfcCashier").focus(); }
    if(b.dataset.memberAction==="pin")resetMemberPin(id);
    if(b.dataset.memberAction==="cards") {
      try {
        const {data:d}=await request("/admin/members/"+encodeURIComponent(id)+"/cards");
        const cards=d.items||[],active=cards.filter(c=>c.status==="active");
        if(!active.length){alert("Tidak ada kartu aktif untuk "+id);return;}
        const selected=active.length===1?active[0]:active.find(c=>c.card_id===prompt("Masukkan Card ID yang akan dicabut:\n"+active.map(c=>c.card_id+" · "+c.card_fingerprint).join("\n")));
        if(!selected)return;
        if(!confirm("Cabut kartu "+selected.card_fingerprint+" untuk "+id+"?"))return;
        await request("/admin/members/"+encodeURIComponent(id)+"/cards/"+encodeURIComponent(selected.card_id)+"/revoke",{method:"POST"});
        show("memberAuthResult","Kartu berhasil dicabut.");await loadMembers();
      } catch(e) {show("memberAuthResult",errorText(e),true);}
    }
  });
  $("financialForm").addEventListener("submit",submitFinancial);
  $("account").addEventListener("change",loadLedger);
  $("paymentForm").addEventListener("submit",e=>{e.preventDefault();loadPayments();});
  $("loadVendingMachines").addEventListener("click",loadVendingDevices);
  $("machineId").addEventListener("change",()=>{loadProducts();loadVendingTransactions();});
  $("productId").addEventListener("change",loadProducts);
  $("productForm").addEventListener("submit",saveProduct);
  $("loadVendingTransactions").addEventListener("click",loadVendingTransactions);
  $("deviceAuthForm").addEventListener("submit",e=>{e.preventDefault();loadDevices();});
  $("deviceProvisionForm").addEventListener("submit",provisionDevice);
  $("devices").addEventListener("click",deviceAction);
  $("toggleDeviceKey").addEventListener("click",()=>{$("provisionedDeviceKey").type=$("provisionedDeviceKey").type==="password"?"text":"password";});
  $("copyDeviceKey").addEventListener("click",async()=>{
    try {await navigator.clipboard.writeText($("provisionedDeviceKey").value);show("deviceProvisionResult","Device Key disalin. Simpan dengan aman.");}
    catch(e){show("deviceProvisionResult","Clipboard tidak tersedia; salin key secara manual.",true);}
  });
  $("cashierForm").addEventListener("submit",e=>{e.preventDefault();loadCashierHistory();});
  $("cashierConfigForm").addEventListener("submit",saveCashierConfig);
  $("cashierDevice").addEventListener("change",loadCashierHistory);
  $("auditForm").addEventListener("submit",e=>{e.preventDefault();loadAudit();});
  $("auditPeriod").addEventListener("change",()=>{
    const custom=$("auditPeriod").value==="custom";
    $("auditDateLabel").hidden=custom;$("auditStartLabel").hidden=!custom;$("auditEndLabel").hidden=!custom;
  });
  $("auditExport").addEventListener("click",exportAudit);
  $("backupCreate").addEventListener("click",createBackup);
  $("backupRestore").addEventListener("click",restoreBackup);
  if($("createMerchantAccount"))$("createMerchantAccount").addEventListener("click",createMerchantAccount);
  document.querySelectorAll(".tab-btn[data-tab]").forEach(btn=>btn.addEventListener("click",()=>switchTab(btn.dataset.tab)));
  const savedToken=api.getToken();
  if(savedToken) {
    api.request("/admin/audit?limit=1").then(()=>unlockApp("admin")).catch(()=>{api.clearToken();showLogin("");});
  } else showLogin("");
})();
