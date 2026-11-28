// Ovládání aplikace: okna, potvrzení, klávesnice, kopírování, hlášky (přesunuto z base.html, #233).
// ---- Potvrzení a upozornění v okně aplikace (místo systémového confirm / alert).
// potvrd(text, {ano: "Smazat"}) → Promise<boolean>; s ne: null jen tlačítko OK (upozornění).
// ---- Datum jako text 20.11.2026 (#94, bez kalendáře prohlížeče). Zkrácené zápisy: 20.11. = letošní rok,
// 20.11.26, 20112026, 201126; ISO 2026-11-20 (registr vozidel). Server přijímá stejné tvary.
function ctiDatum(text) {
  let t = String(text || "").trim().replace(/\s+/g, "");
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) t = `${m[3]}.${m[2]}.${m[1]}`;
  else if (/^\d{8}$/.test(t) || /^\d{6}$/.test(t)) t = `${t.slice(0, 2)}.${t.slice(2, 4)}.${t.slice(4)}`;
  m = t.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})?$/);
  if (!m) return null;
  const rok = m[3] === undefined ? new Date().getFullYear() : m[3].length === 2 ? 2000 + +m[3] : +m[3];
  const d = new Date(rok, +m[2] - 1, +m[1], 12);
  return d.getDate() === +m[1] && d.getMonth() === +m[2] - 1 ? d : null;
}
const dvemi = (n) => String(n).padStart(2, "0");
const pisDatum = (d) => `${dvemi(d.getDate())}.${dvemi(d.getMonth() + 1)}.${d.getFullYear()}`;
function upravDatum(pole) {
  const text = pole.value.trim();
  if (!text) { pole.setCustomValidity(""); return; }
  const sCasem = pole.classList.contains("vstup-datum-cas");
  const m = text.match(/^(\S+?)(?:[\sT]+(\d{1,2})[:.](\d{2}))?$/);
  const d = m && ctiDatum(m[1]);
  if (!d) { pole.setCustomValidity("Zadejte datum jako 20.11.2026" + (sCasem ? " 14:30" : "")); return; }
  pole.setCustomValidity("");
  pole.value = pisDatum(d) + (sCasem ? " " + (m[2] ? `${dvemi(m[2])}:${m[3]}` : "00:00") : "");
}
document.addEventListener("change", (e) => { if (e.target.matches?.("input.vstup-datum")) upravDatum(e.target); }, true);

// hx-confirm (HTMX) přes okno aplikace místo systémového confirm (#126)
document.addEventListener("htmx:confirm", (e) => {
  if (!e.detail.question) return;
  e.preventDefault();
  potvrd(e.detail.question, {ano: "Spustit"}).then((ano) => { if (ano) e.detail.issueRequest(true); });
});
function potvrd(text, {ano = "Ano", ne = "Ne", nebezpecne = false} = {}) {
  const d = document.getElementById("okno-potvrzeni");
  d.querySelector(".potvrzeni-text").textContent = text;
  const bAno = d.querySelector(".potvrzeni-ano"), bNe = d.querySelector(".potvrzeni-ne");
  bAno.textContent = ano; bAno.classList.toggle("nebezpecne", nebezpecne);
  bNe.hidden = ne === null; bNe.textContent = ne || "";
  return new Promise((hotovo) => {
    const konec = (vysledek) => { d.close(); bAno.onclick = bNe.onclick = d.oncancel = null; hotovo(vysledek); };
    bAno.onclick = () => konec(true);
    bNe.onclick = () => konec(false);
    d.oncancel = (e) => { e.preventDefault(); konec(false); };  // Esc = Ne
    d.showModal();
    (ne === null || !nebezpecne ? bAno : bNe).focus();  // u mazání je výchozí Ne
  });
}
const upozorni = (text) => potvrd(text, {ano: "OK", ne: null});
// Formulář s data-potvrdit="text" se odešle až po potvrzení (data-potvrdit-ano = text tlačítka).
// Skryté pole name="zpet" s data-aktualni dostane adresu stránky, odkud se akce spustila (zachová filtr seznamu).
// Kontrola SPZ před uložením (#33): česká SPZ = A–Z a číslice, 5–8 znaků (mezery a pomlčky se vynechají).
// Jiný tvar (zahraniční, s diakritikou…) se uloží až po potvrzení. Zachytává se před HTMX (fáze capture).
document.addEventListener("submit", async (e) => {
  const f = e.target, pole = f.querySelector?.("input[data-kontrola-spz]");
  if (!pole || f.dataset.spzPotvrzena === pole.value) return;
  const spz = pole.value.replace(/[\s-]/g, "").toUpperCase();
  if (!spz || /^[A-Z0-9]{5,8}$/.test(spz)) return;
  e.preventDefault(); e.stopImmediatePropagation();
  if (await potvrd(`SPZ „${pole.value.trim()}“ nemá obvyklý tvar české SPZ (písmena A–Z a číslice, 5–8 znaků). ` +
                   "Je to zahraniční nebo neobvyklá SPZ a chcete ji uložit takto?",
                   {ano: "Uložit takto", ne: "Opravit"})) {
    f.dataset.spzPotvrzena = pole.value; f.requestSubmit();
  } else pole.focus();
}, true);
document.addEventListener("submit", async (e) => {
  const f = e.target;
  f.querySelectorAll("input[name=zpet][data-aktualni]").forEach((p) => { p.value = location.pathname + location.search; });
  if (!f.dataset.potvrdit) return;
  e.preventDefault();
  if (await potvrd(f.dataset.potvrdit, {ano: f.dataset.potvrditAno || "Ano", nebezpecne: true})) f.submit();
});

// ---- Krátká hláška po uložení („Uloženo“) – server ji předá cookie `zprava` (viz routes._se_zpravou).
// Text začínající „!“ = chyba (červeně a déle).
function ukazZpravu(text) {
  const z = document.getElementById("zprava");
  const chyba = text.startsWith("!");
  z.querySelector(".zprava-text").textContent = chyba ? text.slice(1) : text;
  z.hidden = false; z.classList.remove("mizi");
  z.classList.toggle("zprava-chyba", chyba);
  z.setAttribute("role", chyba ? "alert" : "status");
  clearTimeout(z._casovac);
  z._casovac = setTimeout(() => { z.classList.add("mizi"); setTimeout(() => { z.hidden = true; }, 400); },
                          chyba ? 8000 : 3000);
}

