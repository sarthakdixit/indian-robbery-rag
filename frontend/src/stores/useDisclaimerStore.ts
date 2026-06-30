import { create } from "zustand";
import { persist } from "zustand/middleware";
import { STORAGE_KEYS } from "@/config/constants";

type DisclaimerStore = {
  isAccepted: boolean;
  accept: () => void;
  reset: () => void; // dev-only; useful when testing the modal flow
};

/**
 * Tracks whether the user has acknowledged the legal disclaimer.
 * Persisted to localStorage so it survives page reloads — once
 * accepted, the modal stays dismissed for that browser.
 *
 * Reset by clearing localStorage or calling `reset()` from the
 * devtools (e.g., `useDisclaimerStore.getState().reset()`).
 */
export const useDisclaimerStore = create<DisclaimerStore>()(
  persist(
    (set) => ({
      isAccepted: false,
      accept: () => {
        set({ isAccepted: true });
      },
      reset: () => {
        set({ isAccepted: false });
      },
    }),
    { name: STORAGE_KEYS.disclaimerAccepted },
  ),
);
