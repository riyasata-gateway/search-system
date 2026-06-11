import { useState } from "react";
import { FileDown, Loader2 } from "lucide-react";

/**
 * Export a page region to a clean WHITE-background PDF, regardless of the app's
 * current theme. We don't screenshot the dark canvas — instead html2canvas's
 * `onclone` forces the *cloned* DOM into the existing light theme (white cards,
 * dark text), so the live page never flickers and the PDF is always a normal
 * white document. Heavy libs are dynamically imported (kept out of the bundle).
 */
export default function ExportPdfButton({
  targetId, filename, label = "Export PDF",
}: { targetId: string; filename: string; label?: string }) {
  const [busy, setBusy] = useState(false);

  const run = async () => {
    const el = document.getElementById(targetId);
    if (!el) return;
    setBusy(true);
    try {
      const [{ default: html2canvas }, jspdf] = await Promise.all([
        import("html2canvas"), import("jspdf"),
      ]);
      const jsPDF = (jspdf as any).jsPDF || (jspdf as any).default;

      const canvas = await html2canvas(el, {
        scale: 2,
        backgroundColor: "#ffffff",
        useCORS: true,
        logging: false,
        windowWidth: el.scrollWidth,
        onclone: (doc: Document) => {
          // Force the clone into light theme so the PDF is white, whatever the
          // live theme is.
          doc.documentElement.setAttribute("data-theme", "light");
          doc.querySelectorAll(".surface-app").forEach((n) => {
            n.classList.remove("surface-app");
            n.classList.add("surface-light");
          });
          const t = doc.getElementById(targetId) as HTMLElement | null;
          if (t) t.style.background = "#ffffff";
          // Hide controls that shouldn't appear in the document.
          doc.querySelectorAll("[data-export-hide]").forEach((n) => {
            (n as HTMLElement).style.display = "none";
          });
        },
      });

      const pdf = new jsPDF("p", "mm", "a4");
      const pageW = pdf.internal.pageSize.getWidth();
      const pageH = pdf.internal.pageSize.getHeight();
      const margin = 8;
      const imgW = pageW - margin * 2;
      const imgH = (canvas.height * imgW) / canvas.width;
      const img = canvas.toDataURL("image/jpeg", 0.92);
      const printable = pageH - margin * 2;

      let heightLeft = imgH;
      let position = margin;
      pdf.addImage(img, "JPEG", margin, position, imgW, imgH);
      heightLeft -= printable;
      while (heightLeft > 0) {
        position = margin - (imgH - heightLeft);   // shift the image up one page
        pdf.addPage();
        pdf.addImage(img, "JPEG", margin, position, imgW, imgH);
        heightLeft -= printable;
      }
      pdf.save(filename);
    } catch (e) {
      console.error("PDF export failed", e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      data-export-hide
      onClick={run}
      disabled={busy}
      title="Export this analysis as a PDF"
      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 bg-white text-gray-700 text-sm font-medium hover:bg-gray-50 disabled:opacity-60 shadow-soft"
    >
      {busy ? <Loader2 size={14} className="animate-spin" /> : <FileDown size={14} />}
      {busy ? "Exporting…" : label}
    </button>
  );
}
