import { useBrandStore } from './brandStore';

/**
 * Returns query params object with brand_id if a brand is selected.
 * Use in useQuery queryFn: api.get('/xxx', { params: useBrandParams() })
 */
export function useBrandParams(): Record<string, string> {
  const brandId = useBrandStore.getState().selectedBrandId;
  return brandId ? { brand_id: brandId } : {};
}

/**
 * Returns [brandId, params] for use in queryKey and queryFn.
 * queryKey should include brandId for cache isolation.
 */
export function useBrandFilter() {
  const brandId = useBrandStore((s) => s.selectedBrandId);
  const params: Record<string, string> = brandId ? { brand_id: brandId } : {};
  return { brandId, params };
}