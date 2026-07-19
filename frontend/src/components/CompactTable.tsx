import type { ReactNode } from 'react';

export function CompactTable({
  headers,
  children,
  empty,
  /** Column indexes to center (0-based). */
  centerCols,
}: {
  headers: ReactNode[];
  children: ReactNode;
  empty?: ReactNode;
  centerCols?: number[];
}) {
  const centered = new Set(centerCols ?? []);

  return (
    <div className="overflow-x-auto">
      <table className="compact-table">
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
