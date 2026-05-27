import { NavLink, Outlet } from 'react-router-dom';

export function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/5 bg-ink-900/70 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <NavLink to="/" className="flex items-center gap-3 group">
            <span className="w-8 h-8 rounded-md bg-gradient-to-br from-brand to-sky-400 grid place-items-center font-bold text-ink-900">
              ⬡
            </span>
            <span className="text-lg font-semibold tracking-tight">project-neptune</span>
          </NavLink>
        </div>
      </header>

      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-6 py-10">
          <Outlet />
        </div>
      </main>

      <footer className="border-t border-white/5 mt-12">
        <div className="max-w-6xl mx-auto px-6 py-4 text-xs text-slate-500 flex items-center justify-end">
          <span>
            Authed via{' '}
            <a className="hover:text-slate-300" href="https://andrewreaassociates.com/admin.html">
              ara
            </a>
          </span>
        </div>
      </footer>
    </div>
  );
}
