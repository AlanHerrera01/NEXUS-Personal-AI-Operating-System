import { RouterProvider } from 'react-router-dom';
import { router } from './app/router';
import { OverviewProvider } from './app/providers/OverviewProvider';
import './index.css';

function App() {
  return (
    <OverviewProvider>
      <RouterProvider router={router} />
    </OverviewProvider>
  );
}

export default App;
