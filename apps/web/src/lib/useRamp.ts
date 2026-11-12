"use client";

import { useEffect, useState } from "react";
import { RAMPS, type RampName } from "./calendar";

const KEY = "astraforce.ramp";

/** Seçili renk rampası (tarayıcıda hatırlanır). */
export function useRamp() {
  const [ramp, setRamp] = useState<RampName>("fire");
  useEffect(() => {
    try {
      const v = localStorage.getItem(KEY);
      if (v === "fire" || v === "cividis") setRamp(v);
    } catch {}
  }, []);
  const update = (r: RampName) => {
    setRamp(r);
    try {
      localStorage.setItem(KEY, r);
    } catch {}
  };
  return { ramp, colors: RAMPS[ramp], setRamp: update };
}
