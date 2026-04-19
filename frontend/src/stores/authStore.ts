import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  username: string | null;
  roles: string[];
  brandIds: string[];
  isAuthenticated: boolean;
  login: (accessToken: string, refreshToken: string, username: string, roles: string[], brandIds: string[]) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      username: null,
      roles: [],
      brandIds: [],
      isAuthenticated: false,

      login: (accessToken, refreshToken, username, roles, brandIds) =>
        set({ accessToken, refreshToken, username, roles, brandIds, isAuthenticated: true }),

      logout: () =>
        set({ accessToken: null, refreshToken: null, username: null, roles: [], brandIds: [], isAuthenticated: false }),
    }),
    { name: 'erp-auth' },
  ),
);