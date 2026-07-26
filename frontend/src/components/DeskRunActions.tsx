import { RunAnalysisButton } from './RunAnalysisButton';
import { SyncDataButton } from './SyncDataButton';

type Props = {
  /** Watchlist only needs sync; dashboard shows both. */
  showAnalysis?: boolean;
  className?: string;
};

/** Level Sync / Analysis pill triggers on one baseline. */
export function DeskRunActions({ showAnalysis = true, className = '' }: Props) {
  return (
    <div className={`desk-run-actions ${className}`.trim()}>
      <SyncDataButton />
      {showAnalysis ? <RunAnalysisButton /> : null}
    </div>
  );
}
