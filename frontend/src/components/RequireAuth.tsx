import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Navigate, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { isLoggedIn } from '../auth';
import { PageFallback } from './Skeleton';

export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const statusQ = useQuery({
    queryKey: ['auth-status'],
    queryFn: api.getAuthStatus,
    staleTime: 60_000,
    retry: 1,
  });

  if (statusQ.isLoading) {
    return <PageFallback />;
  }

  // If status check fails, still require a local key when one is stored,
  // otherwise send to login so the desk isn't left half-open.
  const authRequired = statusQ.data?.auth_required ?? true;

  if (!authRequired) {
    return <>{children}</>;
  }

  if (!isLoggedIn()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
