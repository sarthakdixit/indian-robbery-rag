import { create } from "zustand";
import { persist } from "zustand/middleware";
import { STORAGE_KEYS } from "@/config/constants";

type AdminAuthStore = {
  password: string | null;
  setPassword: (pw: string) => void;
  clear: () => void;
};

/**
 * Stores the admin password client-side so the user doesn't have to
 * re-enter it on every page load. NOT real authentication — the
 * actual gate is server-side. See AGENT-frontend.md §13.3.
 *
 * Cleared on /admin logout.
 */
export const useAdminAuthStore = create<AdminAuthStore>()(
  persist(
    (set) => ({
      password: null,
      setPassword: (pw) => {
        set({ password: pw });
      },
      clear: () => {
        set({ password: null });
      },
    }),
    { name: STORAGE_KEYS.adminPassword },
  ),
);
