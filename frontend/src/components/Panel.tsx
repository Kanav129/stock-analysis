import type { ReactNode, CSSProperties } from 'react';

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = '',
  style,
  dense = false,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  dense?: boolean;
}) {
  return (
    <section
      className={`terminal-panel ${dense ? 'terminal-panel--dense' : ''} ${className}`}
      style={style}
    >
      {(title || actions) && (
        <header className="terminal-panel__header">
          <div className="min-w-0">
            {title && <h3 className="terminal-panel__title">{title}</h3>}
            {subtitle && <p className="terminal-panel__subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="terminal-panel__actions">{actions}</div>}
        </header>
      )}
      <div className="terminal-panel__body">{children}</div>
    </section>
  );
}
