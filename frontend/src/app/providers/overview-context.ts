import { createContext } from 'react';
import type { Overview } from '../../types';

export interface OverviewContextValue {
  data: Overview | null;
  loading: boolean;
  error: string | null;
  /** False when the last poll could not reach the backend at all. */
  connected: boolean;
  lastUpdated: number | null;
  refresh: () => void;
}

export const OverviewContext = createContext<OverviewContextValue | null>(null);
