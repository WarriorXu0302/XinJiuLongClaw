import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface BrandState {
  selectedBrandId: string | null;
  setBrand: (id: string | null) => void;
}

export const useBrandStore = create<BrandState>()(
  persist(
    (set) => ({
      selectedBrandId: null,
      setBrand: (id) => set({ selectedBrandId: id }),
    }),
    { name: 'erp-brand' }
  )
);