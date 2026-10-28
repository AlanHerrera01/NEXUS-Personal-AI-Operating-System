import { RouterProvider } from 'react-router-dom';
import { router } from './app/router';
import { I18nProvider } from './app/providers/I18nProvider';
import { OverviewProvider } from './app/providers/OverviewProvider';
import { AgentsDialogProvider } from './app/providers/AgentsDialogProvider';
import './index.css';
import { AuthGate } from './components/auth/AuthGate';

function App() {
  return (
    /* Outermost: every screen below translates, and the language has to be
       decided before anything renders rather than after the first paint. */
    <I18nProvider>
      <AuthGate>
      <OverviewProvider>
        {/* Inside the overview provider: the agents dialog refreshes the shared
            dashboard state that every screen reads its active agent from. */}
        <AgentsDialogProvider>
          <RouterProvider router={router} />
        </AgentsDialogProvider>
      </OverviewProvider>
      </AuthGate>
    </I18nProvider>
  );
}

export default App;
