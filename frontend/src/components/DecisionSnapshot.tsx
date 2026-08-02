/** Compact right-rail decision summary — no full thesis (that lives in the report). */
import type { Rating, ReportType } from '../api/types';
import { RatingBadge } from './RatingBadge';
import { ScoreMeter } from './ScoreMeter';

type Props = {
  rating: Rating | string;
  score: number;
  reportType?: ReportType | string | null;
  posture?: string | null;
  onJumpToThesis?: () => void;
};

export function DecisionSnapshot({
  rating,
  score,
  reportType,
  posture,
  onJumpToThesis,
}: Props) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <RatingBadge rating={rating} reportType={reportType} />
        <ScoreMeter value={score} size="sm" reportType={reportType} />
      </div>
      {posture ? (
        <p className="text-xs leading-relaxed text-[var(--color-text-secondary)]">
          {posture}
        </p>
      ) : null}
      {onJumpToThesis ? (
        <button
          type="button"
          className="btn-terminal self-start"
          onClick={onJumpToThesis}
        >
          Full thesis in report ↓
        </button>
      ) : null}
    </div>
  );
}
