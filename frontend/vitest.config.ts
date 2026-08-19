import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // `selection.ts` reads a live `Selection` and walks up to an element, so
    // its tests need a DOM. The other suites are pure and unaffected.
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
});
