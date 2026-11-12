"use client";

import { useCallback, useEffect, useState } from "react";
import { isLocale, type Locale, type MessageKey, translate } from "./i18n";

const DEFAULT_LOCALE: Locale = isLocale(process.env.NEXT_PUBLIC_DEFAULT_LOCALE)
  ? process.env.NEXT_PUBLIC_DEFAULT_LOCALE
  : "en";
const STORAGE_KEY = "astraforce.locale";

/** Seçili dil (sayfalar arası localStorage ile korunur) ve çeviri fonksiyonu. */
export function useLocale() {
  const [locale, setLocale] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (isLocale(saved)) setLocale(saved);
    } catch {}
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {}
  }, [locale]);

  // Kararlı referans: grafik seçenekleri (useMemo) yalnızca dil değişince yeniden kurulsun.
  const t = useCallback((key: MessageKey) => translate(locale, key), [locale]);
  return { locale, setLocale, t };
}
