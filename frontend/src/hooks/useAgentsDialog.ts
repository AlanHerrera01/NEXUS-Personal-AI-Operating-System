import { useContext } from 'react';
import {
  AgentsDialogContext,
  type AgentsDialogContextValue,
} from '../app/providers/agents-dialog-context';

/** Open the shared dialog for creating or switching the active agent. */
export function useAgentsDialog(): AgentsDialogContextValue {
  const value = useContext(AgentsDialogContext);
  if (value === null) {
    throw new Error('useAgentsDialog must be used within an AgentsDialogProvider');
  }
  return value;
}
