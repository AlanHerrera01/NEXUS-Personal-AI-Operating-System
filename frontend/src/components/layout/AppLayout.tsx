import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export function AppLayout() {
  return (
    <div className="bg-background min-h-screen">
      <Sidebar />
      <div className="pl-16 flex flex-col min-h-screen">
        <Topbar />
        <main className="relative pt-14 w-full bg-surface min-h-screen">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
