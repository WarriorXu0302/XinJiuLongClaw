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

// ─── 权限 helper hooks（与后端 permissions.py 保持一致）────

export function useHasRole(...required: string[]): boolean {
  const roles = useAuthStore(s => s.roles);
  if (!roles?.length) return false;
  if (roles.includes('admin')) return true;
  return required.some(r => roles.includes(r));
}

export function useIsAdmin(): boolean {
  return useHasRole('admin', 'boss');
}

export function useCanSeeMasterAccount(): boolean {
  // 只有 admin/boss 能看公司总资金池
  return useHasRole('admin', 'boss');
}

export function useCanSeeSalary(): boolean {
  // HR 工资相关：admin / boss / hr（财务不能看工资明细）
  return useHasRole('admin', 'boss', 'hr');
}

export function useCanOperateFundTransfer(): boolean {
  // 资金调拨：admin / boss / finance
  return useHasRole('admin', 'boss', 'finance');
}