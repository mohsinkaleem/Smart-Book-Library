import { useEffect, useState } from 'react';
import { ChevronRight, List } from 'lucide-react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { Spinner } from '../common/Spinner';

interface OutlineNode {
  title: string;
  page: number | null;
  depth: number;
  children: OutlineNode[];
}

/** pdf.js's outline entries, as much of them as we read. */
interface RawOutlineItem {
  title: string;
  dest: string | unknown[] | null;
  items?: RawOutlineItem[];
}

/**
 * Resolve one outline entry to a 1-based page number.
 *
 * A destination is either a named string that has to be looked up, or an
 * explicit array whose first element is a page reference. Both end at
 * `getPageIndex`, and either can fail on a malformed PDF — an entry with no
 * resolvable page still belongs in the tree, just without a link.
 */
async function resolvePage(doc: PDFDocumentProxy, dest: RawOutlineItem['dest']): Promise<number | null> {
  try {
    const explicit = typeof dest === 'string' ? await doc.getDestination(dest) : dest;
    if (!Array.isArray(explicit) || explicit.length === 0) return null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const index = await doc.getPageIndex(explicit[0] as any);
    return index + 1;
  } catch {
    return null;
  }
}

async function buildTree(
  doc: PDFDocumentProxy,
  items: RawOutlineItem[],
  depth: number,
): Promise<OutlineNode[]> {
  return Promise.all(
    items.map(async (item) => ({
      title: item.title || 'Untitled',
      page: await resolvePage(doc, item.dest),
      depth,
      children: item.items?.length ? await buildTree(doc, item.items, depth + 1) : [],
    })),
  );
}

interface PdfOutlineProps {
  doc: PDFDocumentProxy | null;
  currentPage: number;
  onNavigate: (page: number) => void;
}

/**
 * The PDF's own table of contents.
 *
 * The EPUB reader has had one since it shipped and the PDF reader never did,
 * even though most of the technical PDFs in this library carry an outline —
 * leaving a 600-page book navigable only by typing page numbers.
 */
export function PdfOutline({ doc, currentPage, onNavigate }: PdfOutlineProps) {
  // One state value, written only from the async callbacks below. Flipping a
  // separate `loading` flag synchronously at the top of the effect would
  // schedule a render purely to say "about to start", which React 19's lint
  // rules — correctly — treat as a cascading render.
  const [tree, setTree] = useState<OutlineNode[] | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const loading = tree === null;

  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    doc
      .getOutline()
      .then(async (outline) => {
        const nodes = outline?.length
          ? await buildTree(doc, outline as unknown as RawOutlineItem[], 0)
          : [];
        if (!cancelled) setTree(nodes);
      })
      .catch(() => { if (!cancelled) setTree([]); });
    return () => { cancelled = true; };
  }, [doc]);

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner size={20} />
      </div>
    );
  }

  if (!tree?.length) {
    return (
      <div className="rounded-lg bg-slate-100 p-4 text-center text-sm text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
        <List size={22} className="mx-auto mb-2 opacity-50" />
        <p className="font-medium">No outline</p>
        <p className="mt-1 text-xs">This PDF does not carry a table of contents.</p>
      </div>
    );
  }

  const render = (nodes: OutlineNode[], path: string): React.ReactNode =>
    nodes.map((node, i) => {
      const key = `${path}.${i}`;
      const isCollapsed = collapsed.has(key);
      const active = node.page !== null && node.page === currentPage;
      return (
        <li key={key}>
          <div className="flex items-start">
            {node.children.length > 0 ? (
              <button
                onClick={() =>
                  setCollapsed((prev) => {
                    const next = new Set(prev);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  })
                }
                aria-label={isCollapsed ? 'Expand section' : 'Collapse section'}
                className="mt-1 shrink-0 rounded p-0.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-600"
              >
                <ChevronRight
                  size={12}
                  className={`transition-transform ${isCollapsed ? '' : 'rotate-90'}`}
                />
              </button>
            ) : (
              <span className="w-[17px] shrink-0" />
            )}
            <button
              onClick={() => node.page && onNavigate(node.page)}
              disabled={node.page === null}
              title={node.title}
              className={`flex-1 rounded px-1.5 py-1 text-left text-xs transition-colors disabled:opacity-50 ${
                active
                  ? 'bg-primary-100 font-medium text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-600'
              }`}
              style={{ paddingLeft: `${node.depth * 8 + 6}px` }}
            >
              <span className="line-clamp-2">{node.title}</span>
              {node.page !== null && (
                <span className="ml-1 tabular-nums text-[10px] text-slate-400">{node.page}</span>
              )}
            </button>
          </div>
          {node.children.length > 0 && !isCollapsed && (
            <ul>{render(node.children, key)}</ul>
          )}
        </li>
      );
    });

  return <ul className="space-y-0.5">{render(tree, 'root')}</ul>;
}
