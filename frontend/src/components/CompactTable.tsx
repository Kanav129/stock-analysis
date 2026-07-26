import type { ReactNode } from 'react';

export function CompactTable({
  headers,
  children,
  empty,
  caption,
  /** Column indexes to center (0-based). */
  centerCols,
}: {
  headers: ReactNode[];
  children: ReactNode;
  empty?: ReactNode;
  caption?: string;
  centerCols?: number[];
}) {
  const centered = new Set(centerCols ?? []);

  return (
    <div className="overflow-x-auto">
      <table className="compact-table">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} className={centered.has(i) ? 'is-center' : undefined}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {children}
          {!children && empty && (
            <tr>
              <td colSpan={headers.length} className="py-6 text-center text-[var(--color-text-muted)]">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
