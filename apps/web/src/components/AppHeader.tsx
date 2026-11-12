"use client";

import type { ReactNode } from "react";
import type { Locale, MessageKey } from "@/lib/i18n";
import { LocaleSelect } from "./LocaleSelect";

const NAV = [
  { href: "/", key: "nav.calendar" },
  { href: "/map", key: "nav.map" },
  { href: "/validation", key: "nav.validation" },
] as const;

/** Tüm sayfalarda ortak üst bar: başlık, gezinme, sayfaya özgü kontroller, dil. */
export function AppHeader({
  active,
  t,
  locale,
  setLocale,
  children,
}: {
  active: (typeof NAV)[number]["href"];
  t: (k: MessageKey) => string;
  locale: Locale;
  setLocale: (l: Locale) => void;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/10 px-4 py-3">
      <div>
        <h1 className="text-lg font-semibold text-fire-200">AstraForce</h1>
        <p className="text-xs text-gray-400">{t("appTagline")}</p>
      </div>
      <nav className="flex gap-1 text-sm">
        {NAV.map((n) => (
          <a
            key={n.href}
            href={n.href}
            // Bölge seçimi sayfalar arasında taşınsın (adres çubuğundaki güncel ?region=...)
            onClick={(e) => {
              e.preventDefault();
              const region = new URLSearchParams(window.location.search).get("region");
              window.location.href = region ? `${n.href}?region=${region}` : n.href;
            }}
            aria-current={active === n.href ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 ${
              active === n.href ? "bg-white/15 text-white" : "text-gray-400 hover:bg-white/5"
            }`}
          >
            {t(n.key)}
          </a>
        ))}
      </nav>
      <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {children}
        <LocaleSelect locale={locale} setLocale={setLocale} label={t("language")} />
      </div>
    </header>
  );
}
