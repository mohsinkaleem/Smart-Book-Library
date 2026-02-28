import { useState, useCallback } from 'react';

export function useLocalStorage<T>(key: string, defaultValue: T | (() => T)): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) return JSON.parse(stored);
      return typeof defaultValue === 'function' ? (defaultValue as () => T)() : defaultValue;
    } catch {
      return typeof defaultValue === 'function' ? (defaultValue as () => T)() : defaultValue;
    }
  });

  const set = useCallback((v: T) => {
    setValue(v);
    localStorage.setItem(key, JSON.stringify(v));
  }, [key]);

  return [value, set];
}
