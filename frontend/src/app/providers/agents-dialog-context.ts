import { createContext } from 'react';

export interface AgentsDialogContextValue {
  open: () => void;
  close: () => void;
}

export const AgentsDialogContext = createContext<AgentsDialogContextValue | null>(null);
