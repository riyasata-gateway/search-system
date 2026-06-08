import { Info } from "lucide-react";

/**
 * A tiny "what is this?" affordance: an info icon that reveals a one-line
 * glossary definition on hover or keyboard focus. Used next to every KPI so a
 * first-time user never has to guess what a number means.
 */
export default function InfoTip({ text, label }: { text: string; label?: string }) {
  if (!text) return null;
  return (
    <span className="relative inline-flex items-center group align-middle">
      <button
        type="button"
        aria-label={label ? `What is ${label}?` : "More information"}
        className="text-gray-300 hover:text-gray-500 focus:outline-none focus:text-gray-600"
      >
        <Info size={13} />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute z-40 left-1/2 -translate-x-1/2 bottom-full mb-1.5 w-56
                   rounded-lg bg-gray-900 text-white text-[11px] leading-snug px-2.5 py-2 shadow-xl
                   opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-150"
      >
        {label && <span className="block font-semibold mb-0.5">{label}</span>}
        {text}
        <span className="absolute left-1/2 -translate-x-1/2 top-full -mt-px border-4 border-transparent border-t-gray-900" />
      </span>
    </span>
  );
}