// ---- Chyba ve formuláři: kurzor do pole, kterého se týká (server ho pošle v data-pole), a zvýraznit ho.
function oznacChybnePole(koren) {
  const hlaska = (koren || document).querySelector(".chyba[data-pole]");
  if (!hlaska) return;
  const jmeno = hlaska.dataset.pole;
  const rozsah = hlaska.closest("#okno-formular-obsah") || document;
  const pole = rozsah.querySelector(`[name="${jmeno}"]`) ||
               rozsah.querySelector(`[name$="_${jmeno}"]`);  // pole s předponou (v_rok_vyroby, k_nazev…)
  if (!pole) return;
  pole.setAttribute("aria-invalid", "true");
  pole.addEventListener("input", () => pole.removeAttribute("aria-invalid"), {once: true});
  pole.focus();
  if (pole.select) pole.select();
}
document.addEventListener("DOMContentLoaded", () => oznacChybnePole());
// až po ostatních obsluhách (ty vracejí kurzor do pole, kde uživatel byl)
document.addEventListener("htmx:afterSettle", (e) => setTimeout(() => oznacChybnePole(e.detail.target)));

// ---- Klávesy: Ctrl+Enter = uložit formulář (stránka i okno), Delete = odebrat vybraný řádek mřížky.
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    const okno = document.getElementById("okno-formular");
    const form = e.target.closest?.("form.prijem") ||
                 (okno.open ? okno.querySelector("form.prijem") : document.querySelector(".obsah form.prijem, .obsah form.formular"));
    if (form) { e.preventDefault(); form.requestSubmit(); }
    return;
  }
  if (e.key === "Delete" && vybranyRadek && !e.target.closest("input, textarea, select, [contenteditable]")
      && !document.querySelector("dialog[open]")) {
    const tlacitko = document.querySelector(".akce [data-radek=odebrat]:not(:disabled)");
    if (tlacitko) { e.preventDefault(); tlacitko.click(); }
    else if (vybranyRadek.dataset.odebrat) {  // položky zakázky: tlačítka jsou přímo v řádku, Delete se zeptá
      e.preventDefault();
      const cil = vybranyRadek.dataset.odebrat;
      potvrd(vybranyRadek.dataset.odebratText || "Odebrat vybraný řádek?", {ano: "Odebrat", nebezpecne: true})
        .then((ano) => { if (ano) odesliPost(cil); });
    }
  }
});
document.addEventListener("DOMContentLoaded", () => {
  const c = document.cookie.split("; ").find((x) => x.startsWith("zprava="));
  if (!c) return;
  document.cookie = "zprava=; Max-Age=0; path=/";
  ukazZpravu(decodeURIComponent(c.slice(7)).replace(/^"|"$/g, ""));
});

// Chyba HTMX požadavku (např. neaktuální server) nesmí tiše zmizet.
document.addEventListener("htmx:responseError", (e) => {
  upozorni("Akci se nepodařilo provést (chyba " + e.detail.xhr.status + "). " +
           "Zkuste obnovit stránku (F5). Pokud chyba trvá, dejte vědět správci aplikace.");
});
document.addEventListener("htmx:sendError", () => upozorni("Aplikace neodpovídá – je spuštěná?"));

// Datová mřížka: klik vybere řádek, v seznamech (table.klik-otevre) ho rovnou otevře (#39, #89)
// (řádek s atributem data-otevrit, nebo první odkaz v řádku).
// Tlačítka v pravém sloupci s data-radek="otevrit|upravit" pracují s vybraným řádkem.
// data-radek="X": adresa z atributu data-X vybraného řádku (upravit, odebrat, zakazka…);
// "otevrit" bez data-otevrit = první odkaz v řádku.
// data-radek="odebrat": POST na data-odebrat vybraného řádku po potvrzení (text v data-odebrat-text).
const cilRadku = (tr, akce) => akce !== "otevrit" ? tr.dataset[akce]
  : tr.dataset.otevrit || tr.querySelector("a[href]:not([href='#'])")?.getAttribute("href");
function odesliPost(url) {
  const f = document.createElement("form");
  f.method = "post"; f.action = url;
  document.body.appendChild(f); f.submit();
}
let vybranyRadek = null;
const obnovTlacitkaRadku = () => document.querySelectorAll(".akce [data-radek]").forEach((b) => {
  b.disabled = !(vybranyRadek && cilRadku(vybranyRadek, b.dataset.radek));
});
document.addEventListener("DOMContentLoaded", obnovTlacitkaRadku);
// seznam vyměněný přes HTMX (hledání, řazení): vybraný řádek už neplatí
document.addEventListener("htmx:afterSettle", (e) => {
  if (vybranyRadek && !document.contains(vybranyRadek)) { vybranyRadek = null; obnovTlacitkaRadku(); }
});
// změna řazení kliknutím na hlavičku se propíše do formuláře filtru (hledání pak řazení zachová)
document.addEventListener("htmx:pushedIntoHistory", () => {
  const razeni = new URLSearchParams(location.search).get("razeni") || "";
  document.querySelectorAll(".filtr input[name=razeni]").forEach((p) => { p.value = razeni; p.disabled = !razeni; });
});
document.addEventListener("click", (e) => {
  const tlacitko = e.target.closest(".akce [data-radek]");
  if (tlacitko && vybranyRadek) {
    const cil = cilRadku(vybranyRadek, tlacitko.dataset.radek);
    if (cil && tlacitko.dataset.radek === "odebrat") {
      potvrd(vybranyRadek.dataset.odebratText || "Odebrat vybraný řádek?", {ano: "Odebrat", nebezpecne: true})
        .then((ano) => { if (ano) odesliPost(cil); });
    }
    else if (cil && tlacitko.hasAttribute("data-okno")) otevriOkno(cil);
    else if (cil) window.location.href = cil;
    return;
  }
  const tr = e.target.closest(".obsah tbody tr");
  if (!tr) return;
  tr.parentElement.querySelectorAll("tr.vybrany").forEach((r) => r.classList.remove("vybrany"));
  tr.classList.add("vybrany");
  vybranyRadek = tr;
  obnovTlacitkaRadku();
  // seznamy (#39): jeden klik na řádek otevře (odkazy a tlačítka v řádku fungují samy, Ctrl+klik = nová karta)
  if (tr.closest("table.klik-otevre") && !e.target.closest("a, button, input, select, textarea, label")) {
    const cil = cilRadku(tr, "otevrit");
    if (!cil) return;
    if (e.ctrlKey || e.metaKey) window.open(cil, "_blank");
    else if (tr.hasAttribute("data-okno") && !formularNaStrance()) otevriOkno(cil);
    else window.location.href = cil;
  }
});
document.addEventListener("dblclick", (e) => {
  const tr = e.target.closest(".obsah tbody tr");
  if (!tr || e.target.closest("a, button, input, select, textarea, label")) return;
  if (tr.hasAttribute("data-pridat")) { pridejRadek(tr); return; }  // okno Přidat z ceníku
  if (tr.hasAttribute("data-historie")) { prepniOznaceni(tr); return; }  // okno Z historie (#188)
  const cil = cilRadku(tr, "otevrit");
  // řádek s data-okno (např. ceník) se dvojklikem otevře jako okno
  if (cil && tr.hasAttribute("data-okno") && !formularNaStrance()) otevriOkno(cil);
  else if (cil) window.location.href = cil;
});

