import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function drawdownSeries(points: { date: string; equity: number }[]): { date: string; drawdown: number }[] {
  let peak = -Infinity;
  return points.map((point) => {
    peak = Math.max(peak, point.equity);
    return { date: point.date, drawdown: peak > 0 ? point.equity / peak - 1 : 0 };
  });
}

export function DrawdownChart({ points, height = 220 }: { points: { date: string; equity: number }[]; height?: number }) {
  const data = drawdownSeries(points);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="rgba(35,48,85,0.6)" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#8da0c9", fontSize: 11 }} minTickGap={60} />
        <YAxis
          tick={{ fill: "#8da0c9", fontSize: 11 }}
          tickFormatter={(value: number) => `${(value * 100).toFixed(0)}%`}
          width={48}
        />
        <Tooltip
          contentStyle={{ background: "#182340", border: "1px solid #233055", borderRadius: 8 }}
          formatter={(value) => [`${((value as number) * 100).toFixed(2)}%`, "drawdown"]}
        />
        <Area type="monotone" dataKey="drawdown" stroke="#ff5d6c" fill="rgba(255,93,108,0.25)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
