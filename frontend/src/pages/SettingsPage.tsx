import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

const MODEL_PRESETS = [
  'deepseek/deepseek-v4-pro',
  'deepseek/deepseek-v4-flash',
  'openai/gpt-4o-mini',
  'openai/gpt-4o',
  'anthropic/claude-sonnet-4',
  'google/gemini-2.5-flash',
  'meta-llama/llama-4-maverick',
];

function fmtCredits(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return `$${Number(n).toFixed(2)}`;
}

export function SettingsPage() {
  const qc = useQueryClient();
  const settingsQ = useQuery({ queryKey: ['settings'], queryFn: api.getSettings });
  const openrouterQ = useQuery({
    queryKey: ['openrouter-status'],
    queryFn: api.getOpenRouterStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const [analysisModel, setAnalysisModel] = useState('');
  const [researchModel, setResearchModel] = useState('');
  const [interval, setIntervalSec] = useState('86400');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    if (settingsQ.data) {
      setAnalysisModel(settingsQ.data.analysis_model ?? '');
      setResearchModel(settingsQ.data.research_model ?? '');
      setIntervalSec(settingsQ.data.analysis_interval ?? '86400');
      setApiKey('');
    }
  }, [settingsQ.data]);

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, string | number> = {
        analysis_model: analysisModel.trim(),
        research_model: researchModel.trim(),
        analysis_interval: Number(interval),
      };
      if (apiKey.trim()) {
        payload.openrouter_api_key = apiKey.trim();
      }
      return api.updateSettings(payload);
    },
    onSuccess: () => {
      setApiKey('');
      qc.invalidateQueries({ queryKey: ['settings'] });
      qc.invalidateQueries({ queryKey: ['openrouter-status'] });
    },
  });

  const or = openrouterQ.data;
  const key = or?.key;
  const credits = or?.credits;

  return (
    <div className="flex max-w-2xl flex-col gap-6 animate-fade-up">
      <div>
        <h2 className="font-display text-2xl font-semibold">Settings</h2>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          OpenRouter API, models, and scheduling.
        </p>
      </div>

      {/* ── API (OpenRouter) ── */}
      <section className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-display text-lg font-medium">API</h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              OpenRouter powers research (flash) and decision (pro) models.
            </p>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] font-semibold ${
              or?.connected
                ? 'bg-[color-mix(in_oklch,var(--color-up)_18%,transparent)] text-[var(--color-up)]'
                : 'bg-[var(--color-surface-2)] text-[var(--color-text-muted)]'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                or?.connected ? 'bg-[var(--color-up)]' : 'bg-[var(--color-text-muted)]'
              }`}
            />
            {openrouterQ.isLoading ? 'Checking…' : or?.connected ? 'Connected' : 'Not connected'}
          </span>
        </div>

        {/* Credits / usage */}
        <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              Remaining
            </p>
            <p
              className={`mt-1 font-mono text-lg font-semibold tabular-nums ${
                or?.low_balance ? 'text-[var(--color-sell)]' : 'text-[var(--color-text-primary)]'
              }`}
            >
              {credits?.remaining != null
                ? fmtCredits(credits.remaining)
                : key?.limit_remaining != null
                  ? fmtCredits(key.limit_remaining)
                  : or?.connected
                    ? 'Unlimited'
                    : '—'}
            </p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
              {credits?.remaining != null
                ? 'Account balance'
                : key?.limit_remaining != null
                  ? 'Key limit left'
                  : 'Key / account'}
            </p>
          </div>
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              Today
            </p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-[var(--color-text-primary)]">
              {fmtCredits(key?.usage_daily)}
            </p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">Usage</p>
          </div>
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              This month
            </p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-[var(--color-text-primary)]">
              {fmtCredits(key?.usage_monthly)}
            </p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">Usage</p>
          </div>
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              All time
            </p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-[var(--color-text-primary)]">
              {fmtCredits(key?.usage)}
            </p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">Usage</p>
          </div>
        </div>

        {or?.message && (
          <p
            className={`mb-4 text-xs ${
              or.low_balance
                ? 'text-[var(--color-sell)]'
                : or.connected
                  ? 'text-[var(--color-text-secondary)]'
                  : 'text-[var(--color-text-muted)]'
            }`}
          >
            {or.message}
            {key?.label ? ` · Key: ${key.label}` : ''}
            {settingsQ.data?.openrouter_api_key_source === 'env' ? ' · from .env' : ''}
            {settingsQ.data?.openrouter_api_key_masked
              ? ` · ${settingsQ.data.openrouter_api_key_masked}`
              : ''}
          </p>
        )}

        {or?.credits_note && or.connected && (
          <p className="mb-4 text-[11px] text-[var(--color-text-muted)]">{or.credits_note}</p>
        )}

        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--color-text-secondary)]">OpenRouter API key</span>
            <div className="flex gap-2">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  settingsQ.data?.openrouter_api_key_set === 'true'
                    ? 'Leave blank to keep current key'
                    : 'sk-or-v1-…'
                }
                autoComplete="off"
                className="min-w-0 flex-1 rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
              />
              <button
                type="button"
                className="btn-terminal shrink-0"
                onClick={() => setShowKey((v) => !v)}
              >
                {showKey ? 'Hide' : 'Show'}
              </button>
            </div>
            <span className="text-[11px] text-[var(--color-text-muted)]">
              Stored in app settings (overrides .env). Get a key at{' '}
              <a
                href="https://openrouter.ai/keys"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--color-accent)] underline"
              >
                openrouter.ai/keys
              </a>
              . Top up credits at{' '}
              <a
                href="https://openrouter.ai/credits"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--color-accent)] underline"
              >
                openrouter.ai/credits
              </a>
              .
            </span>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--color-text-secondary)]">
              ANALYSIS_MODEL <span className="text-[var(--color-text-muted)]">(decision / rating)</span>
            </span>
            <input
              list="analysis-model-presets"
              value={analysisModel}
              onChange={(e) => setAnalysisModel(e.target.value)}
              className="rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
            />
            <datalist id="analysis-model-presets">
              {MODEL_PRESETS.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--color-text-secondary)]">
              RESEARCH_MODEL <span className="text-[var(--color-text-muted)]">(report sections)</span>
            </span>
            <input
              list="research-model-presets"
              value={researchModel}
              onChange={(e) => setResearchModel(e.target.value)}
              className="rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
            />
            <datalist id="research-model-presets">
              {MODEL_PRESETS.map((m) => (
                <option key={`r-${m}`} value={m} />
              ))}
            </datalist>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--color-text-secondary)]">Auto-pipeline interval (seconds)</span>
            <input
              value={interval}
              onChange={(e) => setIntervalSec(e.target.value)}
              type="number"
              min={60}
              className="rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="btn-terminal btn-terminal--accent"
            >
              {save.isPending ? 'Saving…' : 'Save API settings'}
            </button>
            <button
              type="button"
              className="btn-terminal"
              disabled={openrouterQ.isFetching}
              onClick={() => qc.invalidateQueries({ queryKey: ['openrouter-status'] })}
            >
              {openrouterQ.isFetching ? 'Refreshing…' : 'Refresh credits'}
            </button>
            {save.isSuccess && (
              <span className="text-xs text-[var(--color-up)]">Saved</span>
            )}
            {save.isError && (
              <span className="text-xs text-[var(--color-down)]">
                {save.error instanceof Error ? save.error.message : 'Save failed'}
              </span>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
