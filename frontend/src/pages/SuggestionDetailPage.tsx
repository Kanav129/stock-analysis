import { lazy, Suspense } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { LoadingState } from '../components/LoadingSpinner';
import { Panel } from '../components/Panel';

const ReportMarkdown = lazy(() =>
  import('../components/ReportMarkdown').then((m) => ({ default: m.ReportMarkdown })),
);

function stanceLabel(stance: string | undefined) {
  switch ((stance || '').toLowerCase()) {
    case 'diversifies':
      return 'Diversifies your book';
    case 'concentrated':
      return 'Adds to an already heavy sector';
    default:
      return 'Neutral portfolio fit';
  }
}

export function SuggestionDetailPage() {
  const { ticker: raw } = useParams();
  const ticker = (raw || '').toUpperCase();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const detailQ = useQuery({
    queryKey: ['watchlist-suggestion', ticker],
    queryFn: () => api.getWatchlistSuggestion(ticker),
    enabled: Boolean(ticker),
    retry: false,
  });

  const accept = useMutation({
    mutationFn: () => api.acceptWatchlistSuggestion(ticker),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlist-suggestions'] });
      qc.invalidateQueries({ queryKey: ['watchlist'] });
      qc.invalidateQueries({ queryKey: ['desk-snapshot'] });
      qc.invalidateQueries({ queryKey: ['universe'] });
      qc.invalidateQueries({ queryKey: ['jobs'] });
      navigate(`/stock/${ticker}`);
    },
  });

  if (!ticker) {
    return <p className="text-sm text-[var(--color-text-muted)]">Missing ticker.</p>;
  }

  if (detailQ.isLoading) {
    return <LoadingState label="Loading suggestion brief…" minHeight="16rem" />;
  }

  if (detailQ.isError || !detailQ.data) {
    return (
      <div className="flex flex-col gap-4 animate-fade-up">
        <Link to="/" className="text-sm text-[var(--color-accent)] hover:underline">
          ← Back to desk
        </Link>
        <Panel title="Suggestion unavailable">
          <p className="text-sm text-[var(--color-text-secondary)]">
            This idea may have expired or been removed. Run sync to refresh suggestions.
          </p>
        </Panel>
      </div>
    );
  }

  const item = detailQ.data;
  const brief = item.brief;
  const fit = brief?.portfolio_fit;
  const warning = fit?.warning?.trim();

  return (
    <div className="flex flex-col gap-6 animate-fade-up">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-text-muted)]">
            <Link to="/" className="text-[var(--color-accent)] hover:underline">
              Desk
            </Link>
            <span aria-hidden="true">/</span>
            <Link to="/watchlist" className="text-[var(--color-accent)] hover:underline">
              Watchlist
            </Link>
          </div>
          <h2 className="mt-2 font-display font-display-title text-2xl font-semibold">
            <span className="font-mono text-[var(--color-accent)]">{item.ticker}</span>
            {item.company_name ? (
              <span className="ml-2 text-[var(--color-text-primary)]">{item.company_name}</span>
            ) : null}
          </h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            {[item.sector, item.industry].filter(Boolean).join(' · ') || 'Suggestion brief'}
          </p>
        </div>
        <button
          type="button"
          disabled={accept.isPending}
          onClick={() => accept.mutate()}
          className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-[var(--color-surface-0)] disabled:opacity-50"
        >
          {accept.isPending ? 'Adding…' : 'Add to watchlist'}
        </button>
      </div>

      {item.company_blurb ? (
        <Panel title="Company" dense>
          <p className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
            {item.company_blurb}
          </p>
        </Panel>
      ) : null}

      <Panel title="Why suggested" dense>
        <p className="text-sm leading-relaxed text-[var(--color-text-primary)]">{item.reason}</p>
      </Panel>

      {fit ? (
        <Panel title="Portfolio fit" subtitle={stanceLabel(fit.stance)} dense>
          {warning ? (
            <p className="mb-2 rounded border border-[var(--color-down)]/40 bg-[var(--color-down)]/10 px-3 py-2 text-sm text-[var(--color-down)]">
              {warning}
            </p>
          ) : null}
          {fit.note ? (
            <p className="text-sm leading-relaxed text-[var(--color-text-secondary)]">{fit.note}</p>
          ) : null}
        </Panel>
      ) : null}

      {brief?.thesis ? (
        <Panel title="Thesis" dense>
          <Suspense fallback={<LoadingState label="Loading…" compact minHeight="4rem" />}>
            <div className="prose-desk text-sm">
              <ReportMarkdown content={brief.thesis} />
            </div>
          </Suspense>
        </Panel>
      ) : null}

      {brief?.reasons?.length ? (
        <Panel title="Reasons to watch" dense>
          <ol className="flex flex-col gap-3">
            {brief.reasons.map((r, i) => (
              <li key={`${r.title}-${i}`} className="text-sm">
                <p className="font-medium text-[var(--color-text-primary)]">
                  {i + 1}. {r.title}
                </p>
                <p className="mt-0.5 leading-relaxed text-[var(--color-text-secondary)]">
                  {r.detail}
                </p>
              </li>
            ))}
          </ol>
        </Panel>
      ) : null}

      {brief?.sources?.length ? (
        <Panel title="Sources" dense>
          <ul className="flex flex-col gap-2">
            {brief.sources.map((s, i) => (
              <li key={`${s.title}-${i}`} className="text-sm">
                {s.url ? (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--color-accent)] hover:underline"
                  >
                    {s.title || s.url}
                  </a>
                ) : (
                  <span className="text-[var(--color-text-primary)]">{s.title || 'Source'}</span>
                )}
                {s.publisher ? (
                  <span className="ml-2 text-xs text-[var(--color-text-muted)]">{s.publisher}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={accept.isPending}
          onClick={() => accept.mutate()}
          className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-[var(--color-surface-0)] disabled:opacity-50"
        >
          {accept.isPending ? 'Adding…' : 'Add to watchlist & run analysis'}
        </button>
        <Link
          to="/watchlist"
          className="rounded-md border border-[var(--color-surface-3)] px-4 py-2 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)]"
        >
          Back to watchlist
        </Link>
      </div>
    </div>
  );
}
