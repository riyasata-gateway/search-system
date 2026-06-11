/**
 * Shared brand selection across pages (Brand Pulse ↔ Brand Potential ↔ …).
 *
 * The brand a user picks on one page should still be selected when they navigate
 * to another — the dropdown there still overrides. Backed by localStorage so the
 * choice also survives a reload; each page reads it on mount and writes on select.
 */
import { useCallback, useState } from "react";
import type { PickerBrand } from "../components/BrandPicker";

const KEY = "pw.selectedBrand";

function load(): PickerBrand | null {
  try {
    const s = localStorage.getItem(KEY);
    return s ? (JSON.parse(s) as PickerBrand) : null;
  } catch {
    return null;
  }
}

/** [brand, setBrand] — like useState, but persisted and shared across pages. */
export function useSelectedBrand(): [PickerBrand | null, (b: PickerBrand | null) => void] {
  const [brand, setBrand] = useState<PickerBrand | null>(load);
  const set = useCallback((b: PickerBrand | null) => {
    setBrand(b);
    try {
      if (b) localStorage.setItem(KEY, JSON.stringify(b));
      else localStorage.removeItem(KEY);
    } catch {
      /* ignore quota / privacy-mode errors */
    }
  }, []);
  return [brand, set];
}