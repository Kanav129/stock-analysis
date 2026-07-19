export type ChartRangeId = '1' | '7' | '15' | '14' | '30' | '90' | '180' | '365' | 'all';

export const CHART_RANGES: { id: ChartRangeId; label: string; hint: string }[] = [
  { id: '1', label: '1D', hint: '5-minute bars' },
  { id: '7', label: '7D', hint: 'Daily close' },
  { id: '15', label: '15D', hint: 'Daily close' },
  { id: '14', label: '2W', hint: 'Daily close' },
  { id: '30', label: '1M', hint: 'Daily close' },
  { id: '90', label: '3M', hint: 'Daily close' },
  { id: '180', label: '6M', hint: 'Daily close' },
  { id: '365', label: '1Y', hint: 'Full year' },
  { id: 'all', label: 'All', hint: 'Full history' },
];

export function ChartRangeToggle({
  value,
  onChange,
}: {
  value: ChartRangeId;
  onChange: (id: ChartRangeId) => void;
}) {
  return (
    <div className="chart-range" role="group" aria-label="Chart date range">
      {CHART_RANGES.map((r) => (
        <button
          key={r.id}
          type="button"
          className="chart-range__btn"
          aria-pressed={value === r.id}
          title={r.hint}
          onClick={() => onChange(r.id)}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

export function chartRangeHint(id: ChartRangeId): string {
  return CHART_RANGES.find((r) => r.id === id)?.hint ?? 'Price history';
}