// ---- Formulář jako okno (nová zakázka, úprava zakázky) – jako okna ve starém systému.
// Odkaz / tlačítko s atributem data-okno otevře formulář v dialogu nad aktuální stránkou.
// Server s parametrem okno=1 vrátí jen obsah okna; po uložení stránku přesměruje nebo obnoví.
const oknoFormulare = () => document.getElementById("okno-formular");
let oknoZmeneno = false;
let obnovitPoZavreni = false;  // zůstane platné, i když se v okně otevře jiné okno
function otevriOkno(url) {
  if (document.querySelector("#okno-formular-obsah [data-obnovit-po-zavreni]")) obnovitPoZavreni = true;
  const adresa = new URL(url, window.location.href);
  adresa.searchParams.set("okno", "1");
  htmx.ajax("GET", adresa.pathname + adresa.search, {target: "#okno-formular-obsah", swap: "innerHTML"})
    .then(() => {
      const okno = oknoFormulare();
      oknoZmeneno = false;
      if (!okno.open) okno.showModal();
      okno.querySelector("[autofocus]")?.focus();
    });
}
// data-s-hledanim="kod" (okno Přidat z ceníku, #68/#69): do adresy přidá text z hledání okna jako parametr
function adresaSpoustece(a) {
  const url = a.getAttribute("href");
  const text = a.closest(".okno-cenik")?.querySelector("input[type=search]")?.value.trim();
  if (!a.dataset.sHledanim || !text) return url;
  const adresa = new URL(url, window.location.href);
  adresa.searchParams.set(a.dataset.sHledanim, text);
  return adresa.pathname + adresa.search;
}
// na stránce, která už formulář zobrazuje celý, se okno neotvírá (duplicitní pole)
const formularNaStrance = () =>
  [...document.querySelectorAll("form.prijem")].some((f) => !f.closest("#okno-formular"));
async function zavriOkno() {
  if (oknoZmeneno && !(await potvrd("Zavřít okno bez uložení změn?",
                                    {ano: "Zavřít bez uložení", ne: "Pokračovat v úpravách", nebezpecne: true}))) return;
  const obsah = document.getElementById("okno-formular-obsah");
  // okno, které už něco uložilo (např. přidání z ceníku), po zavření obnoví stránku pod sebou
  const obnovit = obnovitPoZavreni || obsah.querySelector("[data-obnovit-po-zavreni]");
  obnovitPoZavreni = false;
  oknoFormulare().close();
  obsah.innerHTML = "";  // uvolní id polí formuláře
  if (obnovit) window.location.reload();
}
document.addEventListener("click", async (e) => {
  const spoustec = e.target.closest("a[data-okno]");
  if (spoustec && !formularNaStrance() && !e.ctrlKey && !e.shiftKey && !e.metaKey) {
    e.preventDefault();
    otevriOkno(adresaSpoustece(spoustec));
  }
  if (e.target.closest("[data-zavrit-okno]")) zavriOkno();
});
// hledání a okna s data-bez-potvrzeni (výběr z ceníku) nejsou „neuložené změny“
document.addEventListener("input", (e) => {
  if (e.target.closest("#okno-formular") && e.target.type !== "search" && !e.target.closest("[data-bez-potvrzeni]"))
    oknoZmeneno = true;
});
document.addEventListener("DOMContentLoaded", () => {
  // Esc: stejné jako Zrušit (zeptá se, pokud jsou neuložené změny)
  oknoFormulare().addEventListener("cancel", (e) => { e.preventDefault(); zavriOkno(); });
});

// ---- Dvojice cen bez DPH / s DPH (ceník): psát jde do kteréhokoli pole, druhé se přepočítá podle sazby DPH.
// Skryté pole data-cena="zdroj" říká serveru, které pole uživatel psal naposledy („s“ = s DPH).
const cisloZPole = (t) => { const c = parseFloat(String(t).replace(/\s/g, "").replace(",", ".")); return isNaN(c) ? null : c; };
const naPole = (c) => (Math.round(c * 100) / 100).toFixed(2).replace(".", ",").replace(/,00$/, "");
function prepocitejDvojici(dvojice, zdroj) {
  const sazbaPole = dvojice.closest("form")?.querySelector("[data-sazba-dph]");
  const sazba = cisloZPole(sazbaPole ? sazbaPole.value : "0") || 0;
  const bez = dvojice.querySelector('[data-cena="bez"]'), s = dvojice.querySelector('[data-cena="s"]');
  const pole = dvojice.querySelector('[data-cena="zdroj"]');
  if (!bez || !s) return;
  zdroj = zdroj || (pole.value === "s" ? "s" : "bez");
  pole.value = zdroj === "s" ? "s" : "";
  const z = zdroj === "s" ? s : bez, cil = zdroj === "s" ? bez : s;
  const c = cisloZPole(z.value);
  cil.value = c === null ? "" : naPole(zdroj === "s" ? c / (1 + sazba / 100) : c * (1 + sazba / 100));
}
document.addEventListener("input", (e) => {
  const druh = e.target.dataset?.cena;
  if (druh === "bez" || druh === "s") prepocitejDvojici(e.target.closest(".dvojice-cen"), druh);
  if (e.target.matches?.("[data-sazba-dph]"))
    e.target.closest("form").querySelectorAll(".dvojice-cen").forEach((d) => prepocitejDvojici(d));
  if (e.target.closest?.("form")) hlidejProdejPodNakupem(e.target.closest("form"));
});
// Prodejní cena pod nákupní (#33): jen upozornění pod cenami, uložit jde dál (porovnává ceny bez DPH).
function hlidejProdejPodNakupem(form) {
  const hlaska = form.querySelector("[data-pod-nakupem]");
  if (!hlaska) return;
  const prodej = cisloZPole(form.querySelector("[name=cena]")?.value ?? "");
  const nakup = cisloZPole(form.querySelector("[name=nakupni_cena]")?.value ?? "");
  hlaska.hidden = !(prodej !== null && nakup !== null && prodej < nakup);
}
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("form").forEach(hlidejProdejPodNakupem));
document.addEventListener("htmx:afterSettle", (e) => e.detail.target.querySelectorAll?.("form").forEach(hlidejProdejPodNakupem));

