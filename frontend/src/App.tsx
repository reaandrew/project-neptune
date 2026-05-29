import { NavLink, Outlet } from 'react-router-dom';

export function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-ink-300/40 bg-paper/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-5 flex items-center justify-between">
          <NavLink to="/" className="flex items-center gap-3 group">
            <span className="font-display text-2xl tracking-tightest text-ink-900">
              project<span className="text-accent">neptune</span>
            </span>
          </NavLink>
          <nav className="flex items-center gap-1 text-sm">
            <NavTab to="/brands" label="Brands" />
            <NavTab to="/brands/new" label="Register" />
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-6 py-12">
          <Outlet />
        </div>
      </main>

      <footer className="border-t border-ink-300/40">
        <div className="max-w-6xl mx-auto px-6 py-5 text-xs text-ink-500 flex items-center justify-between">
          <span>Andrew Rea Associates · Brand studio</span>
          <span>
            Authed via{' '}
            <a className="underline hover:text-ink-900" href="https://andrewreaassociates.com/admin.html">
              ara
            </a>
          </span>
        </div>
      </footer>
    </div>
  );
}

function NavTab({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className="px-4 py-2 rounded-full transition text-ink-500 hover:text-ink-900 data-[active=true]:bg-ink-900 data-[active=true]:text-paper"
    >
      {({ isActive }) => <span data-active={isActive}>{label}</span>}
    </NavLink>
  );
}
