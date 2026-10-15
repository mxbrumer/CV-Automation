import MarkdownIt from 'markdown-it'
import { useMemo } from 'react'

// html: false, so text in a posting or a model reply can never inject markup.
const md = new MarkdownIt({ html: false, linkify: false })

export default function Markdown({ source }: { source: string }) {
  const html = useMemo(() => md.render(source), [source])
  return (
    <div
      data-testid="markdown-preview"
      className="space-y-2 text-sm leading-relaxed [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-3 [&_h2]:font-semibold [&_h3]:font-medium [&_li]:ml-5 [&_li]:list-disc [&_a]:text-accent [&_a]:underline"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
