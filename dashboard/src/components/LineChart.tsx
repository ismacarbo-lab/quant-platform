import { useEffect, useRef } from "react";
import {
  ColorType,
  LineSeries,
  createChart,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts";

export type LineSeriesInput = {
  name: string;
  color: string;
  data: { date: string; value: number }[];
  dashed?: boolean;
};

export function LineChart({
  series,
  height = 340,
  logScale = false,
  percentAxis = false,
}: {
  series: LineSeriesInput[];
  height?: number;
  logScale?: boolean;
  percentAxis?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

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
      rightPriceScale: {
        borderColor: "#233055",
        mode: logScale ? 1 : 0,
      },
      timeScale: { borderColor: "#233055" },
      crosshair: { mode: 0 },
      localization: percentAxis
        ? { priceFormatter: (price: number) => `${(price * 100).toFixed(1)}%` }
        : undefined,
    });
    chartRef.current = chart;
    for (const item of series) {
      const line = chart.addSeries(LineSeries, {
        color: item.color,
        lineWidth: 2,
        lineStyle: item.dashed ? 2 : 0,
        priceLineVisible: false,
        lastValueVisible: true,
        title: item.name,
      });
      const data: LineData<Time>[] = item.data
        .filter((point) => Number.isFinite(point.value))
        .map((point) => ({ time: point.date as Time, value: point.value }));
      line.setData(data);
    }
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => {
      if (container.current) chart.applyOptions({ width: container.current.clientWidth });
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [series, height, logScale, percentAxis]);

  return (
    <div>
      <div ref={container} style={{ width: "100%", height }} />
      <div className="legend">
        {series.map((item) => (
          <span key={item.name}>
            <span className="dot" style={{ background: item.color }} />
            {item.name}
          </span>
        ))}
      </div>
    </div>
  );
}
