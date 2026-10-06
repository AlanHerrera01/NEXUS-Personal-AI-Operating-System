import { RouterProvider } from 'react-router-dom';
import { router } from './app/router';
import './index.css';

function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex">
        {/* Sidebar */}
        <aside className="w-64 bg-white border-r border-gray-200 min-h-screen">
          <div className="p-6 border-b border-gray-200">
            <h1 className="text-xl font-bold text-nexus-600">NEXUS</h1>
            <p className="text-xs text-gray-500">Personal AI Operating System</p>
          </div>
          <nav className="p-4 space-y-2">
            <a href="/" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Chat</a>
            <a href="/activity" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Activity</a>
            <a href="/memory" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Memory</a>
            <a href="/runs" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Agent Runs</a>
            <a href="/tools" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Tools</a>
            <a href="/skills" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Skills</a>
            <a href="/permissions" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Permissions</a>
            <a href="/automation" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Automation</a>
            <a href="/settings" className="block px-4 py-2 rounded hover:bg-gray-100 text-gray-700">Settings</a>
          </nav>
        </aside>
        {/* Main Content */}
        <main className="flex-1">
          <header className="bg-white border-b border-gray-200 px-6 py-4">
            <div className="flex justify-between items-center">
              <h2 className="text-lg font-semibold text-gray-800">Control Center</h2>
              <div className="flex items-center gap-4">
                <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                  ● Agent Ready
                </span>
                <button className="p-2 rounded hover:bg-gray-100">
                  ⚙
                </button>
              </div>
            </div>
          </header>
          <div className="p-6">
            <RouterProvider router={router} />
          </div>
        </main>
      </div>
    </div>
  );
}

export default App
