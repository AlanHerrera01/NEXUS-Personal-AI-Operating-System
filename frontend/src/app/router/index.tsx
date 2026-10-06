import { createBrowserRouter } from 'react-router-dom';
import Chat from '../../pages/Chat';
import Memory from '../../pages/Memory';
import AgentRuns from '../../pages/AgentRuns';
import Activity from '../../pages/Activity';
import Tools from '../../pages/Tools';
import Skills from '../../pages/Skills';
import Permissions from '../../pages/Permissions';
import Automation from '../../pages/Automation';
import Settings from '../../pages/Settings';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Chat />,
  },
  {
    path: '/chat',
    element: <Chat />,
  },
  {
    path: '/memory',
    element: <Memory />,
  },
  {
    path: '/runs',
    element: <AgentRuns />,
  },
  {
    path: '/runs/:runId',
    element: <AgentRuns />,
  },
  {
    path: '/activity',
    element: <Activity />,
  },
  {
    path: '/tools',
    element: <Tools />,
  },
  {
    path: '/skills',
    element: <Skills />,
  },
  {
    path: '/permissions',
    element: <Permissions />,
  },
  {
    path: '/automation',
    element: <Automation />,
  },
  {
    path: '/settings',
    element: <Settings />,
  },
]);
