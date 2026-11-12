"use client";

import { isLocale, LOCALES, type Locale } from "@/lib/i18n";

export function LocaleSelect({
  locale,
  setLocale,
  label,
}: {
  locale: Locale;
  setLocale: (l: Locale) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-gray-400">{label}</span>
      <select
        value={locale}
        onChange={(e) => isLocale(e.target.value) && setLocale(e.target.value)}
        className="rounded bg-white/10 px-2 py-1 uppercase"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l} className="bg-gray-900">
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}
