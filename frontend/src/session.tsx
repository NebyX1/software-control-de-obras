import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from './api/endpoints';
import { setCsrfToken } from './api/client';
import type { User } from './api/types';

interface SessionValue {
  user: User;
  can: (permission: string) => boolean;
  setUser: (user: User) => void;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export const SESSION_KEY = ['session'] as const;

export function useSessionQuery() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: async () => {
      const data = await authApi.me();
      setCsrfToken(data.csrf_token);
      return data.user;
    },
    retry: false,
    staleTime: 60_000,
  });
}

export function SessionProvider({ user, children }: { user: User; children: ReactNode }) {
  const queryClient = useQueryClient();

  const value = useMemo<SessionValue>(() => {
    const permissions = new Set(user.permissions);
    return {
      user,
      can: (permission) => permissions.has(permission),
      setUser: (next) => queryClient.setQueryData(SESSION_KEY, next),
      logout: async () => {
        try {
          await authApi.logout();
        } finally {
          setCsrfToken(null);
          queryClient.clear();
          queryClient.setQueryData(SESSION_KEY, null);
        }
      },
    };
  }, [user, queryClient]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession debe usarse dentro de SessionProvider');
  return value;
}
