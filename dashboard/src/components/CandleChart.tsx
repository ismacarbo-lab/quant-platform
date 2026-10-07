import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  type Time,
} from "lightweight-charts";
import type { Bar } from "../api";

export function CandleChart({ bars, height = 420 }: { bars: Bar[]; height?: number }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8da0c9",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(35,48,85,0.6)" },
        horzLines: { color: "rgba(35,48,85,0.6)" },
      },
      rightPriceScale: { borderColor: "#233055" },
      timeScale: { borderColor: "#233055" },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#52d273",
      downColor: "#ff5d6c",
      wickUpColor: "#52d273",
      wickDownColor: "#ff5d6c",
      borderVisible: false,
    });
    candles.setData(
      bars.map((bar) => ({
        time: bar.date as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    const adjusted = chart.addSeries(LineSeries, {
      color: "#4cc9f0",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "cierre ajustado (total return)",
    });
    adjusted.setData(
      bars
        .filter((bar) => bar.adjusted_close !== null)
        .map((bar) => ({ time: bar.date as Time, value: bar.adjusted_close as number })),
    );
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "rgba(141,160,201,0.35)",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      bars
        .filter((bar) => bar.volume !== null)
        .map((bar) => ({
          time: bar.date as Time,
          value: bar.volume as number,
          color: bar.close >= bar.open ? "rgba(82,210,115,0.35)" : "rgba(255,93,108,0.35)",
        })),
    );
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => {
      if (container.current) chart.applyOptions({ width: container.current.clientWidth });
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [bars, height]);
  return <div ref={container} style={{ width: "100%", height }} />;
}