// ---- Formuláře s třídou enter-dalsi: Enter v poli přejde na další pole (formulář neodešle), jako ve starém systému.
document.addEventListener("keydown", (e) => {
  const pole = e.target, form = pole.closest && pole.closest("form.enter-dalsi");
  if (!form || e.key !== "Enter" || pole.tagName === "TEXTAREA" || pole.type === "submit" || pole.tagName === "BUTTON") return;
  e.preventDefault();
  const prvky = [...form.querySelectorAll("input:not([type=hidden]):not([readonly]), select, textarea")]
    .filter((p) => !p.disabled && p.offsetParent !== null && p.type !== "checkbox" && p.type !== "radio");
  const dalsi = prvky[prvky.indexOf(pole) + 1];
  if (dalsi) dalsi.focus();
});
// Po doplnění panelu (HTMX) vrátit kurzor do pole, kde uživatel právě byl.
let fokus = null;
document.addEventListener("htmx:beforeSwap", () => {
  const a = document.activeElement;
  fokus = a && a.name && a.closest("form.enter-dalsi") ? {form: a.closest("form").id, name: a.name} : null;
});
document.addEventListener("htmx:afterSettle", () => {
  const pole = fokus && document.querySelector(`#${fokus.form} [name="${fokus.name}"]`);
  if (pole && document.activeElement !== pole && !document.getElementById("okno-databaze").open) pole.focus();
  fokus = null;
});

// ---- Tlačítko Načti u VIN: údaje vozidla z Registru silničních vozidel (GET /vozidla/registr).
// Vyplní pole formuláře s předponou `predpona` (v_ na příjmu); pole z `jen_prazdne` jen když jsou prázdná.
async function nactiZRegistru(tlacitko, predpona) {
  const form = tlacitko.closest("form");
  const pole = (jmeno) => form.querySelector(`[name="${predpona}${jmeno}"]`);
  const vin = pole("vin").value.replace(/\s/g, "");
  if (!vin) { upozorni("Nejdřív zadejte VIN vozidla."); pole("vin").focus(); return; }
  tlacitko.disabled = true; tlacitko.setAttribute("aria-busy", "true");
  try {
    const odpoved = await fetch("/vozidla/registr?vin=" + encodeURIComponent(vin));
    if (!odpoved.ok) throw new Error(odpoved.status);
    const v = await odpoved.json();
    if (v.chyba) { upozorni(v.chyba); return; }
    let zmeneno = 0;
    for (let [jmeno, hodnota] of Object.entries(v.pole)) {
      const p = pole(jmeno);
      if (p && p.classList.contains("vstup-datum") && ctiDatum(hodnota)) hodnota = pisDatum(ctiDatum(hodnota));
      if (!p || p.value === hodnota || (v.jen_prazdne.includes(jmeno) && p.value.trim())) continue;
      p.value = hodnota; zmeneno++;
      p.classList.add("doplneno-z-registru");
      p.dispatchEvent(new Event("input", {bubbles: true}));  // okno pozná neuložené změny
    }
    ukazZpravu(`Registr vozidel: ${zmeneno ? "doplněno polí: " + zmeneno : "údaje se shodují"}` +
               (v.souhrn ? ` (${v.souhrn})` : "") + ". Nezapomeňte uložit.");
  } catch (e) {
    upozorni("Načtení z registru vozidel se nepovedlo (" + e.message + ").");
  } finally {
    tlacitko.disabled = false; tlacitko.removeAttribute("aria-busy");
  }
}

// ---- Tlačítko Načti u IČO (#11): název, adresa a DIČ firmy z ARES; doplněná pole zeleně, uloží se až Uložit.
async function nactiZAres(tlacitko, predpona) {
  const form = tlacitko.closest("form");
  const pole = (jmeno) => form.querySelector(`[name="${predpona}${jmeno}"]`);
  const ico = pole("ico").value.replace(/\s/g, "");
  if (!ico) { upozorni("Nejdřív zadejte IČO."); pole("ico").focus(); return; }
  tlacitko.disabled = true; tlacitko.setAttribute("aria-busy", "true");
  try {
    const odpoved = await fetch("/zakaznici/ares?ico=" + encodeURIComponent(ico));
    if (!odpoved.ok) throw new Error(odpoved.status);
    const v = await odpoved.json();
    if (v.chyba) { upozorni(v.chyba); pole("ico").focus(); return; }
    let zmeneno = 0;
    for (const [jmeno, hodnota] of Object.entries(v.pole)) {
      const p = pole(jmeno);
      if (!p || p.value === hodnota) continue;
      p.value = hodnota; zmeneno++;
      p.classList.add("doplneno-z-registru");
      p.dispatchEvent(new Event("input", {bubbles: true}));  // okno pozná neuložené změny
    }
    ukazZpravu(`ARES: ${zmeneno ? "doplněno polí: " + zmeneno : "údaje se shodují"} (${v.pole.nazev || ico}). Nezapomeňte uložit.`);
  } catch (e) {
    upozorni("Načtení z ARES se nepovedlo (" + e.message + ").");
  } finally {
    tlacitko.disabled = false; tlacitko.removeAttribute("aria-busy");
  }
}

