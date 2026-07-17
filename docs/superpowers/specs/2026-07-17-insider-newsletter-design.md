# Design: Insider Newsletter ("Insider Weekly" — nome di lavoro)

**Data:** 2026-07-17
**Stato:** approvato in brainstorming, in attesa di review finale utente
**Progetto padre:** InsiderTracker (segnali SEC Form 4, live con 158 test pytest)

---

## 1. Obiettivo

Creare una rendita passiva e automatizzabile monetizzando i segnali che InsiderTracker già produce, tramite una newsletter freemium in doppia lingua (EN + IT). Vincoli fondanti:

- **Costi fissi zero** per l'implementazione e l'esercizio (solo fee percentuali sulle vendite)
- **Tempo a regime minimo**: review di pochi minuti, il resto automatico
- **Nessuna modifica al sistema InsiderTracker live**: la newsletter legge l'output esistente, non tocca il bot
- **Nessuna costruzione di audience attiva**: crescita solo organica, sui canali già esistenti o automatizzabili

## 2. Prodotto

### Tier gratuito — recap settimanale (beehiiv)
- Due pubblicazioni beehiiv sul piano gratuito (Launch, fino a 2.500 iscritti): edizione EN ed edizione IT
- Contenuto: i top segnali insider della settimana (ormai "scaduti" come tempismo operativo), lo storico del dirigente, e il **track record aggiornato** calcolato dal portfolio simulator esistente ("questo segnale i premium l'hanno ricevuto lunedì mattina, il titolo ha fatto +X%")
- Funzione: vetrina e motore di conversione al premium. La differenza free/premium non è "più roba" ma **il tempismo**
- Il gratuito mostra i *top* segnali, non tutti: quando il premium crescerà di prezzo o funzioni, si aggiungerà valore senza mai togliere nulla al tier gratuito

### Tier premium — $5/mese (Telegram + Whop)
- **Canale Telegram privato** con digest giornaliero pre-market (~7:00 ET) contenente i segnali delle ultime 24h: chi ha comprato, score, storico acquisti del dirigente, performance dei suoi acquisti passati
- **Alert immediato** sui segnali forti (stesso trigger che InsiderTracker già usa)
- Billing e controllo accessi gestiti da **Whop** (~3% a transazione, zero costi fissi): pagamento → invito automatico al canale; disdetta → rimozione automatica
- Prezzo simbolico $5/mese per minimizzare l'attrito; assistenza attesa ~zero
- Razionale della scelta piattaforma: gli abbonamenti a pagamento su beehiiv richiedono il piano Scale ($43/mese, in perdita fino a ~9 paganti); Substack è gratis ma senza API ufficiale (automazione fragile). Telegram è il terreno di casa dell'utente e il formato atteso nel mondo trading

## 3. Architettura tecnica

Nuovo modulo `newsletter/` dentro il repo InsiderTracker. **Non modifica nessun file del sistema live.**

### Pipeline settimanale (tier gratuito)
1. **Estrazione** — legge i segnali della settimana dall'output esistente di InsiderTracker
2. **Arricchimento** — per i top segnali: storico acquisti del dirigente e performance passate (dati già disponibili nel company analyzer v2), track record dal portfolio simulator
3. **Generazione** — Claude Code in modalità headless (`claude -p`) trasforma il report strutturato nella newsletter EN, poi genera l'edizione IT (adattamento, non traduzione letterale). Usa l'abbonamento Claude esistente dell'utente → costo zero. Vincolo: gira sul PC dove l'utente è loggato, non sul VPS. Piano B documentato: Claude API con Haiku (`claude-haiku-4-5`, $1/$5 per MTok → centesimi/mese)
4. **Caricamento bozze** — via API ufficiale beehiiv, nelle due pubblicazioni
5. **Notifica** — messaggio Telegram all'utente con i link alle bozze; review di 10-15 minuti e pubblicazione dal telefono (stesso flusso manuale-finale di ReelFactory)

Schedulazione: task settimanale nel weekend (a settimana di filing SEC chiusa), numero pronto domenica, invio lunedì mattina USA.

### Pipeline giornaliera (tier premium)
1. Stesso trigger giornaliero di InsiderTracker (i segnali arrivano per lo più dopo la chiusura USA)
2. Composizione del digest pre-market: formato rigido e formulaico (tabella segnali + testo breve) generato con **template Python puro, nessuna chiamata LLM** — costo zero e output deterministico
3. Pubblicazione sul canale Telegram premium via bot (stack Telegram già padroneggiato)
4. Alert immediati sui segnali forti, inoltrati appena il segnale scatta

**Livello di automazione:** review manuale via Telegram per le prime 2-3 settimane su entrambe le pipeline; poi il digest giornaliero passa in **full-auto** (formato rigido, rischio basso), la review umana resta solo sul settimanale gratuito.

