/**
 * Page tint for the readers.
 *
 * A PDF page is a raster of black ink on white paper. In dark mode the app
 * chrome went dark around it and the page stayed a floodlight — the canvas
 * has no styleable text to retint, so the only lever is a CSS filter over the
 * rendered bitmap.
 *
 * `invert(1) hue-rotate(180deg)` is the standard pairing: the inversion
 * darkens the paper and lightens the ink, and the 180° rotation puts colour
 * back where it started, so figures and syntax-highlighted code survive
 * instead of turning into negatives.
 *
 * EPUBs go through epub.js themes instead — real text, so real colours.
 */
export const READING_THEMES = ['auto', 'paper', 'sepia', 'night', 'plain'] as const;

export type ReadingTheme = (typeof READING_THEMES)[number];

export interface ReadingThemeMeta {
  label: string;
  hint: string;
  /** CSS `filter` applied to the PDF canvas. */
  pdfFilter: string;
  /** Background behind the page. */
  pdfBackground: string;
  /** epub.js body colours. */
  epub: { background: string; color: string };
  swatch: [string, string];
}

export const READING_THEME_META: Record<Exclude<ReadingTheme, 'auto'>, ReadingThemeMeta> = {
  plain: {
    label: 'Plain',
    hint: 'The page as published',
    pdfFilter: 'none',
    pdfBackground: '#e2e8f0',
    epub: { background: '#ffffff', color: '#0f172a' },
    swatch: ['#ffffff', '#0f172a'],
  },
  paper: {
    label: 'Paper',
    hint: 'Warm white, lower glare',
    // Not a colour overlay: a slight sepia plus a knock-down in brightness
    // keeps the ink black while taking the glare off the paper.
    pdfFilter: 'sepia(0.28) brightness(0.97) contrast(1.02)',
    pdfBackground: '#e7ddc8',
    epub: { background: '#fdfaf3', color: '#43392d' },
    swatch: ['#f5eddc', '#43392d'],
  },
  sepia: {
    label: 'Sepia',
    hint: 'Stronger warmth',
    pdfFilter: 'sepia(0.62) brightness(0.94) contrast(1.05)',
    pdfBackground: '#d8c9a8',
    epub: { background: '#f4ecd8', color: '#5b4636' },
    swatch: ['#f4ecd8', '#5b4636'],
  },
  night: {
    label: 'Night',
    hint: 'Inverted, colours preserved',
    pdfFilter: 'invert(1) hue-rotate(180deg) brightness(0.92) contrast(1.05)',
    pdfBackground: '#0b0f16',
    epub: { background: '#14181f', color: '#c7d0da' },
    swatch: ['#14181f', '#c7d0da'],
  },
};

/**
 * Resolve `auto` against the app theme.
 *
 * `auto` is the default because the app already has four themes and a reader
 * that ignored them was the actual complaint — a white page in a dark app.
 */
export function resolveReadingTheme(
  choice: ReadingTheme,
  appTheme: string,
): Exclude<ReadingTheme, 'auto'> {
  if (choice !== 'auto') return choice;
  if (appTheme === 'dark' || appTheme === 'dim') return 'night';
  if (appTheme === 'paper') return 'paper';
  return 'plain';
}

/** Typography knobs for the EPUB reader. `handleRendition` hardcoded these. */
export const EPUB_FONTS = [
  { id: 'serif', label: 'Serif', stack: 'Georgia, "Iowan Old Style", serif' },
  { id: 'sans', label: 'Sans', stack: 'Inter, system-ui, -apple-system, sans-serif' },
  { id: 'mono', label: 'Mono', stack: '"JetBrains Mono", ui-monospace, monospace' },
  { id: 'dyslexic', label: 'Wide', stack: 'Verdana, Tahoma, sans-serif' },
] as const;

export type EpubFontId = (typeof EPUB_FONTS)[number]['id'];

export interface EpubTypography {
  font: EpubFontId;
  /** Unitless line height. */
  lineHeight: number;
  /** Page margin as a percentage of the viewport width. */
  margin: number;
}

export const DEFAULT_TYPOGRAPHY: EpubTypography = {
  font: 'serif',
  lineHeight: 1.8,
  margin: 6,
};

/** The epub.js theme object for one reading theme plus typography. */
export function epubThemeStyles(
  theme: Exclude<ReadingTheme, 'auto'>,
  typography: EpubTypography,
): Record<string, Record<string, string>> {
  const { background, color } = READING_THEME_META[theme].epub;
  const stack = EPUB_FONTS.find((f) => f.id === typography.font)?.stack ?? EPUB_FONTS[0].stack;

  return {
    // epub.js injects these into the rendered document, which carries the
    // publisher's own stylesheet — hence `!important` throughout.
    body: {
      background: `${background} !important`,
      color: `${color} !important`,
      'font-family': `${stack} !important`,
      'line-height': `${typography.lineHeight} !important`,
      'padding-left': `${typography.margin}% !important`,
      'padding-right': `${typography.margin}% !important`,
    },
    'p, li': {
      'line-height': `${typography.lineHeight} !important`,
      color: `${color} !important`,
    },
    p: { 'margin-bottom': '0.8em !important' },
    'h1, h2, h3, h4, h5, h6': { color: `${color} !important` },
    a: { color: `${color} !important` },
    '::selection': { 'background-color': '#c7d2fe !important' },
  };
}
