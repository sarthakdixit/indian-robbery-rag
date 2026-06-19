import { create } from "zustand";

type CitationExpansionStore = {
  expanded: Set<number>;
  toggle: (index: number) => void;
  collapseAll: () => void;
};

/**
 * Tracks which citation cards (by 1-indexed citation number) are
 * expanded to show the full source excerpt. Resets on page navigation
 * (in-memory only, no localStorage).
 */
export const useCitationExpansionStore = create<CitationExpansionStore>((set) => ({
  expanded: new Set(),
  toggle: (index) => {
    set((state) => {
      const next = new Set(state.expanded);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return { expanded: next };
    });
  },
  collapseAll: () => {
    set({ expanded: new Set() });
  },
}));
