import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { LoadingSpinner, LoadingState } from '../components/LoadingSpinner';

const MODEL_PRESETS = [
  'qwen3.7-max',
  'qwen3.7-flash',
  'qwen3.7-plus',
  'qwen3.8-max',
  'qwen3.5-flash',
  'text-embedding-v4',
];

function fmtCredits(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return `$${Number(n).toFixed(2)}`;
}

export function SettingsPage() {
  const qc = useQueryClient();
  const settingsQ = useQuery({ queryKey: ['settings'], queryFn: api.getSettings });
  const llmQ = useQuery({
    queryKey: ['llm-status'],
    queryFn: api.getLlmStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const [analysisModel, setAnalysisModel] = useState('');
  const [researchModel, setResearchModel] = useState('');
  const [syncInterval, setSyncInterval] = useState('86400');
  const [analysisInterval, setAnalysisInterval] = useState('604800');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    if (settingsQ.data) {
      setAnalysisModel(settingsQ.data.analysis_model ?? '');
      setResearchModel(settingsQ.data.research_model ?? '');
      setSyncInterval(settingsQ.data.sync_interval ?? '86400');
      setAnalysisInterval(settingsQ.data.analysis_interval ?? '604800');
      setApiKey('');
    }
  }, [settingsQ.data]);

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, string | number> = {
        analysis_model: analysisModel.trim(),
        research_model: researchModel.trim(),
        sync_interval: Number(syncInterval),
        analysis_interval: Number(analysisInterval),
      };
      if (apiKey.trim()) {
        payload.llm_api_key = apiKey.trim();
      }
      return api.updateSettings(payload);
    },
    onSuccess: () => {
      setApiKey('');
      qc.invalidateQueries({ queryKey: ['settings'] });
      qc.invalidateQueries({ queryKey: ['llm-status'] });
    },
  });

  const llm = llmQ.data;
  const key = llm?.key;
  const credits = llm?.credits;

  if (settingsQ.isLoading && !settingsQ.data) {
    return (
      <div className="flex max-w-2xl flex-col gap-6 animate-fade-up">
        <div>
          <h2 className="font-display text-2xl font-semibold">Settings</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Qwen API, models, and scheduling.
          </p>
        </div>
        <LoadingState label="Loading settings…" minHeight="16rem" />
      </div>
    );
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6 animate-fade-up">
      <div>
        <h2 className="font-display text-2xl font-semibold">Settings</h2>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          Qwen API, models, and scheduling.
        </p>
      </div>

      <section className="rounded-[var(--panel-radius)] border border-[var(--color-surface-3)] bg-[var(--color-surface-1)] p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-display text-lg font-medium">API</h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              Qwen (DashScope) powers research ({researchModel || 'flash'}) and decision (
              {analysisModel || 'max'}) models.
            </p>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[length:var(--text-label)] font-semibold ${
              llm?.connected
                ? 'bg-[color-mix(in_oklch,var(--color-up)_18%,transparent)] text-[var(--color-up)]'
                : 'bg-[var(--color-surface-2)] text-[var(--color-text-muted)]'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                llm?.connected ? 'bg-[var(--color-up)]' : 'bg-[var(--color-text-muted)]'
              }`}
            />
            {llmQ.isLoading ? (
              <span className="inline-flex items-center gap-1.5">
                <LoadingSpinner size="sm" />
                Checking…
              </span>
            ) : llm?.connected ? (
              'Connected'
            ) : (
              'Not connected'
            )}
          </span>
        </div>

        <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5">
            <p className="text-[length:var(--text-label)] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              Balance
            </p>
            <p
              className={`mt-1 font-mono text-lg font-semibold tabular-nums ${
                llm?.low_balance ? 'text-[var(--color-sell)]' : 'text-[var(--color-text-primary)]'
              }`}
            >
              {credits?.remaining != null ? fmtCredits(credits.remaining) : llm?.connected ? '—' : '—'}
            </p>
            <p className="mt-0.5 text-[length:var(--text-label)] text-[var(--color-text-muted)]">
              Account credit
            </p>
          </div>
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5">
            <p className="text-[length:var(--text-label)] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              Models
            </p>
            <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-[var(--color-text-primary)]">
              {key?.models_available != null ? key.models_available : '—'}
            </p>
            <p className="mt-0.5 text-[length:var(--text-label)] text-[var(--color-text-muted)]">
              Available via API
            </p>
          </div>
          <div className="rounded border border-[var(--color-surface-3)] bg-[var(--color-surface-2)] px-3 py-2.5 sm:col-span-1 col-span-2">
            <p className="text-[length:var(--text-label)] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              Provider
            </p>
            <p className="mt-1 font-mono text-lg font-semibold text-[var(--color-text-primary)]">
              Qwen
            </p>
            <p className="mt-0.5 text-[length:var(--text-label)] text-[var(--color-text-muted)]">
              DashScope compatible-mode
            </p>
          </div>
        </div>

        {llm?.message && (
          <p
            className={`mb-4 text-xs ${
              llm.low_balance
                ? 'text-[var(--color-sell)]'
                : llm.connected
                  ? 'text-[var(--color-text-secondary)]'
                  : 'text-[var(--color-text-muted)]'
            }`}
          >
            {llm.message}
            {key?.label ? ` · ${key.label}` : ''}
            {settingsQ.data?.llm_api_key_source === 'env' ? ' · from .env' : ''}
            {settingsQ.data?.llm_api_key_masked ? ` · ${settingsQ.data.llm_api_key_masked}` : ''}
          </p>
        )}

        {llm?.credits_note && llm.connected && (
          <p className="mb-4 text-[length:var(--text-label)] text-[var(--color-text-muted)]">
            {llm.credits_note}
          </p>
        )}

        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--color-text-secondary)]">Qwen API key</span>
            <div className="flex gap-2">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  settingsQ.data?.llm_api_key_set === 'true'
                    ? 'Leave blank to keep current key'
                    : 'sk-…'
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
            <span className="text-[length:var(--text-label)] text-[var(--color-text-muted)]">
              Stored in app settings (overrides .env). Get a key at{' '}
              <a
                href="https://www.qwencloud.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--color-accent)] underline"
              >
                qwencloud.com
              </a>
              . Manage billing in the{' '}
              <a
                href="https://dashscope.console.aliyun.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--color-accent)] underline"
              >
                DashScope console
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
            <span className="text-[var(--color-text-secondary)]">
              Sync interval (seconds){' '}
              <span className="text-[var(--color-text-muted)]">prices + news · default 86400 = daily</span>
            </span>
            <input
              value={syncInterval}
              onChange={(e) => setSyncInterval(e.target.value)}
              type="number"
              min={60}
              className="rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-[var(--color-text-secondary)]">
              Analysis interval (seconds){' '}
              <span className="text-[var(--color-text-muted)]">reports · default 604800 = weekly</span>
            </span>
            <input
              value={analysisInterval}
              onChange={(e) => setAnalysisInterval(e.target.value)}
              type="number"
              min={60}
              className="rounded-md bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm outline-none ring-[var(--color-accent)] focus:ring-2"
            />
          </label>
          <p className="text-xs text-[var(--color-text-muted)]">
            On Render free tier, keep in-process auto off and use GitHub Actions cron (see README) to wake the dyno.
          </p>

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
              disabled={llmQ.isFetching}
              onClick={() => qc.invalidateQueries({ queryKey: ['llm-status'] })}
            >
              {llmQ.isFetching ? 'Refreshing…' : 'Refresh status'}
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
