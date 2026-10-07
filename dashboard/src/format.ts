export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function money(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("es-ES", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function signClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return value > 0 ? "pos" : value < 0 ? "neg" : "";
}

export function shortDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "—";
}

export const STRATEGY_LABELS: Record<string, string> = {
  buy_and_hold: "Buy & hold SPY",
  sixty_forty: "60/40 SPY/IEF",
  trend_following: "Tendencia (SMA)",
  dual_momentum: "Dual momentum",
  relative_momentum_top_n: "Momentum top-N",
  inverse_volatility: "Inversa volatilidad",
};

export function strategyLabel(name: string): string {
  return STRATEGY_LABELS[name] ?? name;
}

export const PALETTE = [
  "#4cc9f0",
  "#f72585",
  "#b5e48c",
  "#ffb703",
  "#c77dff",
  "#ff7b00",
  "#90e0ef",
  "#e63946",
];

export function colorFor(index: number): string {
  return PALETTE[index % PALETTE.length];
}
