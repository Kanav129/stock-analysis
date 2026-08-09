import { useState, type ReactNode } from 'react';

export function SectionAccordion({
  id,
  title,
  children,
  defaultOpen = false,
}: {
  id?: string;
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div id={id} className={`section-accordion${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="section-accordion__trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className="section-accordion__chevron" aria-hidden>
          ▸
        </span>
      </button>
      <div className="section-accordion__panel" inert={!open ? true : undefined}>
        <div className="section-accordion__panel-inner">
          <div className="section-accordion__body">{children}</div>
        </div>
      </div>
    </div>
  );
}
