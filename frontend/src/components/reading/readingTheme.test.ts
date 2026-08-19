import { describe, expect, it } from 'vitest';
import {
  DEFAULT_TYPOGRAPHY,
  EPUB_FONTS,
  READING_THEMES,
  READING_THEME_META,
  epubThemeStyles,
  resolveReadingTheme,
} from './readingTheme';

describe('resolveReadingTheme', () => {
  it('follows the dark-family app themes into Night', () => {
    expect(resolveReadingTheme('auto', 'dark')).toBe('night');
    expect(resolveReadingTheme('auto', 'dim')).toBe('night');
  });

  it('follows the Paper app theme', () => {
    expect(resolveReadingTheme('auto', 'paper')).toBe('paper');
  });

  it('leaves a light app theme showing the page as published', () => {
    expect(resolveReadingTheme('auto', 'light')).toBe('plain');
  });

  it('treats an unknown app theme as light rather than throwing', () => {
    expect(resolveReadingTheme('auto', 'something-new')).toBe('plain');
  });

  it('never overrides an explicit choice', () => {
    for (const theme of READING_THEMES) {
      if (theme === 'auto') continue;
      expect(resolveReadingTheme(theme, 'dark')).toBe(theme);
    }
  });
});

describe('READING_THEME_META', () => {
  it('defines every theme except auto', () => {
    const defined = Object.keys(READING_THEME_META).sort();
    const expected = READING_THEMES.filter((t) => t !== 'auto').slice().sort();
    expect(defined).toEqual(expected);
  });

  it('inverts only Night, so figures survive in the warm themes', () => {
    expect(READING_THEME_META.night.pdfFilter).toContain('invert(1)');
    expect(READING_THEME_META.paper.pdfFilter).not.toContain('invert');
    expect(READING_THEME_META.sepia.pdfFilter).not.toContain('invert');
  });

  it('pairs invert with a 180deg hue rotation so colours are not negated', () => {
    expect(READING_THEME_META.night.pdfFilter).toContain('hue-rotate(180deg)');
  });

  it('leaves Plain untouched', () => {
    expect(READING_THEME_META.plain.pdfFilter).toBe('none');
  });
});

describe('epubThemeStyles', () => {
  it('applies the theme colours and the chosen typography', () => {
    const styles = epubThemeStyles('sepia', { font: 'mono', lineHeight: 2.1, margin: 12 });
    expect(styles.body['font-family']).toContain('JetBrains Mono');
    expect(styles.body['line-height']).toBe('2.1 !important');
    expect(styles.body['padding-left']).toBe('12% !important');
    expect(styles.body.background).toContain('#f4ecd8');
  });

  it('marks every declaration important, to beat the publisher stylesheet', () => {
    const styles = epubThemeStyles('night', DEFAULT_TYPOGRAPHY);
    for (const rule of Object.values(styles)) {
      for (const value of Object.values(rule)) {
        expect(value).toContain('!important');
      }
    }
  });

  it('recolours headings and links, not just body text', () => {
    const styles = epubThemeStyles('night', DEFAULT_TYPOGRAPHY);
    const ink = READING_THEME_META.night.epub.color;
    expect(styles['h1, h2, h3, h4, h5, h6'].color).toContain(ink);
    expect(styles.a.color).toContain(ink);
  });

  it('falls back to the first font stack for an unknown font id', () => {
    // `font` comes out of localStorage and can predate a change to the list.
    const styles = epubThemeStyles('plain', {
      ...DEFAULT_TYPOGRAPHY,
      font: 'no-such-font' as (typeof EPUB_FONTS)[number]['id'],
    });
    expect(styles.body['font-family']).toContain(EPUB_FONTS[0].stack);
  });
});
