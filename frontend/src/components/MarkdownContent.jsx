import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function MarkdownContent({ content, isStreaming = false, className = '' }) {
  if (!content) return null

  return (
    <div className={`text-sm text-white/85 leading-relaxed space-y-2 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p({ children }) {
            return (
              <p className="text-sm leading-relaxed text-white/85 my-1.5 first:mt-0 last:mb-0">
                {children}
              </p>
            )
          },
          strong({ children }) {
            return <strong className="font-semibold text-white">{children}</strong>
          },
          em({ children }) {
            return <em className="italic text-white/90">{children}</em>
          },
          a({ href, children }) {
            if (!href) return <span>{children}</span>
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:text-accent-light underline underline-offset-2 transition-colors"
              >
                {children}
              </a>
            )
          },
          ul({ children }) {
            return (
              <ul className="list-disc list-outside ml-5 my-2 space-y-1 text-sm text-white/85">
                {children}
              </ul>
            )
          },
          ol({ children }) {
            return (
              <ol className="list-decimal list-outside ml-5 my-2 space-y-1 text-sm text-white/85">
                {children}
              </ol>
            )
          },
          li({ children }) {
            return <li className="leading-relaxed">{children}</li>
          },
          h1({ children }) {
            return (
              <h1 className="text-base font-bold text-white mt-4 mb-2">{children}</h1>
            )
          },
          h2({ children }) {
            return (
              <h2 className="text-sm font-bold text-white mt-3 mb-1.5">{children}</h2>
            )
          },
          h3({ children }) {
            return (
              <h3 className="text-xs font-bold text-white/90 mt-2.5 mb-1">{children}</h3>
            )
          },
          h4({ children }) {
            return (
              <h4 className="text-xs font-semibold text-white/80 mt-2 mb-1">{children}</h4>
            )
          },
          blockquote({ children }) {
            return (
              <blockquote className="border-l-2 border-white/30 pl-3 italic text-white/70 my-2 text-xs">
                {children}
              </blockquote>
            )
          },
          hr() {
            return <hr className="border-white/10 my-3" />
          },
          table({ children }) {
            return (
              <div className="overflow-x-auto my-2">
                <table className="text-xs w-full border-collapse">{children}</table>
              </div>
            )
          },
          th({ children }) {
            return (
              <th className="border border-white/15 px-2 py-1 text-accent font-semibold text-left">
                {children}
              </th>
            )
          },
          td({ children }) {
            return (
              <td className="border border-white/15 px-2 py-1 align-top">{children}</td>
            )
          },
          code({ className: codeClassName, children, ...props }) {
            const match = /language-(\w+)/.exec(codeClassName || '')
            const isMultiLine = String(children).includes('\n')
            const isInline = !match && !isMultiLine

            if (isInline) {
              return (
                <code
                  className="bg-white/10 text-amber-300 font-mono text-[11px] px-1.5 py-0.5 rounded border border-white/10"
                  {...props}
                >
                  {children}
                </code>
              )
            }

            return (
              <pre className="bg-neutral-900 border border-white/10 p-3 rounded-lg overflow-x-auto font-mono text-xs my-2 text-white/90 leading-relaxed">
                <code className={codeClassName} {...props}>
                  {children}
                </code>
              </pre>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>

      {isStreaming && (
        <span className="inline-block w-1 h-3.5 ml-1 animate-pulse bg-white/50 align-middle" />
      )}
    </div>
  )
}
