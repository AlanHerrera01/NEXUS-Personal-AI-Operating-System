import { RouterProvider } from 'react-router-dom';
import { router } from './app/router';
import { OverviewProvider } from './app/providers/OverviewProvider';
import { AgentsDialogProvider } from './app/providers/AgentsDialogProvider';
import './index.css';

function App() {
  return (
    <OverviewProvider>
      {/* Inside the overview provider: the agents dialog refreshes the shared
          dashboard state that every screen reads its active agent from. */}
      <AgentsDialogProvider>
        <RouterProvider router={router} />
      </AgentsDialogProvider>
    </OverviewProvider>
  );
}

export default App;
