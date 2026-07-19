import type { ReactNode } from 'react';
import { Sparkline } from './Sparkline';
import { DeltaValue } from './DeltaValue';

export function StatTile({
  label,
  value,
  changePct,
  spark,
  footer,
}: {
  label: string;
  value: ReactNode;
  changePct?: number | null;
  spark?: number[];
  footer?: ReactNode;
}) {
  return (
    <div className="stat-tile">
      <div className="flex items-start justify-between gap-2">
        <p className="stat-tile__label">{label}</p>
        {spark && spark.length > 1 && <Sparkline data={spark} width={56} height={18} />}
      </div>
      <div className="stat-tile__value font-mono">{value}</div>
      {(changePct != null || footer) && (
        <div className="mt-1 flex items-center gap-2 text-xs">
          {changePct != null && <DeltaValue value={changePct} />}
          {footer}
        </div>
      )}
    </div>
  );
}