// ---- #185: ovládání šipkami. Seznamy: ↑/↓ výběr řádku, Enter otevře, ←/→ další / předchozí záložka
// hlavního menu (dokola), Insert = nový záznam, písmeno/číslice skočí do hledání, ↓ z hledání zpět
// do seznamu, Esc z hledání ven. Detail zakázky: ↑/↓ položky materiálu i práce, Enter upraví, Insert = ceník.
// Nic z toho neplatí při psaní do pole, v rozbalovací nabídce, v otevřeném okně ani s Ctrl/Alt.
const mrizkaPolozek = () => document.querySelector(".obsah table.mrizka-polozek");
function radkyKlavesnici() {
  if (mrizkaPolozek()) return [...document.querySelectorAll(".obsah table.mrizka-polozek tbody tr")];
  const t = document.querySelector("#seznam table.klik-otevre, .obsah table.klik-otevre");
  return t ? [...t.querySelectorAll("tbody tr")].filter((tr) => cilRadku(tr, "otevrit")) : [];
}
function vyberRadekKlavesnici(tr) {
  if (!tr) return;
  document.querySelectorAll(".obsah tbody tr.vybrany").forEach((r) => r.classList.remove("vybrany"));
  tr.classList.add("vybrany");
  vybranyRadek = tr;
  obnovTlacitkaRadku();
  tr.scrollIntoView({block: "nearest"});
}
const poleHledani = () => document.querySelector(".obsah .filtr input[type=search]");
function otevriRadekKlavesnici(tr) {
  if (mrizkaPolozek()) {
    if (tr.dataset.upravit) { tr.hasAttribute("data-okno") ? otevriOkno(tr.dataset.upravit) : (location.href = tr.dataset.upravit); }
    return;
  }
  const cil = cilRadku(tr, "otevrit");
  if (!cil) return;
  if (tr.hasAttribute("data-okno") && !formularNaStrance()) otevriOkno(cil); else location.href = cil;
}
// ←/→ na seznamu: sousední záložka hlavního menu, za poslední zase první (jen na těchto seznamech)
const ZALOZKY_MENU = ["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace", "/faktury", "/prijem"];
function prepniZalozku(smer) {
  const i = ZALOZKY_MENU.indexOf(location.pathname);
  if (i < 0) return false;
  location.href = ZALOZKY_MENU[(i + smer + ZALOZKY_MENU.length) % ZALOZKY_MENU.length];
  return true;
}
document.addEventListener("DOMContentLoaded", () => {
  // po otevření seznamu je vybraný první řádek (kurzor zůstává, kde byl – např. v hledání)
  if (!vybranyRadek) { const r = radkyKlavesnici(); if (r.length && !mrizkaPolozek()) vyberRadekKlavesnici(r[0]); }
});
document.addEventListener("htmx:afterSettle", (e) => {
  if (e.detail.target.id === "seznam" && !vybranyRadek) {
    const r = radkyKlavesnici();
    if (r.length) { r[0].classList.add("vybrany"); vybranyRadek = r[0]; obnovTlacitkaRadku(); }
  }
});
function otevriInsert() {
  // Detail zakázky: ceník oddílu vybraného řádku (materiál nebo práce). Bez výběru ceník materiálu.
  if (mrizkaPolozek()) {
    const sekce = vybranyRadek && document.contains(vybranyRadek)
      ? vybranyRadek.closest("section.sekce-polozek") : null;
    const odkaz = (sekce || document.querySelector("#polozky-material"))?.querySelector("[data-insert]");
    if (odkaz) odkaz.click();
    return;
  }
  document.querySelector(".obsah [data-insert]")?.click();
}
// Nápověda v liště: klávesy jen té obrazovky (nebo otevřeného okna), ne nová stránka.
const RADKY_NAPOVEDY = {
  seznam: [
    ["↑  ↓", "vybere řádek"],
    ["Enter", "otevře vybraný řádek"],
    ["←  →", "další a předchozí záložka menu, dokola"],
    ["Insert", "nový záznam"],
    ["Ctrl+N", "totéž co Insert"],
    ["Home / End", "první a poslední řádek"],
    ["Page Up / Page Down", "o deset řádků"],
    ["psaní", "písmeno nebo číslice skočí do hledání; ↓ zpět do seznamu, Esc z hledání ven"],
  ],
  seznamBez: [
    ["↑  ↓", "vybere řádek"],
    ["Enter", "otevře vybraný řádek"],
    ["←  →", "další a předchozí záložka menu, dokola"],
    ["Home / End", "první a poslední řádek"],
    ["Page Up / Page Down", "o deset řádků"],
    ["psaní", "písmeno nebo číslice skočí do hledání; ↓ zpět do seznamu, Esc z hledání ven"],
  ],
  zakazka: [
    ["↑  ↓", "položky materiálu a práce"],
    ["Enter", "úprava vybrané položky"],
    ["Insert", "ceník oddílu vybraného řádku; bez výběru ceník materiálu"],
    ["Delete", "odebere položku, až po dotazu"],
    ["Ctrl+←  Ctrl+→", "množství o 1; pod 1 jen ručně"],
    ["Home / End", "první a poslední řádek"],
    ["Page Up / Page Down", "o deset řádků"],
    ["Esc", "zpět na seznam zakázek; z pole nejdřív vyskočí, okno zavře"],
  ],
  mrizka: [
    ["↑  ↓", "vybere řádek"],
    ["Enter", "otevře vybraný řádek"],
    ["Home / End", "první a poslední řádek"],
    ["Page Up / Page Down", "o deset řádků"],
  ],
  karta: [
    ["↑  ↓", "vybere řádek"],
    ["Enter", "otevře vybraný řádek"],
    ["Home / End", "první a poslední řádek"],
    ["Page Up / Page Down", "o deset řádků"],
    ["Esc", "zpět na seznam; z pole nejdřív vyskočí, okno zavře"],
  ],
  cenik: [
    ["Tab / Shift+Tab", "přepne ceník"],
    ["↑  ↓", "vybere řádek"],
    ["←  →", "ubere nebo přidá kus; pod 1 jen ručně"],
    ["Enter", "vloží"],
    ["Esc", "zavře okno"],
  ],
  historie: [
    ["↑  ↓", "vybere řádek"],
    ["Mezerník", "zaškrtne řádek"],
    ["Enter", "vloží označené"],
    ["Esc", "zavře okno"],
  ],
  formular: [
    ["Enter", "další pole"],
    ["Ctrl+Enter", "uloží"],
    ["Esc", "zavře okno; při změnách se zeptá"],
  ],
  nastaveni: [
    ["Enter", "další pole"],
    ["Ctrl+Enter", "uloží"],
  ],
  obecne: [
    ["?", "na této obrazovce nejsou zvláštní klávesy"],
  ],
};
function polozkyNapovedy() {
  const obsah = document.getElementById("okno-formular-obsah");
  const okno = document.getElementById("okno-formular");
  if (okno?.open && obsah) {
    if (obsah.querySelector(".okno-historie")) return RADKY_NAPOVEDY.historie;
    if (obsah.querySelector(".okno-cenik")) return RADKY_NAPOVEDY.cenik;
    return RADKY_NAPOVEDY.formular;
  }
  const p = location.pathname;
  if (["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace"].includes(p)) return RADKY_NAPOVEDY.seznam;
  if (p === "/faktury" || p === "/prijem") return RADKY_NAPOVEDY.seznamBez;
  if (/^\/zakazky\/\d+$/.test(p)) return RADKY_NAPOVEDY.zakazka;
  if (/^\/vozidla\/\d+$/.test(p) || /^\/zakaznici\/\d+$/.test(p)) return RADKY_NAPOVEDY.karta;
  if (p.startsWith("/nastaveni")) return RADKY_NAPOVEDY.nastaveni;
  if (document.querySelector(".obsah form.prijem, .obsah form.formular")) return RADKY_NAPOVEDY.formular;
  if (radkyKlavesnici().length) return RADKY_NAPOVEDY.mrizka;
  return RADKY_NAPOVEDY.obecne;
}
function ukazNapovedu() {
  const d = document.getElementById("okno-napoveda-klaves");
  const telo = d.querySelector("tbody");
  telo.replaceChildren();
  for (const [klavesa, popis] of polozkyNapovedy()) {
    const tr = document.createElement("tr");
    const a = document.createElement("td");
    const b = document.createElement("td");
    a.textContent = klavesa;
    b.textContent = popis;
    tr.append(a, b);
    telo.append(tr);
  }
  if (!d.open) d.showModal();
}
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("tlacitko-napoveda")?.addEventListener("click", ukazNapovedu);
  // Po Esc prohlížeč vrátí výběr na tlačítko Nápověda a šipky pak seznam neposlouchají.
  document.getElementById("okno-napoveda-klaves")?.addEventListener("close", () => {
    // Prohlížeč vrací výběr na tlačítko až po zavření, někdy později než první odložený krok.
    const pust = () => {
      if (document.activeElement?.id === "tlacitko-napoveda") document.activeElement.blur();
    };
    setTimeout(pust, 0);
    setTimeout(pust, 50);
  });
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "n") {
    e.preventDefault();  // nezaloží nové okno prohlížeče
    if (document.querySelector("dialog[open]")) return;
    if (e.target.closest("input, textarea, select, [contenteditable]")) return;
    if (!["/zakazky", "/vozidla", "/zakaznici", "/cenik", "/prace"].includes(location.pathname)) return;
    document.querySelector(".obsah [data-insert]")?.click();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey
      && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
    if (document.querySelector("dialog[open]")) return;
    // Tlačítko +/− v řádku smí mít výběr: jinak druhá šipka množství už nic neudělá.
    if (e.target.closest("input, textarea, select, [contenteditable], button, a[href]")
        && !e.target.closest(".mnozstvi-radku button.krok")) return;
    if (!mrizkaPolozek() || !vybranyRadek || !document.contains(vybranyRadek)) return;
    e.preventDefault();
    vybranyRadek.querySelector(`[data-krok="${e.key === "ArrowRight" ? 1 : -1}"]`)?.click();
    return;
  }
  if (e.ctrlKey || e.altKey || e.metaKey || document.querySelector("dialog[open]")) return;
  const hledani = poleHledani();
  if (hledani && e.target === hledani) {  // v hledání: ↓ do seznamu, Esc ven z pole
    if (e.key === "ArrowDown" || e.key === "Escape") {
      e.preventDefault();
      hledani.blur();
      if (e.key === "ArrowDown") vyberRadekKlavesnici(vybranyRadek && document.contains(vybranyRadek) ? vybranyRadek : radkyKlavesnici()[0]);
    }
    return;
  }
  if (e.key === "Escape") {  // detail zakázky, vozidla a zákazníka: Esc = tlačítko Zpět
    const pole = e.target.closest("input, textarea, select, [contenteditable]");
    if (pole) { e.preventDefault(); pole.blur(); return; }
    if (/^\/(zakazky|vozidla|zakaznici)\/\d+$/.test(location.pathname)) {
      const zpet = document.querySelector(".akce a.zpet");
      if (zpet) { e.preventDefault(); zpet.click(); }
    }
    return;
  }
  if (e.target.closest("input, textarea, select, [contenteditable], button, a[href]")) return;
  const radky = radkyKlavesnici();
  const i = radky.indexOf(vybranyRadek);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!radky.length) return;
    e.preventDefault();
    vyberRadekKlavesnici(i < 0 ? radky[0] : radky[Math.min(Math.max(i + (e.key === "ArrowDown" ? 1 : -1), 0), radky.length - 1)]);
  } else if (e.key === "Enter") {
    if (i < 0) return;
    e.preventDefault();
    otevriRadekKlavesnici(vybranyRadek);
  } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    if (prepniZalozku(e.key === "ArrowRight" ? 1 : -1)) e.preventDefault();
  } else if (e.key === "Home" || e.key === "End") {
    if (!radky.length) return;
    e.preventDefault();
    vyberRadekKlavesnici(e.key === "Home" ? radky[0] : radky[radky.length - 1]);
  } else if (e.key === "PageUp" || e.key === "PageDown") {
    if (!radky.length) return;
    e.preventDefault();
    const od = i < 0 ? 0 : i;
    const krok = e.key === "PageDown" ? 10 : -10;
    vyberRadekKlavesnici(radky[Math.min(Math.max(od + krok, 0), radky.length - 1)]);
  } else if (e.key === "Insert") {
    if (mrizkaPolozek() || document.querySelector(".obsah [data-insert]")) {
      e.preventDefault();
      otevriInsert();
    }
  } else if (hledani && e.key.length === 1 && /[\p{L}\p{N}]/u.test(e.key)) {
    hledani.focus();  // znak se zapíše do pole hledání
    const konec = hledani.value.length;
    hledani.setSelectionRange(konec, konec);
  }
});