## 4. Crescita (100% organica, budget zero)

**Decisione 17/07/2026 (sera):** X (XybridFX) e IG (ReelFactory) restano dedicati ai progetti forex/GridMartingala/TRFX (Copy Funnel) e NON promuovono la newsletter, almeno per ora.

1. **Rete di raccomandazioni reciproche beehiiv** (gratuita) per l'edizione EN
2. **SEO** — le versioni web dei numeri beehiiv sono pagine indicizzate (query tipo "insider buying this week")
3. **Reddit** (r/stocks, r/ValueInvesting…) — opzionale, solo manuale, solo se l'utente vorrà: non automatizzabile in sicurezza
4. **Boosts a pagamento** — valutazione futura, solo dopo la validazione del segnale

**Gate di lancio:** la newsletter non viene lanciata pubblicamente finché il track record del portfolio simulato non è credibile (indicativamente ≥25-30 trade chiusi con aspettativa positiva netta). Prerequisito tecnico: allineare la simulazione live al backtest aggiungendo lo stop-loss 8% (`SL_PERCENT`) in `portfolio_tracker.update()` — oggi le posizioni chiudono solo a scadenza temporale, mentre gli holding period consigliati dal company analyzer assumono lo SL 8%.

**Aspettative dichiarate:** con solo organico, i primi 1.000 iscritti richiedono realisticamente 6-12 mesi. Il progetto si giudica a 6 mesi, non a 6 settimane. Riferimenti di mercato: conversione mediana free→paid ~0,6%; ad network beehiiv redditizio da ~3.000 iscritti (richiederebbe comunque piano Scale — valutazione futura).

## 5. Gestione errori e qualità

- **Settimana povera di segnali**: la pipeline lo rileva, lo dichiara nella notifica Telegram e propone un numero "slow week" (follow-up sui segnali passati) invece di forzare contenuto debole
- **Track record auto-aggiornante** in ogni numero, calcolato dal portfolio simulator: è il motore di credibilità e non richiede manutenzione
- **Disclaimer "not financial advice"** in ogni numero e in ogni digest, in entrambe le lingue — obbligatorio per un prodotto finanziario
- La review umana pre-invio resta il filtro finale finché attiva; il passaggio a full-auto del digest avviene solo dopo il rodaggio

## 6. Test

Sviluppo TDD (metodologia standard dell'utente):
- Test su estrazione e arricchimento con dati sintetici
- Test del formato output verso l'API beehiiv e verso Telegram
- **Dry-run completo**: la pipeline genera un numero di prova end-to-end senza pubblicare nulla
- Prima uscita reale solo dopo 2-3 numeri di prova generati e approvati dall'utente

## 7. Fuori scope (per ora)

Sito web dedicato, social nuovi, logo elaborato, referral program, sponsor, ad network, Boosts a pagamento: tutto rimandato a dopo la validazione. Eccezione: **nome e descrizione delle pubblicazioni** vanno scelti bene da subito, perché cambiare identità dopo costa.

## 8. Costi ed effort

| Voce | Costo |
|---|---|
| beehiiv Launch (2 pubblicazioni) | $0 |
| Whop | ~3% a transazione, zero fisso |
| Telegram bot + canale | $0 |
| Generazione newsletter (Claude Code headless, abbonamento esistente) | $0 |
| Generazione digest giornaliero (template Python, no LLM) | $0 |
| Piano B: Claude API Haiku | centesimi/mese, solo se serve |
| X API (tier free) | $0 |
| VPS / scheduling | già esistente |

- Setup: alcune sessioni di sviluppo (pipeline + account + numeri di prova)
- Regime iniziale: 10-15 min/giorno di review del digest + review settimanale
- Regime post-rodaggio: solo review settimanale (10-15 min/settimana) + manutenzione occasionale

## 9. Decisioni prese durante il brainstorming

| Decisione | Scelta | Alternativa scartata e perché |
|---|---|---|
| Lingua/mercato | EN + IT dalla stessa pipeline | Solo EN (perde sinergia ReelFactory), solo IT (bacino piccolo per dati SEC) |
| Contenuto | Solo insider | Multi-segnale (identità confusa), insider+macro (poco distintivo) |
| Monetizzazione | Freemium, premium $5/mese | Solo gratis+ads (redditività tardiva), solo premium (nessuno paga uno sconosciuto) |
| Timing segnali | Premium giornaliero pre-market, free settimanale | Tutto settimanale (uccide il valore dei segnali, che sono deperibili) |
| Piattaforma premium | Telegram + Whop | beehiiv Scale ($43/mese fissi), Substack (API non ufficiale fragile) |
| Crescita | Solo organico (raccomandazioni, X, IG, SEO) | Boosts a pagamento (utente non vuole budget) |
| Automazione | Review manuale → full-auto sul giornaliero dopo rodaggio | Full-auto da subito (rischio reputazionale) |
