/**
 * Minimal i18n — no external dep, just a context + localStorage-persisted locale.
 *
 * Usage:
 *   const { t, locale, setLocale } = useI18n();
 *   t("search.tab.live")
 *   t("results.count", { count: 47 })
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "en" | "fr" | "nl" | "de";

export const LOCALES: { code: Locale; label: string }[] = [
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
  { code: "nl", label: "Nederlands" },
  { code: "de", label: "Deutsch" },
];

const STORAGE_KEY = "pw_locale";

// ── Strings dictionary — keep keys flat-dotted, values in 4 languages ──
// Use {placeholder} tokens for interpolation.
const STRINGS: Record<string, Record<Locale, string>> = {
  // Page header
  "page.title":      { en: "Brand & Drug Search", fr: "Recherche de marque et médicament", nl: "Merk- & geneesmiddelzoekfunctie", de: "Marken- & Arzneimittelsuche" },
  "page.subtitle":   {
    en: "Real-time results from news, forums & trends — or let AI synthesise the intelligence for you.",
    fr: "Résultats en temps réel depuis l'actualité, les forums et les tendances — ou laissez l'IA synthétiser pour vous.",
    nl: "Realtime resultaten uit nieuws, forums en trends — of laat AI de informatie voor u synthetiseren.",
    de: "Echtzeit-Ergebnisse aus News, Foren und Trends — oder lassen Sie die KI für Sie zusammenfassen.",
  },

  // Tabs / shortcuts
  "tab.search":         { en: "Search",         fr: "Recherche",       nl: "Zoeken",           de: "Suche" },
  "tab.ai":             { en: "AI Mode",        fr: "Mode IA",         nl: "AI-modus",         de: "KI-Modus" },
  "shortcut.focus":     { en: "K to focus",     fr: "K pour cibler",   nl: "K om te focussen", de: "K zum Fokussieren" },
  "recent":             { en: "Recent",         fr: "Récent",          nl: "Recent",           de: "Zuletzt" },

  // Live search bar
  "live.placeholder":   {
    en: 'e.g. "ibuprofen", "Dafalgan", "doliprane", "aspirin"  ·  ⌘K to focus',
    fr: 'p. ex. « ibuprofène », « Dafalgan », « doliprane », « aspirine »  ·  ⌘K pour cibler',
    nl: 'bijv. "ibuprofen", "Dafalgan", "doliprane", "aspirine"  ·  ⌘K om te focussen',
    de: 'z. B. „Ibuprofen", „Dafalgan", „Doliprane", „Aspirin"  ·  ⌘K zum Fokussieren',
  },
  "live.filters":       { en: "Filters",         fr: "Filtres",          nl: "Filters",           de: "Filter" },
  "live.search":        { en: "Search",          fr: "Rechercher",       nl: "Zoeken",            de: "Suchen" },
  "live.searching":     { en: "Searching…",      fr: "Recherche…",       nl: "Zoeken…",           de: "Suche läuft…" },

  // Filter panel
  "filter.period":      { en: "Time Period",     fr: "Période",          nl: "Periode",           de: "Zeitraum" },
  "filter.sources":     { en: "Sources",         fr: "Sources",          nl: "Bronnen",           de: "Quellen" },
  "period.7d":          { en: "7 days",          fr: "7 jours",          nl: "7 dagen",           de: "7 Tage" },
  "period.30d":         { en: "1 month",         fr: "1 mois",           nl: "1 maand",           de: "1 Monat" },
  "period.180d":        { en: "6 months",        fr: "6 mois",           nl: "6 maanden",         de: "6 Monate" },
  "period.365d":        { en: "1 year",          fr: "1 an",             nl: "1 jaar",            de: "1 Jahr" },
  "period.all":         { en: "All time",        fr: "Toutes périodes",  nl: "Alle tijden",       de: "Gesamter Zeitraum" },

  // Loading / errors
  "live.loading.title": { en: "Searching live sources…", fr: "Interrogation des sources en direct…", nl: "Live bronnen worden doorzocht…", de: "Live-Quellen werden durchsucht…" },
  "live.loading.hint":  { en: "this takes 5–15 seconds",  fr: "cela prend 5 à 15 secondes",          nl: "dit duurt 5–15 seconden",         de: "dauert 5–15 Sekunden" },
  "live.error":         { en: "Search failed — check that the API server is running and sources are reachable.", fr: "Échec de la recherche — vérifiez que l'API et les sources sont accessibles.", nl: "Zoekopdracht mislukt — controleer of de API en bronnen bereikbaar zijn.", de: "Suche fehlgeschlagen — prüfen Sie, ob API und Quellen erreichbar sind." },

  // Result header
  "results.countLabel": { en: "live results for",  fr: "résultats en direct pour", nl: "live resultaten voor", de: "Live-Ergebnisse für" },
  "results.countLabel.one": { en: "live result for", fr: "résultat en direct pour", nl: "live resultaat voor", de: "Live-Ergebnis für" },
  "results.via":        { en: "via",                fr: "via",                      nl: "via",                  de: "über" },
  "risk.flagsShort.one":{ en: "risk flag",          fr: "alerte risque",            nl: "risicomelding",        de: "Risikohinweis" },
  "risk.flagsShort":    { en: "risk flags",         fr: "alertes risque",           nl: "risicomeldingen",      de: "Risikohinweise" },

  // Sentiment filter
  "sentiment.all":      { en: "All",      fr: "Tous",      nl: "Alle",      de: "Alle" },
  "sentiment.positive": { en: "Positive", fr: "Positif",   nl: "Positief",  de: "Positiv" },
  "sentiment.neutral":  { en: "Neutral",  fr: "Neutre",    nl: "Neutraal",  de: "Neutral" },
  "sentiment.negative": { en: "Negative", fr: "Négatif",   nl: "Negatief",  de: "Negativ" },

  // Bridge button
  "live.askAi":         { en: "Ask AI about these results", fr: "Synthèse IA de ces résultats", nl: "Vraag AI over deze resultaten", de: "KI zu diesen Ergebnissen fragen" },
  "live.askAi.title":   { en: "Synthesise these results with the AI Mode (no second fetch)", fr: "Synthétiser ces résultats avec le mode IA (sans seconde requête)", nl: "Synthetiseer deze resultaten met de AI-modus (geen tweede ophaalactie)", de: "Diese Ergebnisse mit dem KI-Modus zusammenfassen (ohne zweiten Abruf)" },

  // Insight panel titles
  "insight.sentiment":  { en: "Sentiment",        fr: "Sentiment",        nl: "Sentiment",        de: "Stimmung" },
  "insight.timeline":   { en: "Mentions over time", fr: "Mentions dans le temps", nl: "Vermeldingen over tijd", de: "Erwähnungen im Zeitverlauf" },
  "insight.sources":    { en: "Top sources",      fr: "Sources principales", nl: "Top bronnen",   de: "Top-Quellen" },
  "insight.topics":     { en: "Top topics",       fr: "Sujets principaux", nl: "Top onderwerpen", de: "Top-Themen" },
  "insight.empty":      { en: "No data",          fr: "Aucune donnée",    nl: "Geen gegevens",    de: "Keine Daten" },
  "insight.timeline.empty": { en: "Need dated mentions across multiple days", fr: "Mentions datées sur plusieurs jours requises", nl: "Gedateerde vermeldingen over meerdere dagen vereist", de: "Datierte Erwähnungen über mehrere Tage erforderlich" },
  "insight.positive":   { en: "positive",         fr: "positif",          nl: "positief",         de: "positiv" },

  // Risk callout
  "risk.headline":      { en: "{count} mentions flagged for adverse-event review", fr: "{count} mentions signalées pour examen d'événement indésirable", nl: "{count} vermeldingen gemarkeerd voor bijwerkingsbeoordeling", de: "{count} Erwähnungen für Nebenwirkungsprüfung markiert" },
  "risk.headline.one":  { en: "1 mention flagged for adverse-event review",        fr: "1 mention signalée pour examen d'événement indésirable",        nl: "1 vermelding gemarkeerd voor bijwerkingsbeoordeling",          de: "1 Erwähnung für Nebenwirkungsprüfung markiert" },
  "risk.subline":       { en: "The pharmacovigilance officer should triage these candidates — human review is mandatory.", fr: "Le responsable de pharmacovigilance doit trier ces candidats — la revue humaine est obligatoire.", nl: "De farmacovigilantiefunctionaris moet deze kandidaten triëren — menselijke beoordeling is verplicht.", de: "Der Pharmakovigilanzbeauftragte muss diese Kandidaten triagieren — menschliche Prüfung ist Pflicht." },
  "risk.cta":           { en: "Review queue →",   fr: "File de revue →",  nl: "Beoordelingswachtrij →", de: "Prüfungs­warteschlange →" },

  // No results / empty state
  "noResults.headline": { en: "No results found for", fr: "Aucun résultat pour", nl: "Geen resultaten voor", de: "Keine Ergebnisse für" },
  "noResults.acrossSources": { en: "across the selected sources.", fr: "dans les sources sélectionnées.", nl: "in de geselecteerde bronnen.", de: "in den ausgewählten Quellen." },
  "noResults.tryVariants": { en: "Try one of the EU brand variants:", fr: "Essayez l'une des marques équivalentes en Europe :", nl: "Probeer een van de Europese merkvarianten:", de: "Probieren Sie eine der EU-Markenvarianten:" },
  "noResults.tryName":  { en: "Try a brand or molecule name, e.g.", fr: "Essayez un nom de marque ou de molécule, p. ex.", nl: "Probeer een merk- of molecuulnaam, bijv.", de: "Probieren Sie einen Marken- oder Molekülnamen, z. B." },
  "noResults.widenFilters": { en: "You can also widen Filters → time period or sources.", fr: "Vous pouvez aussi élargir les Filtres → période ou sources.", nl: "U kunt ook de Filters verbreden → periode of bronnen.", de: "Sie können auch die Filter erweitern → Zeitraum oder Quellen." },

  // First-load empty (live)
  "live.empty.title":   { en: "Search live across news, forums & trends", fr: "Rechercher en direct dans l'actualité, les forums et les tendances", nl: "Zoek live in nieuws, forums en trends", de: "Live in News, Foren und Trends suchen" },
  "live.empty.subtitle": { en: "Type any brand or drug name and press Search. Cross-lingual expansion automatically covers EU brand variants.", fr: "Tapez un nom de marque ou de médicament et lancez la recherche. L'expansion multilingue couvre automatiquement les marques européennes.", nl: "Typ een merk- of medicijnnaam en klik op Zoeken. Cross-linguale expansie dekt automatisch EU-merkvarianten.", de: "Geben Sie einen Marken- oder Arzneimittelnamen ein und klicken Sie auf Suchen. Die mehrsprachige Erweiterung deckt EU-Markenvarianten automatisch ab." },

  // Expansion pills
  "expansion.alsoSearched": { en: "Also searched", fr: "Aussi recherché", nl: "Ook gezocht",      de: "Auch gesucht" },
  "expansion.drillInto":    { en: "Drill into",    fr: "Affiner sur",     nl: "Inzoomen op",      de: "Detail zu" },

  // AI Mode
  "ai.beta":            { en: "Beta",             fr: "Bêta",             nl: "Bèta",             de: "Beta" },
  "ai.subtitle":        { en: "AI-synthesised pharmaceutical intelligence — powered by", fr: "Intelligence pharmaceutique synthétisée par IA — propulsée par", nl: "Door AI gesynthetiseerde farmaceutische intelligentie — aangedreven door", de: "KI-synthetisierte pharmazeutische Intelligenz — angetrieben von" },
  "ai.grounded":        { en: "grounded with live news context.", fr: "ancrée dans le contexte de l'actualité en direct.", nl: "gefundeerd op live nieuwscontext.", de: "verankert im Live-Nachrichtenkontext." },
  "ai.placeholder":     { en: 'Ask about any drug or brand — e.g. "ibuprofen side effects Belgium"  ·  ⌘K', fr: 'Posez une question sur un médicament ou une marque — p. ex. « effets secondaires ibuprofène Belgique »  ·  ⌘K', nl: 'Stel een vraag over een geneesmiddel of merk — bijv. "bijwerkingen ibuprofen België"  ·  ⌘K', de: 'Stellen Sie eine Frage zu einem Arzneimittel oder einer Marke — z. B. „Ibuprofen Nebenwirkungen Belgien"  ·  ⌘K' },
  "ai.askButton":       { en: "Ask AI",           fr: "Interroger l'IA",  nl: "Vraag AI",         de: "KI fragen" },
  "ai.analysing":       { en: "Analysing…",       fr: "Analyse en cours…", nl: "Analyseren…",     de: "Analysiere…" },
  "ai.analysingFor":    { en: "Analysing \"{q}\"…", fr: "Analyse de « {q} »…", nl: "Analyseren van \"{q}\"…", de: "Analysiere \"{q}\"…" },
  "ai.bridgeFromN":     { en: "Synthesising from {n} live results · GPT-5.4-mini", fr: "Synthèse à partir de {n} résultats en direct · GPT-5.4-mini", nl: "Synthetiseren van {n} live resultaten · GPT-5.4-mini", de: "Synthese aus {n} Live-Ergebnissen · GPT-5.4-mini" },
  "ai.fetchHint":       { en: "Fetching live news context · Synthesising with GPT-5.4-mini · Usually 3–8 seconds", fr: "Récupération du contexte d'actualité · Synthèse avec GPT-5.4-mini · Généralement 3 à 8 secondes", nl: "Live nieuwscontext ophalen · Synthese met GPT-5.4-mini · Meestal 3–8 seconden", de: "Live-Nachrichtenkontext wird geholt · Synthese mit GPT-5.4-mini · Üblicherweise 3–8 Sekunden" },
  "ai.error":           { en: "AI search failed. Check that OPENAI_API_KEY is configured and the API server is running.", fr: "La recherche IA a échoué. Vérifiez que OPENAI_API_KEY est configurée et que l'API tourne.", nl: "AI-zoekopdracht mislukt. Controleer of OPENAI_API_KEY is ingesteld en de API draait.", de: "KI-Suche fehlgeschlagen. Prüfen Sie, ob OPENAI_API_KEY konfiguriert ist und der API-Server läuft." },
  "ai.overview":        { en: "AI Overview",      fr: "Aperçu IA",        nl: "AI-overzicht",     de: "KI-Übersicht" },
  "ai.sentimentSuffix": { en: "sentiment",        fr: "sentiment",        nl: "sentiment",        de: "Stimmung" },
  "ai.sourcesHeader":   { en: "Numbered sources", fr: "Sources numérotées", nl: "Genummerde bronnen", de: "Nummerierte Quellen" },
  "ai.sourcesHint":     { en: "click any [n] in the answer to jump here", fr: "cliquez sur un [n] dans la réponse pour y revenir", nl: "klik op [n] in het antwoord om hierheen te springen", de: "klicken Sie auf [n] in der Antwort, um hierher zu springen" },
  "ai.viewSource":      { en: "View source",      fr: "Voir la source",   nl: "Bron bekijken",    de: "Quelle ansehen" },
  "ai.empty.title":     { en: "AI-powered pharmaceutical intelligence", fr: "Intelligence pharmaceutique propulsée par IA", nl: "AI-aangedreven farmaceutische intelligentie", de: "KI-gestützte pharmazeutische Intelligenz" },
  "ai.empty.subtitle":  { en: "Ask any question about a drug or brand. The AI fetches live news context, then synthesises a concise answer with sentiment analysis and key points — every claim is cited.", fr: "Posez une question sur un médicament ou une marque. L'IA récupère le contexte d'actualité en direct, puis synthétise une réponse concise avec analyse de sentiment et points clés — chaque affirmation est citée.", nl: "Stel een vraag over een geneesmiddel of merk. De AI haalt live nieuwscontext op en synthetiseert een beknopt antwoord met sentimentanalyse en kernpunten — elke claim wordt geciteerd.", de: "Stellen Sie eine Frage zu einem Arzneimittel oder einer Marke. Die KI holt Live-Nachrichtenkontext und synthetisiert eine prägnante Antwort mit Stimmungsanalyse und Kernpunkten — jede Aussage ist zitiert." },

  // Sidebar (Layout) — partial: just Log out + chooser label
  "nav.logout":         { en: "Log out",          fr: "Déconnexion",      nl: "Afmelden",         de: "Abmelden" },
  "nav.language":       { en: "Language",         fr: "Langue",           nl: "Taal",             de: "Sprache" },
};

interface Ctx {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<Ctx | null>(null);

function readInitial(): Locale {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "en" || v === "fr" || v === "nl" || v === "de") return v;
  } catch {}
  return "en";
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readInitial);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try { localStorage.setItem(STORAGE_KEY, l); } catch {}
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const t = useCallback((key: string, vars?: Record<string, string | number>) => {
    const row = STRINGS[key];
    if (!row) return key;
    let s = row[locale] ?? row.en ?? key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
      }
    }
    return s;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider/>");
  return ctx;
}
