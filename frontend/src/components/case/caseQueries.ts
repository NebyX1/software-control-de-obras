import type { QueryClient } from '@tanstack/react-query';

export async function invalidateCase(queryClient: QueryClient, code: string) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['case', code] }),
    queryClient.invalidateQueries({ queryKey: ['case-events', code] }),
    queryClient.invalidateQueries({ queryKey: ['cases'] }),
    queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  ]);
}
