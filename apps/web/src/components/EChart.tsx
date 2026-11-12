"use client";

import type { ECharts, EChartsOption } from "echarts";
import { useEffect, useMemo, useRef } from "react";

type ClickParams = { data?: unknown; value?: unknown; dataIndex?: number; seriesIndex?: number };

/** ECharts'ı yalnızca tarayıcıda yükleyen, boyut değişimine uyan küçük sarmalayıcı. */
export function EChart({
  option: baseOption,
  className,
  onClick,
  pngName,
  pngTitle = "PNG",
  style,
}: {
  option: EChartsOption;
  className?: string;
  onClick?: (p: ClickParams) => void;
  /** Verilirse sağ üstte "PNG olarak kaydet" düğmesi çıkar (dosya adı, uzantısız). */
  pngName?: string;
  pngTitle?: string;
  style?: React.CSSProperties;
}) {
  // useMemo: setOption yalnızca seçenek gerçekten değişince çağrılsın
  const option = useMemo<EChartsOption>(
    () =>
      pngName
    ? {
        ...baseOption,
        toolbox: {
          right: 0,
          top: 0,
          iconStyle: { borderColor: "#9ca3af" },
          feature: {
            saveAsImage: {
              name: pngName,
              title: pngTitle,
              type: "png",
              pixelRatio: 2,
              backgroundColor: "#030712",
            },
          },
        },
      }
    : baseOption,
    [baseOption, pngName, pngTitle],
  );
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const latestOption = useRef(option);
  const clickRef = useRef(onClick);
  latestOption.current = option;
  clickRef.current = onClick;

  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | undefined;
    import("echarts").then((echarts) => {
      if (disposed || !el.current) return;
      const c = echarts.init(el.current, "dark", { renderer: "canvas" });
      c.setOption(latestOption.current, true);
      c.on("click", (p) => clickRef.current?.(p as ClickParams));
      chart.current = c;
      ro = new ResizeObserver(() => c.resize());
      ro.observe(el.current);
    });
    return () => {
      disposed = true;
      ro?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return <div ref={el} className={className} style={style} />;
}
