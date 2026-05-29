import { NavLink, Outlet } from 'react-router-dom';

export function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/5 bg-ink-950/70 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-5 flex items-center justify-between">
          <NavLink to="/" className="flex items-center gap-3 group">
            <span className="w-8 h-8 rounded-md bg-gradient-to-br from-brand to-brand-bright grid place-items-center font-bold text-ink-950">
              ⬡
            </span>
            <div className="leading-tight">
              <div className="text-[11px] uppercase tracking-widest2 text-slate-500">
                Andrew Rea Associates
              </div>
              <div className="text-sm font-semibold text-slate-100">Brand Studio</div>
            </div>
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

      <footer className="border-t border-white/5 mt-12">
        <div className="max-w-6xl mx-auto px-6 py-5 text-xs text-slate-500 flex items-center justify-between">
          <span>andrewreaassociates.com</span>
          <span>
            Authed via{' '}
            <a className="hover:text-slate-200 underline underline-offset-2" href="https://andrewreaassociates.com/admin.html">
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
      className="px-3 py-1.5 rounded-md text-slate-400 hover:text-slate-100 transition data-[active=true]:text-white data-[active=true]:bg-white/10"
    >
      {({ isActive }) => <span data-active={isActive}>{label}</span>}
    </NavLink>
  );
}
