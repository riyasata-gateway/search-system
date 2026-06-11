/**
 * Structured AI-Search PDF — real text (crisp, selectable), native page breaks,
 * clickable source links (jsPDF textWithLink), AND a branded visual layout:
 * accent header band, coloured section rules, a sentiment pill, numbered insights,
 * and real PR24 bars — not a flat dump and not a sliced screenshot.
 * Covers the complete AI Mode result: AI analysis, Deep Insights, and PR24.
 */
type Src = { title?: string | null; url?: string | null; text?: string | null; source_url?: string | null };
type RGB = [number, number, number];

const ACCENT: RGB = [120, 66, 238];   // accent-600
const ACCENT_LITE: RGB = [237, 233, 255]; // accent-100
const BRAND: RGB = [42, 79, 245];      // brand-600 — links
const INK: RGB = [40, 50, 77];         // ink-700 — section titles
const TRACK: RGB = [232, 232, 240];

const SENTIMENT_RGB: Record<string, RGB> = {
  Positive: [22, 163, 74], Negative: [220, 38, 38],
  Mixed: [217, 119, 6], Neutral: [100, 116, 139],
};

export async function exportAiModePdf(opts: {
  query: string; data: any | null; insights: any | null; pr24: any | null;
}) {
  const jspdf: any = await import("jspdf");
  const JsPDF = jspdf.jsPDF || jspdf.default;
  const pdf = new JsPDF("p", "mm", "a4");
  const W = pdf.internal.pageSize.getWidth();
  const H = pdf.internal.pageSize.getHeight();
  const M = 14;
  const maxW = W - 2 * M;
  let y = M;

  const ensure = (h: number) => { if (y + h > H - 12) { pdf.addPage(); y = M; } };
  const setText = (c: number | RGB) => Array.isArray(c) ? pdf.setTextColor(c[0], c[1], c[2]) : pdf.setTextColor(c);
  const setFill = (c: RGB) => pdf.setFillColor(c[0], c[1], c[2]);

  const text = (s: string, o: { size?: number; color?: number | RGB; bold?: boolean; gap?: number; x?: number } = {}) => {
    const { size = 10, color = 60, bold = false, gap = 5, x = M } = o;
    pdf.setFont("helvetica", bold ? "bold" : "normal");
    pdf.setFontSize(size); setText(color);
    pdf.splitTextToSize(s || "", maxW - (x - M)).forEach((ln: string) => {
      ensure(gap); pdf.text(ln, x, y); y += gap;
    });
  };
  const heading = (s: string) => {
    y += 4; ensure(11);
    pdf.setFont("helvetica", "bold"); pdf.setFontSize(13.5); setText(INK);
    pdf.text(s, M, y); y += 2.5;
    setFill(ACCENT); pdf.rect(M, y, 26, 1.1, "F");           // accent rule
    pdf.setDrawColor(225); pdf.line(M + 28, y + 0.5, W - M, y + 0.5);
    y += 5;
  };
  const sub = (s: string) => { y += 1.5; ensure(7); text(s, { size: 10.5, bold: true, color: INK, gap: 5.5 }); };
  const linkLine = (label: string, url: string, indent = 0) => {
    pdf.setFont("helvetica", "normal"); pdf.setFontSize(9); setText(BRAND);
    const lines = pdf.splitTextToSize("• " + (label || url), maxW - indent);
    ensure(4.6); pdf.textWithLink(lines[0], M + indent, y, { url }); y += 4.6;
    for (let i = 1; i < lines.length; i++) { ensure(4.6); pdf.text(lines[i], M + indent + 3, y); y += 4.6; }
  };
  const sources = (title: string, list: Src[]) => {
    const valid = (list || []).filter((s) => s && (s.url || s.source_url || s.title || s.text));
    if (!valid.length) return;
    sub(title);
    valid.forEach((s) => {
      const url = s.url || s.source_url || "";
      const label = s.title || s.text || url;
      if (url && /^https?:/i.test(url)) linkLine(label!, url);
      else text("• " + (label || ""), { size: 9, color: 90, gap: 4.6 });
    });
  };
  const pill = (label: string, rgb: RGB) => {
    pdf.setFont("helvetica", "bold"); pdf.setFontSize(8.5);
    const w = pdf.getTextWidth(label) + 6;
    ensure(8); setFill(rgb); pdf.roundedRect(M, y - 3.6, w, 5.6, 2.8, 2.8, "F");
    pdf.setTextColor(255, 255, 255); pdf.text(label, M + 3, y); y += 6;
  };
  // PR24 horizontal index bar (0–100) with the value at the right.
  const bar = (label: string, value: number | null, note?: string) => {
    text(label, { size: 9.5, bold: true, color: INK, gap: 4.4 });
    ensure(5);
    const numW = 12;
    const trackW = maxW - numW;
    const trackY = y;
    setFill(TRACK); pdf.roundedRect(M, trackY, trackW, 3, 1.5, 1.5, "F");
    const v = Math.max(0, Math.min(100, value ?? 0));
    const fw = (v / 100) * trackW;
    if (fw > 0) { setFill(ACCENT); pdf.roundedRect(M, trackY, Math.max(fw, 2), 3, 1.5, 1.5, "F"); }
    pdf.setFont("helvetica", "bold"); pdf.setFontSize(8.5); setText(ACCENT);
    pdf.text(value == null ? "—" : `${Math.round(v)}`, W - M, trackY + 2.7, { align: "right" });
    y += 5.5;
    if (note) text(note, { size: 8.5, color: 110, gap: 4.2 });
  };

  // ── Header band (page 1) ────────────────────────────────────────────────
  setFill(ACCENT); pdf.rect(0, 0, W, 24, "F");
  pdf.setFont("helvetica", "bold"); pdf.setFontSize(18); pdf.setTextColor(255, 255, 255);
  pdf.text("AI Search Report", M, 13);
  pdf.setFont("helvetica", "normal"); pdf.setFontSize(10.5); pdf.setTextColor(231, 226, 255);
  pdf.text(`Query: ${opts.query || "—"}`, M, 19.5);
  y = 32;

  // ── AI analysis ────────────────────────────────────────────────────────
  if (opts.data) {
    heading("AI Analysis");
    if (opts.data.sentiment_summary) pill(`Sentiment: ${opts.data.sentiment_summary}`, SENTIMENT_RGB[opts.data.sentiment_summary] || SENTIMENT_RGB.Neutral);
    if (opts.data.answer) text(opts.data.answer, { size: 10, color: 55 });
    if (opts.data.key_points?.length) {
      sub("Key points");
      opts.data.key_points.forEach((k: string) => text("• " + k, { size: 10, color: 55 }));
    }
    sources("Sources", opts.data.sources || []);
  }

  // ── Deep Insights ──────────────────────────────────────────────────────
  if (opts.insights) {
    heading("Deep Insights");
    if (opts.insights.recommendation) {
      ensure(8); setFill(ACCENT_LITE);
      const lines = pdf.splitTextToSize("Recommendation: " + opts.insights.recommendation, maxW - 6);
      const boxH = lines.length * 4.8 + 4;
      ensure(boxH); setFill(ACCENT_LITE); pdf.roundedRect(M, y - 3, maxW, boxH, 1.5, 1.5, "F");
      pdf.setFont("helvetica", "bold"); pdf.setFontSize(9.5); setText(INK);
      lines.forEach((ln: string) => { pdf.text(ln, M + 3, y + 1); y += 4.8; });
      y += 3;
    }
    if (opts.insights.headline) text(opts.insights.headline, { size: 10, color: 55 });
    (opts.insights.insights || []).forEach((it: any, i: number) => {
      ensure(6);
      setFill(ACCENT_LITE); pdf.roundedRect(M, y - 3.6, 5, 5, 1, 1, "F");
      pdf.setFont("helvetica", "bold"); pdf.setFontSize(8); setText(ACCENT);
      pdf.text(String(i + 1), M + 2.5, y, { align: "center" });
      const tag = it.category ? `  (${it.category})` : "";
      text((it.topic || "") + tag, { size: 10, bold: true, color: INK, x: M + 8, gap: 4.8 });
      if (it.detail) text(it.detail, { size: 9, color: 75, x: M + 8, gap: 4.6 });
    });
    const findings = opts.insights.findings || [];
    if (findings.length) {
      sub(`Research trail — ${findings.length} findings${opts.insights.angles?.length ? ` across ${opts.insights.angles.length} angles` : ""}`);
      findings.forEach((f: any) => {
        const fact = f.fact || "";
        const date = f.date ? ` · ${f.date}` : "";
        text("– " + fact + date, { size: 9, color: 70, gap: 4.6 });
        if (f.source_url && /^https?:/i.test(f.source_url)) linkLine(f.source_title || f.source_url, f.source_url, 3);
        else if (f.source_title) text(`  · ${f.source_title}`, { size: 8.5, color: 110, gap: 4.4, x: M + 3 });
      });
    }
  }

  // ── PR24 ───────────────────────────────────────────────────────────────
  if (opts.pr24) {
    heading("PR24 — Belgium & France product-search insights");
    if (opts.pr24.summary) text(opts.pr24.summary, { size: 10, color: 55 });
    text("Index = 0–100 relative search interest within each category (higher = searched more in Belgium/France).", { size: 8, color: 130 });
    const pillar = (title: string, p: any) => {
      if (!p) return;
      sub(title);
      (p.items || []).forEach((it: any) => bar(it.label, it.share, it.note));
      sources("Data sources", p.sources || []);
    };
    pillar("Gender", opts.pr24.gender);
    pillar("Age group", opts.pr24.age_group);
    pillar("Region (Belgium & France)", opts.pr24.region);
  }

  // ── Footer (page numbers) on every page ──────────────────────────────────
  const pages = pdf.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    pdf.setPage(i);
    pdf.setFont("helvetica", "normal"); pdf.setFontSize(7.5); pdf.setTextColor(155);
    pdf.text("PharmaWatch · AI Search", M, H - 6);
    pdf.text(`${i} / ${pages}`, W - M, H - 6, { align: "right" });
  }

  pdf.save(`AI Search — ${opts.query || "results"}.pdf`);
}
