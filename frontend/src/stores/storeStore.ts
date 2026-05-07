import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface StoreState {
  selectedStoreId: string | null;
  setStore: (id: string | null) => void;
}

export const useStoreStore = create<StoreState>()(
  persist(
    (set) => ({
      selectedStoreId: null,
      setStore: (id) => set({ selectedStoreId: id }),
    }),
    { name: 'erp-store' }
  )
);
