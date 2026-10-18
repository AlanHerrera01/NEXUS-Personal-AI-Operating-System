import { useContext } from 'react';
import { OverviewContext, type OverviewContextValue } from '../app/providers/overview-context';

/** Read the shared dashboard state polled from `/api/v1/overview`. */
export function useOverview(): OverviewContextValue {
  const value = useContext(OverviewContext);
  if (value === null) {
    throw new Error('useOverview must be used within an OverviewProvider');
  }
  return value;
}
