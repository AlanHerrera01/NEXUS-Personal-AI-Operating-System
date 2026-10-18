import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { AgentsDialog } from '../../components/agents/AgentsDialog';
import {
  AgentsDialogContext,
  type AgentsDialogContextValue,
} from './agents-dialog-context';

/**
 * Owns the single instance of the agents dialog.
 *
 * The top bar and any screen sitting in the "no active agent" state open the
 * same dialog, so there is one list and one create form rather than a copy per
 * call site. It sits inside ``OverviewProvider`` because a change here has to
 * refresh the shared overview that every screen reads its agent from.
 */
export function AgentsDialogProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  const show = useCallback(() => setOpen(true), []);
  const hide = useCallback(() => setOpen(false), []);
  const value = useMemo<AgentsDialogContextValue>(
    () => ({ open: show, close: hide }),
    [show, hide],
  );

  return (
    <AgentsDialogContext.Provider value={value}>
      {children}
      <AgentsDialog open={open} onClose={hide} />
    </AgentsDialogContext.Provider>
  );
}
