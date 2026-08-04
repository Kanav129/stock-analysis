import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ReportHistoryItem } from '../api/types';
import { CompactTable } from './CompactTable';
import { LoadingState } from './LoadingSpinner';
import { Panel } from './Panel';
import { RatingBadge } from './RatingBadge';

function fmtDate(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function typeLabel(t: string) {
  return t === 'deep' ? 'Deep' : 'Core';
}

function PdfButton({
  ticker,
  item,
}: {
  ticker: string;
  item: ReportHistoryItem;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onClick = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.downloadReportPdf(ticker, item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="recent-reports__download">
      <button
        type="button"
        className="btn-terminal recent-reports__pdf-btn"
        disabled={busy}
        onClick={() => void onClick()}
        title={`Download ${ticker} report PDF`}
      >
        {busy ? '…' : 'PDF'}
      </button>
      {error ? (
        <span className="recent-reports__err" title={error}>
          !
        </span>
      ) : null}
    </div>
  );
}

export function RecentReportsPanel({ ticker }: { ticker: string }) {
  const t = ticker.toUpperCase();
  const historyQ = useQuery({
    queryKey: ['report-history', t],
    queryFn: () => api.getReportHistory(t),
    enabled: !!t,
    staleTime: 60_000,
  });

  const items = historyQ.data?.items ?? [];

  return (
    <Panel title="Recent reports" subtitle="Newest first" dense>
      {historyQ.isLoading ? (
        <LoadingState label="Loading reports…" compact minHeight="6rem" />
      ) : historyQ.isError ? (
        <p className="text-xs text-[var(--color-down)]">
          {historyQ.error instanceof Error
            ? historyQ.error.message
            : 'Failed to load report history'}
        </p>
      ) : !items.length ? (
        <p className="text-xs text-[var(--color-text-muted)]">
          No saved reports yet.
        </p>
      ) : (
        <div className="recent-reports">
          <CompactTable
            headers={['Date', 'Score', 'Rating', 'Type', 'Download']}
            centerCols={[1, 4]}
            caption={`Recent research reports for ${t}`}
          >
            {items.map((item) => (
              <tr key={item.id}>
                <td className="font-mono text-[11px] whitespace-nowrap">
                  {fmtDate(item.created_at)}
                </td>
                <td className="is-center font-mono text-[11px] tabular-nums">
                  {item.score != null ? (item.score > 0 ? `+${item.score}` : item.score) : '—'}
                </td>
                <td>
                  {item.rating ? (
                    <RatingBadge rating={item.rating} reportType={item.report_type} />
                  ) : (
                    <span className="text-[var(--color-text-muted)]">—</span>
                  )}
                </td>
                <td className="font-mono text-[11px] uppercase text-[var(--color-text-secondary)]">
                  {typeLabel(item.report_type)}
                </td>
                <td className="is-center">
                  <PdfButton ticker={t} item={item} />
                </td>
              </tr>
            ))}
          </CompactTable>
        </div>
      )}
    </Panel>
  );
}
