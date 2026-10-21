import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom lacks these; antd reads them while mounting.
class ResizeObserverStub implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// Tests choose the OS preference by replacing window.matchMedia themselves;
// this default is "light, no listeners".
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

// antd sizes an auto-growing textarea from getComputedStyle; jsdom answers with empty values, which
// turns the height into NaN. Padding and border default to 0px, the rest passes through untouched.
const realGetComputedStyle = window.getComputedStyle.bind(window);
vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) => {
  const style = realGetComputedStyle(element, pseudo);
  return new Proxy(style, {
    get(target, property) {
      if (property === "getPropertyValue") {
        return (name: string) => {
          const value = target.getPropertyValue(name);
          return value || (name.startsWith("padding-") || name.startsWith("border-") ? "0px" : value);
        };
      }
      const value = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
});

// Newer Node versions ship an experimental global localStorage that shadows
// jsdom's and throws without --localstorage-file. Tests get a plain in-memory
// Storage so they behave the same on every Node version.
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}
vi.stubGlobal("localStorage", memoryStorage());
vi.stubGlobal("sessionStorage", memoryStorage());

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});