// ---- Okno Přidat z ceníku: řádek s data-pridat přidá dvojklik nebo Enter (s množstvím z řádku, předvyplněno 1).
// Šipky ↓ ↑ v hledání i v mřížce vybírají řádek, Enter ho přidá.
function pridejRadek(tr) {
  const form = tr.querySelector("form.radek-pridat");
  const pole = form && form.querySelector("[name=mnozstvi]");
  if (!form) return;
  if (pole && !pole.value.trim()) pole.value = "1";
  form.requestSubmit();
}
// #96: Enter v hledání materiálu – text přesně shodný s kódem dílu (bez ohledu na velikost písmen a mezery)
// díl vloží, jinak se otevře Nový materiál s kódem z hledání. Nejdřív se počká na čerstvé výsledky hledání.
const kodProShodu = (t) => String(t || "").toUpperCase().replace(/\s+/g, "");
let enterCeka = false;
async function enterVHledaniMaterialu(okno, hledani) {
  const hledany = kodProShodu(hledani.value);
  if (!hledany || enterCeka) return;
  enterCeka = true;
  try {
    const vysledky = okno.querySelector("#cenik-vysledky");
    await new Promise((hotovo) => {
      const konec = () => { clearTimeout(pojistka); vysledky.removeEventListener("htmx:afterSettle", konec); hotovo(); };
      const pojistka = setTimeout(konec, 3000);
      vysledky.addEventListener("htmx:afterSettle", konec);
      htmx.trigger(hledani, "search");  // hledání hned, bez čekání na prodlevu psaní
    });
    if (!document.contains(hledani) || kodProShodu(hledani.value) !== hledany) return;  // mezitím se psalo dál
    const shoda = [...okno.querySelectorAll(".vyber-cenik tbody tr[data-pridat]")]
      .find((tr) => kodProShodu(tr.dataset.kod) === hledany);
    if (shoda) pridejRadek(shoda);
    else okno.querySelector(".tlacitko-novy[data-s-hledanim]").click();
  } finally {
    enterCeka = false;
  }
}
function vyberRadekCeniku(tr) {
  if (!tr) return;
  tr.parentElement.querySelectorAll("tr.vybrany").forEach((r) => r.classList.remove("vybrany"));
  tr.classList.add("vybrany");
  vybranyRadek = tr;
  tr.scrollIntoView({block: "nearest"});
}
// ---- Okno Z historie (#188): ↓ ↑ vybírají řádek (kurzor na jeho zaškrtávátko), Mezerník zaškrtne,
// Enter vloží všechno označené (bez označení vybraný řádek), dvojklik zaškrtne. V polích se píše normálně.
function prepniOznaceni(tr) {
  const c = tr.querySelector("input[name=vybrano]");
  if (c) c.checked = !c.checked;
}
function vlozHistorii(okno) {
  const form = okno.querySelector("#vlozit-historii");
  if (!form) return;
  if (!form.querySelector("input[name=vybrano]:checked")) {
    const vybrany = okno.querySelector(".vyber-historie tbody tr.vybrany");
    if (!vybrany) return;
    vybrany.querySelector("input[name=vybrano]").checked = true;
  }
  form.requestSubmit();
}
document.addEventListener("keydown", (e) => {
  const okno = e.target.closest?.(".okno-historie");
  if (!okno || e.ctrlKey || e.altKey || e.metaKey) return;
  const radky = [...okno.querySelectorAll(".vyber-historie tbody tr[data-historie]")];
  const vybrany = radky.find((r) => r.classList.contains("vybrany"));
  const vTextu = e.target.matches("input[type=search], input[type=text]");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!radky.length) return;
    e.preventDefault();
    const i = radky.indexOf(vybrany);
    const cil = radky[i < 0 ? 0 : (e.key === "ArrowDown" ? Math.min(i + 1, radky.length - 1) : Math.max(i - 1, 0))];
    vyberRadekCeniku(cil);
    cil.querySelector("input[name=vybrano]")?.focus();
  } else if (e.key === "Enter") {
    e.preventDefault();
    vlozHistorii(okno);
  } else if (e.key === " " && !vTextu) {
    const tr = e.target.closest("tr[data-historie]") || vybrany;
    if (!tr) return;
    e.preventDefault();
    prepniOznaceni(tr);
  }
}, true);
document.addEventListener("keydown", (e) => {
  const okno = e.target.closest?.(".okno-cenik");
  if (okno?.classList.contains("okno-historie")) return;  // vlastní obsluha výše
  if (!okno || !["ArrowDown", "ArrowUp", "Enter", "Tab", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  if (e.target.closest("form.radek-pridat") || e.target.closest("button, a")) return;  // pole množství: Enter = Přidat
  const radky = [...okno.querySelectorAll(".vyber-cenik tbody tr[data-pridat]")];
  const vybrany = radky.find((r) => r.classList.contains("vybrany"));
  if (e.key === "Tab") {  // #185: Tab / Shift+Tab přepne ceník (sklady, Z historie) – text hledání zůstane
    const zdroje = [...okno.querySelectorAll(".prepinac-katalogu a[href]")];
    if (zdroje.length < 2) return;
    e.preventDefault();
    const i = zdroje.findIndex((a) => a.classList.contains("aktivni"));
    zdroje[(i + (e.shiftKey ? -1 : 1) + zdroje.length) % zdroje.length].click();
    return;
  }
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {  // #185: ←/→ ubere / přidá kus vybranému řádku
    if (!vybrany) return;  // bez vybraného řádku posouvají kurzor v hledání
    e.preventDefault();
    vybrany.querySelector(`[data-krok="${e.key === "ArrowRight" ? 1 : -1}"]`)?.click();
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    if (vybrany) pridejRadek(vybrany);
    else if (e.target.matches("input[type=search]") && okno.querySelector(".tlacitko-novy[data-s-hledanim]"))
      enterVHledaniMaterialu(okno, e.target);
    else if (radky.length === 1) pridejRadek(radky[0]);  // práce: jediný nalezený řádek
    return;
  }
  e.preventDefault();
  const i = radky.indexOf(vybrany);
  vyberRadekCeniku(radky[e.key === "ArrowDown" ? Math.min(i + 1, radky.length - 1) : Math.max(i - 1, 0)]);
});
// Po přidání (okno se znovu vykreslí) kurzor zpět do hledání a okno nehlásí neuložené změny;
// po uložení karty ceníku otevřené z tohoto okna se okno ceníku vrátí.
// Okno Přidat z ceníku (#46): Vložit (tlačítko, Enter, dvojklik) zapíše řádek rovnou do zakázky (HTMX),
// okno zůstane otevřené s potvrzením a po zavření se detail zakázky obnoví.
const hlaseniOkna = (text, chyba = false) => {
  const p = document.querySelector("#okno-formular-obsah .hlaseni-okna");
  if (p) { p.textContent = text; p.className = "hlaseni-okna " + (chyba ? "chyba" : "uspech"); }
};
const textMnozstvi = (c) => String(Math.round(c * 1000) / 1000).replace(".", ",");
// Tlačítka − / + u množství (okno ceníku, řádky zakázky). Minus nejde pod 1 (menší množství se píše ručně).
// V řádku zakázky se uloží až chvíli po posledním kliknutí (víc kliknutí = jedno uložení).
let casovacKroku = null;
// Tlačítko Kopírovat (např. VIN na kartě vozidla): text z data-kopirovat do schránky, krátce zelená fajfka (#154)
// #195: na http (síť dílny) není navigator.clipboard. Náhradní kopírování nesmí záviset na označení textu –
// řádky seznamů mají user-select: none a prohlížeč pak zkopíroval prázdný výběr. Text se proto vloží přímo
// v události copy. Fajfka jen při skutečném úspěchu, jinak hláška s textem k ručnímu zkopírování.
function kopirujNahradne(text) {
  let zapsano = false;
  const priKopirovani = (ev) => { ev.clipboardData.setData("text/plain", text); ev.preventDefault(); zapsano = true; };
  document.addEventListener("copy", priKopirovani, true);
  const pole = Object.assign(document.createElement("textarea"), {value: text, readOnly: true});
  pole.style.cssText = "position:fixed;top:0;left:0;opacity:0;user-select:text;-webkit-user-select:text";
  document.body.append(pole);
  pole.focus(); pole.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  pole.remove();
  document.removeEventListener("copy", priKopirovani, true);
  return ok && zapsano;
}
async function kopiruj(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* zkusit náhradní */ }
  }
  return kopirujNahradne(text);
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-kopirovat]");
  if (!b) return;
  const text = b.dataset.kopirovat;
  if (!(await kopiruj(text))) {
    ukazZpravu("!Kopírování se nepovedlo – označte text a stiskněte Ctrl+C: " + text);
    return;
  }
  const popisek = b.dataset.popisek ||= b.title;
  b.classList.add("zkopirovano"); b.title = "Zkopírováno";
  clearTimeout(b._casovac);
  b._casovac = setTimeout(() => { b.classList.remove("zkopirovano"); b.title = popisek; }, 1500);
});
document.addEventListener("click", (e) => {
  const tlacitko = e.target.closest("[data-krok]");
  if (!tlacitko) return;
  e.preventDefault();
  const pole = tlacitko.closest(".krokovac").querySelector("input");
  const ted = cisloZPole(pole.value) ?? 0;
  const krok = Number(tlacitko.dataset.krok);
  const nove = krok > 0 ? ted + krok : (ted > 1 ? Math.max(1, ted + krok) : ted);
  if (nove === ted) return;
  pole.value = textMnozstvi(nove);
  if (document.activeElement === tlacitko) tlacitko.blur();
  const form = pole.closest("form.mnozstvi-radku");
  if (form) {
    const tr = form.closest("tr");
    if (tr?.dataset.otevrit) sessionStorage.setItem("autoservis-vyber", tr.dataset.otevrit);
    clearTimeout(casovacKroku);
    casovacKroku = setTimeout(() => form.requestSubmit(), 700);
  }
});
document.addEventListener("click", (e) => {
  // tlačítko Smazat přímo v řádku (položky zakázky) – maže hned, bez potvrzení
  const smazat = e.target.closest("[data-smazat-radek]");
  if (smazat) { e.stopPropagation(); odesliPost(smazat.dataset.smazatRadek); }
});
document.addEventListener("htmx:afterSettle", (e) => {
  if (e.detail.target.id !== "okno-formular-obsah") return;
  if (e.detail.target.querySelector("[data-bez-potvrzeni]")) oknoZmeneno = false;
  const hledani = e.detail.target.querySelector(".okno-cenik input[type=search]");
  if (hledani && document.activeElement === document.body) hledani.focus();
});

// ---- Zvýrazněný řádek (např. právě uložená položka ceníku): vybrat ho a odrolovat na něj.
document.addEventListener("DOMContentLoaded", () => {
  // Po uložení množství se stránka překreslí. Stejný řádek vybrat znovu, ať Ctrl+šipka jde opakovat.
  const ulozene = sessionStorage.getItem("autoservis-vyber");
  if (ulozene) {
    sessionStorage.removeItem("autoservis-vyber");
    const zachovat = [...document.querySelectorAll(".obsah tbody tr")].find((r) => r.dataset.otevrit === ulozene);
    if (zachovat) {
      zachovat.classList.add("vybrany");
      vybranyRadek = zachovat;
      obnovTlacitkaRadku();
      zachovat.scrollIntoView({block: "nearest"});
      return;
    }
  }
  const tr = document.querySelector(".obsah tbody tr.zvyrazneny");
  if (!tr) return;
  tr.classList.add("vybrany"); vybranyRadek = tr; obnovTlacitkaRadku();
  tr.scrollIntoView({block: "center"});
});
