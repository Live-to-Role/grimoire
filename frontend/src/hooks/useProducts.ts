import { useInfiniteQuery } from '@tanstack/react-query';
import { getProducts, type ProductFilters } from '../api/products';

export function useProducts(filters: ProductFilters = {}) {
  return useInfiniteQuery({
    queryKey: ['products', filters],
    queryFn: ({ pageParam }) => getProducts({ ...filters, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined,
    staleTime: 60000,
  });
}
