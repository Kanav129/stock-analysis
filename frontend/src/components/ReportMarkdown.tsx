/** Custom markdown renderer — renders LLM-generated markdown with dark trading-desk styling. */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';

function TableWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ overflowX: 'auto', margin: '12px 0 18px', border: '1px solid var(--color-surface-3)', borderRadius: 6, background: 'var(--color-surface-0)' }}>
      {children}
    </div>
  );
}

export function ReportMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={{
        table: ({ children }) => (
          <TableWrapper>
            <table style={{ width: '100%', minWidth: '32rem', borderCollapse: 'collapse', fontSize: 14, lineHeight: 1.45, tableLayout: 'auto' }}>
              {children}
            </table>
          </TableWrapper>
        ),
        thead: ({ children }) => <thead>{children}</thead>,
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => <tr>{children}</tr>,
        th: ({ children }) => (
          <th style={{ padding: '10px 14px', border: '1px solid var(--color-surface-3)', textAlign: 'left', verticalAlign: 'top', background: 'var(--color-surface-1)', fontWeight: 650, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.03em', color: 'var(--color-text-muted)' }}>
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td style={{ padding: '10px 14px', border: '1px solid var(--color-surface-3)', textAlign: 'left', verticalAlign: 'top', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
            {children}
          </td>
        ),
        h1: ({ children }) => <h1 style={{ fontSize: '1.125rem', margin: '1.4em 0 0.6em', fontWeight: 600, lineHeight: 1.25, textWrap: 'balance' }}>{children}</h1>,
        h2: ({ children }) => <h2 style={{ fontSize: '1.125rem', margin: '1.6em 0 0.55em', paddingBottom: '0.35em', borderBottom: '1px solid var(--color-surface-3)', fontWeight: 600, lineHeight: 1.3, textWrap: 'balance' }}>{children}</h2>,
        h3: ({ children }) => <h3 style={{ fontSize: '0.875rem', margin: '1.35em 0 0.45em', fontWeight: 600, textWrap: 'balance' }}>{children}</h3>,
        h4: ({ children }) => <h4 style={{ fontSize: '0.6875rem', margin: '1.1em 0 0.4em', color: 'var(--color-text-muted)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>{children}</h4>,
        p: ({ children }) => <p style={{ margin: '0 0 1em', maxWidth: '75ch', fontSize: '0.875rem', lineHeight: 1.45, textWrap: 'pretty' }}>{children}</p>,
        ul: ({ children }) => <ul style={{ margin: '0 0 1em', paddingLeft: '1.5em', maxWidth: '75ch' }}>{children}</ul>,
        ol: ({ children }) => <ol style={{ margin: '0 0 1em', paddingLeft: '1.5em', maxWidth: '75ch' }}>{children}</ol>,
        li: ({ children }) => <li style={{ margin: '0.35em 0', paddingLeft: '0.15em' }}>{children}</li>,
        strong: ({ children }) => <strong style={{ fontWeight: 650 }}>{children}</strong>,
        blockquote: ({ children }) => (
          <blockquote style={{ margin: '0 0 1em', padding: '10px 14px', border: '1px solid var(--gridline)', color: 'var(--color-text-secondary)', background: 'var(--color-surface-2)', borderRadius: 6, maxWidth: '75ch' }}>
            {children}
          </blockquote>
        ),
        code: ({ className, children, ...props }: any) => {
          const isInline = !className;
          if (isInline) {
            return <code style={{ fontFamily: '"JetBrains Mono", ui-monospace, monospace', background: 'var(--color-surface-1)', padding: '0.12em 0.4em', borderRadius: 4, fontSize: '0.88em' }} {...props}>{children}</code>;
          }
          return (
            <pre style={{ width: '100%', background: 'var(--color-surface-1)', padding: '14px 16px', borderRadius: 6, overflowX: 'auto', fontSize: 13, lineHeight: 1.5, border: '1px solid var(--color-surface-3)' }}>
              <code className={className} style={{ background: 'transparent', padding: 0 }} {...props}>{children}</code>
            </pre>
          );
        },
        hr: () => <hr style={{ border: 0, borderTop: '1px solid var(--color-surface-3)', margin: '28px 0' }} />,
        a: ({ href, children }) => <a href={href} style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>{children}</a>,
        em: ({ children }) => <em>{children}</em>,
        img: ({ src, alt }) => <img src={src} alt={alt} style={{ maxWidth: '100%', height: 'auto' }} />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
